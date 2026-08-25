from typing import cast
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import LiveOpsFixture, PgConnection, create_live_ops_fixture


def _start_service(
    conn: PgConnection,
    setup: LiveOpsFixture,
    entry_id: UUID,
) -> UUID:
    with conn.transaction():
        started = conn.execute("SELECT clock_timestamp()").fetchone()
        assert started is not None
        conn.execute(
            "UPDATE request_engine.queue_entries SET status='serving',service_started_at=%s,"
            "revision=revision+1 WHERE id=%s",
            (started[0], entry_id),
        )
        row = conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,"
            "actual_workload_classification_id,started_at) VALUES (%s,%s,%s,%s,%s,%s) "
            "RETURNING id",
            (
                setup.organization_id, entry_id, setup.resource_id, setup.location_id,
                setup.actual_workload_id, started[0],
            ),
        ).fetchone()
        assert row is not None
        return cast(UUID, row[0])


@pytest.mark.postgres
@pytest.mark.adversarial
def test_service_session_cannot_commit_without_matching_queue_lifecycle(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    with pytest.raises(psycopg.Error) as error, admin_conn.transaction():
        admin_conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
            "VALUES (%s,%s,%s,%s,clock_timestamp())",
            (setup.organization_id, setup.entry_a_id, setup.resource_id, setup.location_id),
        )
    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE queue_entry_id=%s",
        (setup.entry_a_id,),
    ).fetchone() == (0,)


@pytest.mark.postgres
@pytest.mark.adversarial
def test_execution_preserves_planning_and_expected_vs_actual_classification(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    before = admin_conn.execute(
        "SELECT offering_version_id,during,revision FROM request_engine.reservations WHERE id=%s",
        (setup.reservation_id,),
    ).fetchone()
    session_id = _start_service(admin_conn, setup, setup.entry_a_id)
    observed = admin_conn.execute(
        "SELECT e.expected_workload_classification_id,s.actual_workload_classification_id "
        "FROM request_engine.queue_entries e JOIN request_engine.service_sessions s "
        "ON s.queue_entry_id=e.id WHERE e.id=%s",
        (setup.entry_a_id,),
    ).fetchone()
    assert observed == (setup.expected_workload_id, setup.actual_workload_id)
    assert setup.expected_workload_id != setup.actual_workload_id
    assert admin_conn.execute(
        "SELECT offering_version_id,during,revision FROM request_engine.reservations WHERE id=%s",
        (setup.reservation_id,),
    ).fetchone() == before
    with pytest.raises(psycopg.Error) as error:
        admin_conn.execute(
            "UPDATE request_engine.service_sessions SET queue_entry_id=%s,revision=revision+1 "
            "WHERE id=%s",
            (setup.entry_b_id, session_id),
        )
    assert error.value.sqlstate == "23514"


@pytest.mark.postgres
@pytest.mark.adversarial
def test_live_operation_temporal_constraints_reject_reversed_time(admin_conn: PgConnection) -> None:
    setup = create_live_ops_fixture(admin_conn)
    with pytest.raises(psycopg.Error) as arrival_error:
        admin_conn.execute(
            "INSERT INTO request_engine.queue_entries "
            "(organization_id,service_queue_id,subject_party_id,arrived_at,admitted_at) "
            "VALUES (%s,%s,%s,'2035-01-01T10:00Z','2035-01-01T09:59Z')",
            (setup.organization_id, setup.queue_id, setup.party_a_id),
        )
    assert arrival_error.value.sqlstate == "23514"
    with pytest.raises(psycopg.Error) as completion_error:
        admin_conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,status,started_at,completed_at) "
            "VALUES (%s,%s,%s,%s,'completed','2035-01-01T10:00Z','2035-01-01T09:59Z')",
            (setup.organization_id, setup.entry_a_id, setup.resource_id, setup.location_id),
        )
    assert completion_error.value.sqlstate == "23514"
