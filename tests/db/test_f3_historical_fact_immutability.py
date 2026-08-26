from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture

EXECUTION_AT = "2035-01-01T09:30Z"
PAUSED_AT = "2035-01-01T09:40Z"
RESUMED_AT = "2035-01-01T09:45Z"
COMPLETED_AT = "2035-01-01T10:00Z"


def _principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.principals "
        "(organization_id,principal_kind,external_subject) "
        "VALUES (%s,'human','f3-history-actor') RETURNING id",
        (organization_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def _start_session(conn: PgConnection) -> tuple[object, UUID, UUID]:
    setup = create_live_ops_fixture(conn)
    principal_id = _principal(conn, setup.organization_id)
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE request_engine.queue_entries SET status='serving',"
            "service_started_at=%s,revision=revision+1 WHERE id=%s",
            (EXECUTION_AT, setup.entry_a_id),
        )
        row = conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,"
            "actual_workload_classification_id,started_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (
                setup.organization_id,
                setup.entry_a_id,
                setup.resource_id,
                setup.location_id,
                setup.actual_workload_id,
                EXECUTION_AT,
            ),
        ).fetchone()
        assert row is not None
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return setup, principal_id, row[0]


@pytest.mark.postgres
@pytest.mark.adversarial
def test_interruption_history_is_append_preserving(admin_conn: PgConnection) -> None:
    setup, principal_id, session_id = _start_session(admin_conn)
    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "UPDATE request_engine.service_sessions SET status='paused',revision=revision+1 "
        "WHERE id=%s",
        (session_id,),
    )
    row = admin_conn.execute(
        "INSERT INTO request_engine.service_session_interruptions "
        "(organization_id,service_session_id,kind,started_at,started_by_principal_id) "
        "VALUES (%s,%s,'break',%s,%s) RETURNING id",
        (setup.organization_id, session_id, PAUSED_AT, principal_id),
    ).fetchone()
    assert row is not None
    interruption_id = row[0]
    admin_conn.execute("COMMIT")

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.service_session_interruptions "
            "SET kind='administrative' WHERE id=%s",
            (interruption_id,),
        )

    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "UPDATE request_engine.service_session_interruptions "
        "SET ended_at=%s,ended_by_principal_id=%s WHERE id=%s",
        (RESUMED_AT, principal_id, interruption_id),
    )
    admin_conn.execute(
        "UPDATE request_engine.service_sessions SET status='active',revision=revision+1 "
        "WHERE id=%s",
        (session_id,),
    )
    admin_conn.execute("COMMIT")

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.service_session_interruptions "
            "SET ended_at=%s WHERE id=%s",
            (COMPLETED_AT, interruption_id),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "DELETE FROM request_engine.service_session_interruptions WHERE id=%s",
            (interruption_id,),
        )


@pytest.mark.postgres
@pytest.mark.adversarial
def test_completed_service_session_is_immutable(admin_conn: PgConnection) -> None:
    setup, _principal_id, session_id = _start_session(admin_conn)
    admin_conn.execute("BEGIN")
    admin_conn.execute(
        "UPDATE request_engine.service_sessions SET status='completed',completed_at=%s,"
        "revision=revision+1 WHERE id=%s",
        (COMPLETED_AT, session_id),
    )
    admin_conn.execute(
        "UPDATE request_engine.queue_entries SET status='completed',completed_at=%s,"
        "revision=revision+1 WHERE id=%s",
        (COMPLETED_AT, setup.entry_a_id),
    )
    admin_conn.execute("COMMIT")

    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "UPDATE request_engine.service_sessions "
            "SET actual_workload_classification_id=%s,revision=revision+1 WHERE id=%s",
            (setup.expected_workload_id, session_id),
        )
    row = admin_conn.execute(
        "SELECT status,completed_at,actual_workload_classification_id,revision "
        "FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert row[2] == setup.actual_workload_id
    assert row[3] == 2
