from __future__ import annotations

import asyncio
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.reservation_commands import lock_resources
from request_engine.platform.db.session import SessionFactory, tenant_transaction

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _organization_with_two_resources(conn: PgConnection) -> tuple[UUID, tuple[UUID, UUID]]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"i26-{suffix}", f"I26 {suffix}"),
    )
    resource_ids = tuple(
        _uuid_row(
            conn,
            """
            INSERT INTO request_engine.resources (
                organization_id, resource_key, display_name,
                capacity_model, capacity_units
            ) VALUES (%s, %s, %s, 'exclusive', 1)
            RETURNING id
            """,
            (
                organization_id,
                f"resource-{ordinal}-{suffix}",
                f"Resource {ordinal} {suffix}",
            ),
        )
        for ordinal in (1, 2)
    )
    return organization_id, cast(tuple[UUID, UUID], resource_ids)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_i26_booking_resource_lock_order_is_canonical_for_reversed_input(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    organization_id, resource_ids = _organization_with_two_resources(admin_conn)
    canonical = tuple(sorted(resource_ids, key=str))
    first_locked = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def first_contender() -> tuple[UUID, ...]:
        async with tenant_transaction(app_session_factory, organization_id) as session:
            resources = await lock_resources(
                session,
                organization_id=organization_id,
                resource_ids=tuple(reversed(resource_ids)),
            )
            first_locked.set()
            await release_first.wait()
            return tuple(resources)

    async def second_contender() -> tuple[UUID, ...]:
        async with tenant_transaction(app_session_factory, organization_id) as session:
            second_started.set()
            resources = await lock_resources(
                session,
                organization_id=organization_id,
                resource_ids=resource_ids,
            )
            return tuple(resources)

    first_task = asyncio.create_task(first_contender())
    await asyncio.wait_for(first_locked.wait(), timeout=5)
    second_task = asyncio.create_task(second_contender())
    await asyncio.wait_for(second_started.wait(), timeout=5)

    # The first transaction owns both rows. The second caller asked for the same
    # roots in the opposite input order and must serialize behind the canonical
    # ORDER BY id lock acquisition rather than completing out of order.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(second_task), timeout=0.1)

    release_first.set()
    first_order = await asyncio.wait_for(first_task, timeout=5)
    second_order = await asyncio.wait_for(second_task, timeout=5)

    assert first_order == canonical
    assert second_order == canonical
