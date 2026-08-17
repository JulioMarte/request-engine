import asyncio
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from psycopg import Connection, sql

PgConnection = Connection[Any]

_ALLOWED_RACE_ROOTS = frozenset(
    {
        "requests",
        "reservations",
        "queue_entries",
        "waitlist_entries",
        "reminder_plans",
    }
)


def ungranted_lock_waiters(admin_conn: PgConnection) -> int:
    row = admin_conn.execute(
        """
        SELECT count(DISTINCT pid)
        FROM pg_locks
        WHERE NOT granted
          AND pid IS NOT NULL
          AND pid <> pg_backend_pid()
        """
    ).fetchone()
    assert row is not None
    return int(row[0])


async def wait_for_new_lock_waiters(
    admin_conn: PgConnection,
    *,
    baseline: int,
    expected_new: int,
) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        if ungranted_lock_waiters(admin_conn) >= baseline + expected_new:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"expected at least {expected_new} new PostgreSQL lock waiters above baseline {baseline}"
    )


async def race_behind_row_lock[T](
    admin_conn: PgConnection,
    *,
    table: str,
    organization_id: UUID,
    aggregate_id: UUID,
    first: Coroutine[Any, Any, T],
    second: Coroutine[Any, Any, T],
) -> tuple[T | BaseException, T | BaseException]:
    if table not in _ALLOWED_RACE_ROOTS:
        raise ValueError(f"unsupported race root: {table}")

    with admin_conn.transaction():
        query = sql.SQL(
            "SELECT id FROM request_engine.{} WHERE organization_id = %s AND id = %s FOR UPDATE"
        ).format(sql.Identifier(table))
        locked = admin_conn.execute(query, (organization_id, aggregate_id)).fetchone()
        assert locked == (aggregate_id,)
        baseline = ungranted_lock_waiters(admin_conn)
        first_task = asyncio.create_task(first)
        second_task = asyncio.create_task(second)
        await wait_for_new_lock_waiters(
            admin_conn,
            baseline=baseline,
            expected_new=2,
        )
        assert not first_task.done()
        assert not second_task.done()

    first_result, second_result = await asyncio.gather(
        first_task,
        second_task,
        return_exceptions=True,
    )
    return first_result, second_result
