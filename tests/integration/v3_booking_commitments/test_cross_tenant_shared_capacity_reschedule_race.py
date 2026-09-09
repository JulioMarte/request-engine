import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import pytest
from psycopg import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db import reservation_commands as reservation_db
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    reschedule_reservation,
)
from request_engine.platform.db.session import SessionFactory

from .contextual_booking_support import (
    ContextualTenantFixture,
    contextual_book_command,
    contextual_reschedule_command,
    contextual_slot_at,
    create_contextual_tenant,
    uuid_row,
)

PgConnection = Connection[Any]
SharedRootLocker = Callable[[AsyncSession, UUID, tuple[UUID, ...]], Awaitable[None]]


def _shared_root(conn: PgConnection, label: str) -> UUID:
    identity_id = uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", f"verified {label}"),
    )
    return uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (identity_id, "test.control-plane", f"serialize {label}"),
    )


def _bind(
    conn: PgConnection,
    fixture: ContextualTenantFixture,
    resource_id: UUID,
    root_id: UUID,
) -> None:
    conn.execute(
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            resource_id,
            root_id,
            "test.control-plane",
            "cross-tenant reschedule race proof",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_simultaneous_cross_tenant_reschedules_acquire_shared_roots_canonically(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a = create_contextual_tenant(admin_conn, "reschedule-a", resource_count=2)
    tenant_b = create_contextual_tenant(admin_conn, "reschedule-b", resource_count=2)
    root_one = _shared_root(admin_conn, "root-one")
    root_two = _shared_root(admin_conn, "root-two")

    _bind(admin_conn, tenant_a, tenant_a.resources[0].resource_id, root_one)
    _bind(admin_conn, tenant_a, tenant_a.resources[1].resource_id, root_two)
    _bind(admin_conn, tenant_b, tenant_b.resources[0].resource_id, root_two)
    _bind(admin_conn, tenant_b, tenant_b.resources[1].resource_id, root_one)

    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    original_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    target_start = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)

    original_a_slot = await contextual_slot_at(
        tenant_a,
        session_factory,
        resource_id=tenant_a.resources[0].resource_id,
        start_at=original_start,
    )
    original_b_slot = await contextual_slot_at(
        tenant_b,
        session_factory,
        resource_id=tenant_b.resources[0].resource_id,
        start_at=original_start,
    )
    target_a_slot = await contextual_slot_at(
        tenant_a,
        session_factory,
        resource_id=tenant_a.resources[1].resource_id,
        start_at=target_start,
    )
    target_b_slot = await contextual_slot_at(
        tenant_b,
        session_factory,
        resource_id=tenant_b.resources[1].resource_id,
        start_at=target_start,
    )

    original_a, original_b = await asyncio.gather(
        book_appointment(
            reservations,
            contextual_book_command(tenant_a, original_a_slot, key_prefix="original-a"),
        ),
        book_appointment(
            reservations,
            contextual_book_command(tenant_b, original_b_slot, key_prefix="original-b"),
        ),
    )

    barrier = asyncio.Barrier(2)
    original_locker = cast(
        SharedRootLocker,
        reservation_db.__dict__["_lock_shared_capacity_roots"],
    )

    async def synchronized_locker(
        session: AsyncSession,
        organization_id: UUID,
        resource_ids: tuple[UUID, ...],
    ) -> None:
        await asyncio.wait_for(barrier.wait(), timeout=5)
        await original_locker(session, organization_id, resource_ids)

    monkeypatch.setattr(
        reservation_db,
        "_lock_shared_capacity_roots",
        synchronized_locker,
    )

    rescheduled_a, rescheduled_b = await asyncio.wait_for(
        asyncio.gather(
            reschedule_reservation(
                commitments,
                contextual_reschedule_command(
                    tenant_a,
                    target_a_slot,
                    reservation_id=original_a.id,
                    expected_revision=original_a.revision,
                    key_prefix="reschedule-a",
                ),
            ),
            reschedule_reservation(
                commitments,
                contextual_reschedule_command(
                    tenant_b,
                    target_b_slot,
                    reservation_id=original_b.id,
                    expected_revision=original_b.revision,
                    key_prefix="reschedule-b",
                ),
            ),
        ),
        timeout=10,
    )

    assert rescheduled_a.start_at == target_start
    assert rescheduled_b.start_at == target_start
    assert rescheduled_a.revision == original_a.revision + 1
    assert rescheduled_b.revision == original_b.revision + 1

    rows = admin_conn.execute(
        """
        SELECT c.reservation_id, c.resource_id, link.shared_capacity_identity_id
        FROM request_engine.capacity_claims c
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE c.reservation_id = ANY(%s::uuid[])
          AND c.status = 'active'
        ORDER BY c.reservation_id
        """,
        ([original_a.id, original_b.id],),
    ).fetchall()
    assert {(cast(UUID, row[0]), cast(UUID, row[1]), cast(UUID, row[2])) for row in rows} == {
        (original_a.id, tenant_a.resources[1].resource_id, root_two),
        (original_b.id, tenant_b.resources[1].resource_id, root_one),
    }

    states = admin_conn.execute(
        """
        SELECT status, count(*)
        FROM request_engine.capacity_claims
        WHERE reservation_id = ANY(%s::uuid[])
        GROUP BY status
        ORDER BY status
        """,
        ([original_a.id, original_b.id],),
    ).fetchall()
    assert {cast(str, row[0]): cast(int, row[1]) for row in states} == {
        "active": 2,
        "replaced": 2,
    }
