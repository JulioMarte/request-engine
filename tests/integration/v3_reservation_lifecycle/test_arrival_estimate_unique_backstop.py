import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from ._arrival_estimate_support import PgConnection, wait_until_lock_blocked
from ._arrival_estimate_world import ArrivalWorld, create_arrival_world
from ._authority_race_support import connect

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.concurrency]


def _insert_active_estimate(
    conn: PgConnection,
    world: ArrivalWorld,
    *,
    minutes: int,
    source: str,
) -> None:
    conn.execute(
        "INSERT INTO request_engine.reservation_arrival_estimates"
        " (organization_id, reservation_id, estimated_arrival_at, source_kind)"
        " VALUES (%s, %s, %s, %s)",
        (
            world.organization_id,
            world.reservation_id,
            datetime.now(UTC) + timedelta(minutes=minutes),
            source,
        ),
    )


@pytest.mark.asyncio
async def test_direct_concurrent_insert_violating_one_active_index_is_rejected(
    admin_conn: PgConnection,
) -> None:
    """The partial unique index reservation_arrival_estimates_one_active_uq is the
    PostgreSQL backstop for 'at most one active estimate per reservation', enforced
    even for raw concurrent INSERTs that bypass the application command."""

    world = create_arrival_world(admin_conn)
    holder = connect()
    racer = connect()
    outcome: dict[str, Any] = {}

    def _racer_insert() -> None:
        try:
            _insert_active_estimate(racer, world, minutes=40, source="operator")
            outcome["error"] = None
        except Exception as error:  # noqa: BLE001 - re-asserted precisely below
            outcome["error"] = error
        finally:
            racer.rollback()

    try:
        _insert_active_estimate(holder, world, minutes=15, source="customer")
        thread = threading.Thread(target=_racer_insert, daemon=True)
        thread.start()
        await wait_until_lock_blocked(
            admin_conn,
            "%INSERT INTO request_engine.reservation_arrival_estimates%",
            "concurrent estimate insert never blocked on the one-active unique index",
        )
        holder.commit()
        thread.join(timeout=5)
        assert thread.is_alive() is False
        error = outcome.get("error")
        assert isinstance(error, psycopg.errors.UniqueViolation)
        assert error.sqlstate == "23505"
        assert error.diag.constraint_name == "reservation_arrival_estimates_one_active_uq"
    finally:
        if not holder.closed:
            holder.rollback()
        holder.close()
        if not racer.closed:
            racer.rollback()
        racer.close()

    rows = admin_conn.execute(
        "SELECT estimated_arrival_at, source_kind, superseded_at IS NOT NULL"
        " FROM request_engine.reservation_arrival_estimates"
        " WHERE organization_id = %s AND reservation_id = %s",
        (world.organization_id, world.reservation_id),
    ).fetchall()
    assert len(rows) == 1
    assert (rows[0][1], rows[0][2]) == ("customer", False)
