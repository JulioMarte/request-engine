from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from psycopg import Connection


def _start(
    conninfo: str,
    barrier: Barrier,
    organization_id: UUID,
    entry_id: UUID,
    resource_id: UUID,
    location_id: UUID,
) -> str:
    conn: Connection[Any] = psycopg.connect(conninfo)
    try:
        barrier.wait()
        with conn.transaction():
            started = conn.execute("SELECT clock_timestamp()").fetchone()
            assert started is not None
            conn.execute(
                "UPDATE request_engine.queue_entries SET status='serving',service_started_at=%s,"
                "revision=revision+1 WHERE id=%s",
                (started[0], entry_id),
            )
            conn.execute(
                "INSERT INTO request_engine.service_sessions "
                "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (organization_id, entry_id, resource_id, location_id, started[0]),
            )
        return "committed"
    except psycopg.Error as exc:
        conn.rollback()
        return exc.sqlstate or "postgres-error"
    finally:
        conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
def test_same_resource_concurrent_service_start_has_one_clean_winner(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    barrier = Barrier(2)
    common = (setup.organization_id, setup.resource_id, setup.location_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            _start, pg_conninfo, barrier, common[0], setup.entry_a_id, common[1], common[2]
        )
        second = pool.submit(
            _start, pg_conninfo, barrier, common[0], setup.entry_b_id, common[1], common[2]
        )
        outcomes = sorted((first.result(timeout=5), second.result(timeout=5)))
    assert outcomes == ["23P01", "committed"]
    sessions = admin_conn.execute(
        "SELECT queue_entry_id FROM request_engine.service_sessions "
        "WHERE organization_id=%s AND resource_id=%s AND status IN ('active','paused')",
        (setup.organization_id, setup.resource_id),
    ).fetchall()
    assert len(sessions) == 1
    statuses = dict(
        admin_conn.execute(
            "SELECT id,status FROM request_engine.queue_entries WHERE id IN (%s,%s)",
            (setup.entry_a_id, setup.entry_b_id),
        ).fetchall()
    )
    winner = sessions[0][0]
    loser = setup.entry_b_id if winner == setup.entry_a_id else setup.entry_a_id
    assert statuses[winner] == "serving"
    assert statuses[loser] == "called"
