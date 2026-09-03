import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from .triage_scenario import PgConnection


async def _wait_for_queue_waiters(conn: PgConnection, minimum: int) -> None:
    for _ in range(200):
        row = conn.execute(
            """
            SELECT count(*)
              FROM pg_catalog.pg_stat_activity
             WHERE datname = current_database()
               AND pid <> pg_backend_pid()
               AND wait_event_type = 'Lock'
               AND query ILIKE '%service_queues%'
            """
        ).fetchone()
        assert row is not None
        if row[0] >= minimum:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"expected {minimum} queue-lock waiters")


async def race_behind_queue_lock(
    conn: PgConnection,
    organization_id: UUID,
    queue_id: UUID,
    *coroutines: Coroutine[Any, Any, object],
) -> tuple[object, ...]:
    tasks: list[asyncio.Task[object]] = []
    with conn.transaction():
        conn.execute(
            """
            SELECT id FROM request_engine.service_queues
             WHERE organization_id = %s AND id = %s FOR UPDATE
            """,
            (organization_id, queue_id),
        ).fetchone()
        tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
        await _wait_for_queue_waiters(conn, len(tasks))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return tuple(results)
