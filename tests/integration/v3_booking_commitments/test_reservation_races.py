import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import ReservationRevisionConflict
from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.platform.db.session import SessionFactory

from .contextual_booking_support import (
    contextual_book_command,
    contextual_reschedule_command,
    contextual_slot_at,
    create_contextual_tenant,
)

PgConnection = Connection[Any]
RaceCoroutine = Coroutine[Any, Any, object]
RaceResult = object | BaseException


async def _start_behind_reservation_lock(
    admin_conn: PgConnection,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    coroutines: tuple[RaceCoroutine, ...],
) -> list[RaceResult]:
    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
              FROM request_engine.reservations
             WHERE organization_id = %s
               AND id = %s
             FOR UPDATE
            """,
            (organization_id, reservation_id),
        ).fetchone()
        tasks: list[asyncio.Task[object]] = [
            asyncio.create_task(coroutine) for coroutine in coroutines
        ]
        await asyncio.sleep(0.1)

    return list(await asyncio.gather(*tasks, return_exceptions=True))


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_cancel_and_reschedule_serialize_to_one_reservation_revision(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_tenant(admin_conn, "reservation-race")
    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    original_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    moved_start = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)
    resource_id = fixture.resources[0].resource_id

    original_slot = await contextual_slot_at(
        fixture,
        session_factory,
        resource_id=resource_id,
        start_at=original_start,
    )
    moved_slot = await contextual_slot_at(
        fixture,
        session_factory,
        resource_id=resource_id,
        start_at=moved_start,
    )
    reservation = await book_appointment(
        reservations,
        contextual_book_command(fixture, original_slot, key_prefix="race-book"),
    )

    cancel_result, reschedule_result = await _start_behind_reservation_lock(
        admin_conn,
        organization_id=fixture.organization_id,
        reservation_id=reservation.id,
        coroutines=(
            cancel_reservation(
                reservations,
                CancelReservationCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    reservation_id=reservation.id,
                    expected_revision=reservation.revision,
                    reason="reservation-race",
                    idempotency_key=f"cancel-race-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            ),
            reschedule_reservation(
                commitments,
                contextual_reschedule_command(
                    fixture,
                    moved_slot,
                    reservation_id=reservation.id,
                    expected_revision=reservation.revision,
                    key_prefix="reschedule-race",
                ),
            ),
        ),
    )

    successes = [
        result for result in (cancel_result, reschedule_result) if isinstance(result, Reservation)
    ]
    failures = [
        result for result in (cancel_result, reschedule_result) if isinstance(result, BaseException)
    ]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ReservationRevisionConflict)

    stored = admin_conn.execute(
        """
        SELECT status, revision, lower(during), upper(during)
          FROM request_engine.reservations
         WHERE organization_id = %s
           AND id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert stored is not None
    assert stored[1] == reservation.revision + 1

    active_claims = admin_conn.execute(
        """
        SELECT id, status, lower(during), upper(during)
          FROM request_engine.capacity_claims
         WHERE organization_id = %s
           AND reservation_id = %s
           AND status = 'active'
         ORDER BY id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()

    if stored[0] == "cancelled":
        assert stored[2] == reservation.start_at
        assert stored[3] == reservation.end_at
        assert active_claims == []
    else:
        assert stored[0] == "confirmed"
        assert stored[2] == moved_start
        assert stored[3] == moved_start + (reservation.end_at - reservation.start_at)
        assert len(active_claims) == 1
        assert active_claims[0][1] == "active"
        assert active_claims[0][2] == stored[2]
        assert active_claims[0][3] == stored[3]
