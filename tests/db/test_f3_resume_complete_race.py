from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from f3_live_ops_race_support import create_paused_session
from psycopg import Connection


def _resume(
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
            state = conn.execute(
                "SELECT status,revision FROM request_engine.service_sessions "
                "WHERE id=%s FOR UPDATE",
                (session_id,),
            ).fetchone()
            assert state == ("paused", 2)
            ended_at = conn.execute(
                "SELECT started_at + interval '1 minute' "
                "FROM request_engine.service_session_interruptions "
                "WHERE service_session_id=%s AND ended_at IS NULL",
                (session_id,),
            ).fetchone()
            assert ended_at is not None
            ended = conn.execute(
                "UPDATE request_engine.service_session_interruptions "
                "SET ended_at=%s,ended_by_principal_id=%s "
                "WHERE service_session_id=%s AND ended_at IS NULL RETURNING id",
                (ended_at[0], principal_id, session_id),
            ).fetchone()
            assert ended is not None
            conn.execute(
                "UPDATE request_engine.service_sessions SET status='active',revision=revision+1 "
                "WHERE organization_id=%s AND id=%s",
                (organization_id, session_id),
            )
            return "resumed"
    finally:
        conn.close()


def _complete_attempt(conninfo: str, barrier: Barrier, session_id: UUID) -> str:
    conn: Connection[Any] = psycopg.connect(conninfo)
    try:
        barrier.wait()
        with conn.transaction():
            state = conn.execute(
                "SELECT status,revision FROM request_engine.service_sessions "
                "WHERE id=%s FOR UPDATE",
                (session_id,),
            ).fetchone()
            assert state is not None
            if state[1] != 2:
                return "stale"
            if state[0] != "active":
                return "not_actionable"
            raise AssertionError("completion cannot legitimately win from a paused revision")
    finally:
        conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
def test_resume_vs_complete_preserves_paused_intent_and_one_revision_winner(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    session_id, principal_id = create_paused_session(admin_conn, setup)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resume = pool.submit(
            _resume, pg_conninfo, barrier, setup.organization_id, session_id, principal_id
        )
        complete = pool.submit(_complete_attempt, pg_conninfo, barrier, session_id)
        outcomes = {resume.result(timeout=5), complete.result(timeout=5)}
    assert "resumed" in outcomes
    assert outcomes & {"stale", "not_actionable"}
    state = admin_conn.execute(
        "SELECT status,revision,completed_at FROM request_engine.service_sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    open_interruptions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_session_interruptions "
        "WHERE service_session_id=%s AND ended_at IS NULL",
        (session_id,),
    ).fetchone()
    assert state == ("active", 3, None)
    assert open_interruptions == (0,)
