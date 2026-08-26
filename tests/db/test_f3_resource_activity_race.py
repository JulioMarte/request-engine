from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_principal
from psycopg import Connection

EXECUTION_AT = "2035-01-01T09:30Z"


def _start_service(conninfo: str, barrier: Barrier, setup: tuple[UUID, ...]) -> str:
    org, entry, resource, location = setup
    conn: Connection[Any] = psycopg.connect(conninfo)
    try:
        barrier.wait()
        with conn.transaction():
            conn.execute(
                "UPDATE request_engine.queue_entries SET status='serving',"
                "service_started_at=%s,revision=revision+1 WHERE id=%s",
                (EXECUTION_AT, entry),
            )
            conn.execute(
                "INSERT INTO request_engine.service_sessions "
                "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (org, entry, resource, location, EXECUTION_AT),
            )
        return "service"
    except psycopg.Error as exc:
        conn.rollback()
        return exc.sqlstate or "postgres-error"
    finally:
        conn.close()


def _start_activity(
    conninfo: str, barrier: Barrier, setup: tuple[UUID, ...], principal: UUID
) -> str:
    org, _, resource, location = setup
    conn: Connection[Any] = psycopg.connect(conninfo)
    try:
        barrier.wait()
        with conn.transaction():
            conn.execute(
                "INSERT INTO request_engine.resource_activities "
                "(organization_id,resource_id,location_id,activity_kind,started_at,"
                "started_by_principal_id) VALUES (%s,%s,%s,'break',%s,%s)",
                (org, resource, location, EXECUTION_AT, principal),
            )
        return "activity"
    except psycopg.Error as exc:
        conn.rollback()
        return exc.sqlstate or "postgres-error"
    finally:
        conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
def test_service_session_and_resource_activity_cannot_both_occupy_resource(
    admin_conn: PgConnection, pg_conninfo: str
) -> None:
    fixture = create_live_ops_fixture(admin_conn)
    principal = create_principal(admin_conn, fixture)
    args = (
        fixture.organization_id,
        fixture.entry_a_id,
        fixture.resource_id,
        fixture.location_id,
    )
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        service = pool.submit(_start_service, pg_conninfo, barrier, args)
        activity = pool.submit(_start_activity, pg_conninfo, barrier, args, principal)
        outcomes = {service.result(timeout=5), activity.result(timeout=5)}
    assert len(outcomes & {"service", "activity"}) == 1
    assert outcomes & {"23P01", "23505"}
    sessions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE resource_id=%s",
        (fixture.resource_id,),
    ).fetchone()
    activities = admin_conn.execute(
        "SELECT count(*) FROM request_engine.resource_activities "
        "WHERE resource_id=%s AND ended_at IS NULL",
        (fixture.resource_id,),
    ).fetchone()
    entry = admin_conn.execute(
        "SELECT status,service_started_at FROM request_engine.queue_entries WHERE id=%s",
        (fixture.entry_a_id,),
    ).fetchone()
    assert sessions is not None and activities is not None and sessions[0] + activities[0] == 1
    if sessions[0] == 1:
        assert entry is not None and entry[0] == "serving" and entry[1] is not None
    else:
        assert entry == ("called", None)
