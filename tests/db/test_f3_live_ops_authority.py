from datetime import timedelta

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture


@pytest.mark.postgres
@pytest.mark.adversarial
def test_service_session_cannot_predate_called_at(admin_conn: PgConnection) -> None:
    setup = create_live_ops_fixture(admin_conn)
    row = admin_conn.execute(
        "SELECT called_at FROM request_engine.queue_entries WHERE id=%s",
        (setup.entry_a_id,),
    ).fetchone()
    assert row is not None
    started_at = row[0] - timedelta(seconds=1)

    with pytest.raises(psycopg.Error) as error, admin_conn.transaction():
        admin_conn.execute(
            "UPDATE request_engine.queue_entries SET status='serving',service_started_at=%s,"
            "revision=revision+1 WHERE id=%s",
            (started_at, setup.entry_a_id),
        )
        admin_conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                setup.organization_id,
                setup.entry_a_id,
                setup.resource_id,
                setup.location_id,
                started_at,
            ),
        )

    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT status,service_started_at FROM request_engine.queue_entries WHERE id=%s",
        (setup.entry_a_id,),
    ).fetchone() == ("called", None)


@pytest.mark.postgres
@pytest.mark.adversarial
def test_service_session_requires_active_resource_location_assignment(
    admin_conn: PgConnection,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    other_location = admin_conn.execute(
        "INSERT INTO request_engine.locations "
        "(organization_id,location_key,display_name,timezone) "
        "VALUES (%s,'unassigned-live-location','Unassigned','UTC') RETURNING id",
        (setup.organization_id,),
    ).fetchone()
    assert other_location is not None

    with pytest.raises(psycopg.Error) as error:
        admin_conn.execute(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
            "VALUES (%s,%s,%s,%s,'2035-01-01T09:30Z')",
            (
                setup.organization_id,
                setup.entry_a_id,
                setup.resource_id,
                other_location[0],
            ),
        )

    assert error.value.sqlstate == "23514"
    assert admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE queue_entry_id=%s",
        (setup.entry_a_id,),
    ).fetchone() == (0,)
