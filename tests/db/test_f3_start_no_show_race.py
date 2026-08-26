from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from uuid import UUID

import psycopg
import pytest
from f3_live_ops_fixture import PgConnection, create_live_ops_fixture
from psycopg import Connection


def _race(conninfo: str, barrier: Barrier, entry_id: UUID, *, start: bool) -> str:
    conn: Connection[Any] = psycopg.connect(conninfo)
    try:
        barrier.wait()
        with conn.transaction():
            if not start:
                row = conn.execute(
                    "UPDATE request_engine.queue_entries SET status='no_show',revision=revision+1 "
                    "WHERE id=%s AND status='called' RETURNING id",
                    (entry_id,),
                ).fetchone()
                return "no_show" if row is not None else "lost"
            started = conn.execute(
                "SELECT called_at + interval '1 minute' FROM request_engine.queue_entries "
                "WHERE id=%s",
                (entry_id,),
            ).fetchone()
            assert started is not None
            row = conn.execute(
                "UPDATE request_engine.queue_entries SET status='serving',service_started_at=%s,"
                "revision=revision+1 WHERE id=%s AND status='called' RETURNING "
                "organization_id,service_queue_id",
                (started[0], entry_id),
            ).fetchone()
            if row is None:
                return "lost"
            resource = conn.execute(
                "SELECT resource_id,location_id FROM request_engine.resource_location_assignments "
                "WHERE organization_id=%s AND status='active' "
                "AND effective_during @> %s::timestamptz LIMIT 1",
                (row[0], started[0]),
            ).fetchone()
            assert resource is not None
            conn.execute(
                "INSERT INTO request_engine.service_sessions "
                "(organization_id,queue_entry_id,resource_id,location_id,started_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (row[0], entry_id, resource[0], resource[1], started[0]),
            )
            return "start"
    finally:
        conn.close()


@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.adversarial
def test_start_service_vs_no_show_has_one_coherent_winner(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    setup = create_live_ops_fixture(admin_conn)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        start = pool.submit(_race, pg_conninfo, barrier, setup.entry_a_id, start=True)
        no_show = pool.submit(_race, pg_conninfo, barrier, setup.entry_a_id, start=False)
        outcomes = sorted((start.result(timeout=5), no_show.result(timeout=5)))
    assert "lost" in outcomes
    final = admin_conn.execute(
        "SELECT status,service_started_at FROM request_engine.queue_entries WHERE id=%s",
        (setup.entry_a_id,),
    ).fetchone()
    sessions = admin_conn.execute(
        "SELECT count(*) FROM request_engine.service_sessions WHERE queue_entry_id=%s",
        (setup.entry_a_id,),
    ).fetchone()
    assert final is not None and sessions is not None
    if "start" in outcomes:
        assert final[0] == "serving" and final[1] is not None and sessions[0] == 1
    else:
        assert outcomes == ["lost", "no_show"]
        assert final == ("no_show", None) and sessions == (0,)
