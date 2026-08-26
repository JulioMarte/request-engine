from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_active_session, create_principal
from psycopg import Connection


def _pause(
    conninfo: str,
    barrier: Barrier,
    organization_id: UUID,
    session_id: UUID,
    principal_id: UUID,
) -> str:
    conn: Connection[Any] = psycopg.connect(conninfo)
    try:
        barrier.wait()
        with conn.transaction():
            started = conn.execute(
                "SELECT started_at + interval '1 minute' "
                "FROM request_engine.service_sessions WHERE id=%s",
                (session_id,),
            ).fetchone()
            assert started is not None
            row = conn.execute(
                "UPDATE request_engine.service_sessions SET status='paused',revision=revision+1 "
                "WHERE organization_id=%s AND id=%s AND status='active' RETURNING id",
                (organization_id, session_id),
            ).fetchone()
            if row is None:
                return "lost"
            conn.execute(
                "INSERT INTO request_engine.service_session_interruptions "
                "(organization_id,service_session_id,kind,started_at,started_by_principal_id) "
                "VALUES (%s,%s,'break',%s,%s)",
                (organization_id, session_id, started[0], principal_id),
            )
            return "paused"
    finally:
        conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
def test_concurrent_pause_creates_exactly_one_open_interruption(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    principal_id = create_principal(admin_conn, setup)
    session_id = create_active_session(admin_conn, setup, setup.entry_a_id)
    barrier = Barrier(2)
    args = (setup.organization_id, session_id, principal_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_pause, pg_conninfo, barrier, *args)
        second = pool.submit(_pause, pg_conninfo, barrier, *args)
        outcomes = sorted((first.result(timeout=5), second.result(timeout=5)))
    assert outcomes == ["lost", "paused"]
    session = admin_conn.execute(
        "SELECT status,revision FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    open_interruptions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_session_interruptions "
        "WHERE service_session_id=%s AND ended_at IS NULL",
        (session_id,),
    ).fetchone()
    assert session == ("paused", 2)
    assert open_interruptions == (1,)
