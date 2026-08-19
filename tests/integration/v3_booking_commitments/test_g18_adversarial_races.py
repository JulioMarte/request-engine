# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db import reservation_commands as reservation_db
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
    acquire_capacity_hold,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.booking.application.commands.confirm_capacity_hold import (
    ConfirmCapacityHoldCommand,
    confirm_capacity_hold,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    CapacityHoldExpired,
)
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.create_slot_opportunity import (
    CreateSlotOpportunityCommand,
    create_slot_opportunity,
)
from request_engine.modules.queue.application.commands.join_waitlist import (
    JoinWaitlistCommand,
    join_waitlist,
)
from request_engine.modules.queue.application.commands.offer_next_waitlist_candidate import (
    OfferNextWaitlistCandidateCommand,
    offer_next_waitlist_candidate,
)
from request_engine.platform.db.session import SessionFactory

from .test_booking_commitments import _choice, _create_fixture
from .test_cross_tenant_shared_capacity import _book, _two_bound_tenants
from .test_cross_tenant_shared_capacity_reschedule_race import (
    _bind as _bind_reschedule_resource,
)
from .test_cross_tenant_shared_capacity_reschedule_race import _book_command as _race_book_command
from .test_cross_tenant_shared_capacity_reschedule_race import (
    _reschedule_command as _race_reschedule_command,
)
from .test_cross_tenant_shared_capacity_reschedule_race import (
    _shared_root as _reschedule_shared_root,
)
from .test_cross_tenant_shared_capacity_reschedule_race import _tenant as _reschedule_tenant

PgConnection = Connection[Any]
RaceCoroutine = Coroutine[Any, Any, Any]
SharedRootLocker = Callable[[AsyncSession, UUID, tuple[UUID, ...]], Awaitable[None]]


async def _force_shared_root_winner(
    monkeypatch: pytest.MonkeyPatch,
    *,
    winner_organization_id: UUID,
    winner: RaceCoroutine,
    loser: RaceCoroutine,
) -> tuple[Any, Any]:
    """Hold the winner after it owns the shared root while the loser reaches that lock."""

    winner_locked = asyncio.Event()
    release_winner = asyncio.Event()
    original_locker = cast(
        SharedRootLocker,
        reservation_db.__dict__["_lock_shared_capacity_roots"],
    )

    async def controlled_locker(
        session: AsyncSession,
        organization_id: UUID,
        resource_ids: tuple[UUID, ...],
    ) -> None:
        await original_locker(session, organization_id, resource_ids)
        if organization_id == winner_organization_id and not winner_locked.is_set():
            winner_locked.set()
            await asyncio.wait_for(release_winner.wait(), timeout=5)

    monkeypatch.setattr(
        reservation_db,
        "_lock_shared_capacity_roots",
        controlled_locker,
    )

    winner_task = asyncio.create_task(winner)
    await asyncio.wait_for(winner_locked.wait(), timeout=5)
    loser_task = asyncio.create_task(loser)
    await asyncio.sleep(0.1)
    release_winner.set()
    winner_result, loser_result = await asyncio.wait_for(
        asyncio.gather(winner_task, loser_task, return_exceptions=True),
        timeout=10,
    )
    return winner_result, loser_result


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_hold_confirmation_waiting_past_authoritative_expiry_is_rejected(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """R02: a confirmer blocked on the Hold lock must re-check DB wall-clock expiry."""

    fixture = _create_fixture(admin_conn)
    commitments = PostgresBookingCommitmentCommands(session_factory)
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    expires_at = datetime.now(UTC) + timedelta(seconds=1)
    hold = await acquire_capacity_hold(
        commitments,
        AcquireCapacityHoldCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_version_id=fixture.offering_version_id,
            subject_party_id=fixture.subject_party_id,
            location_id=fixture.location_id,
            start_at=start_at,
            expires_at=expires_at,
            resources=_choice(fixture),
            idempotency_key=f"g18-expiry-hold-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )

    with admin_conn.transaction():
        admin_conn.execute(
            """
            SELECT id
            FROM request_engine.capacity_holds
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, hold.id),
        ).fetchone()
        confirm_task = asyncio.create_task(
            confirm_capacity_hold(
                commitments,
                ConfirmCapacityHoldCommand(
                    organization_id=fixture.organization_id,
                    principal_id=fixture.principal_id,
                    hold_id=hold.id,
                    expected_revision=hold.revision,
                    idempotency_key=f"g18-expiry-confirm-{uuid4().hex}",
                    allow_subject_override=True,
                ),
            )
        )
        await asyncio.sleep(0.1)
        remaining = max((hold.expires_at - datetime.now(UTC)).total_seconds(), 0.0)
        await asyncio.sleep(remaining + 0.1)

    result = await asyncio.wait_for(
        asyncio.gather(confirm_task, return_exceptions=True),
        timeout=5,
    )
    assert len(result) == 1
    assert isinstance(result[0], CapacityHoldExpired)

    graph = admin_conn.execute(
        """
        SELECT h.status,
               h.revision,
               h.expires_at <= clock_timestamp() AS expired_by_db_clock,
               (SELECT count(*)
                  FROM request_engine.reservations r
                 WHERE r.organization_id = h.organization_id
                   AND r.subject_party_id = h.subject_party_id
                   AND r.during = h.during),
               (SELECT count(*)
                  FROM request_engine.capacity_claims c
                 WHERE c.organization_id = h.organization_id
                   AND c.hold_id = h.id
                   AND c.reservation_id IS NULL
                   AND c.status = 'active')
        FROM request_engine.capacity_holds h
        WHERE h.organization_id = %s AND h.id = %s
        """,
        (fixture.organization_id, hold.id),
    ).fetchone()
    assert graph == ("active", hold.revision, True, 0, 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.parametrize("winner", ["booking", "slot_offer"])
async def test_direct_booking_vs_foreign_slot_offer_has_one_capacity_owner_in_both_orders(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
    winner: str,
) -> None:
    """R26: force both shared-root winner orders for Booking versus SlotOffer."""

    tenant_a, tenant_b, _ = _two_bound_tenants(admin_conn)
    waitlist = PostgresWaitlistCommands(session_factory)
    slot_commands = PostgresSlotOfferCommands(
        session_factory,
        capacity=CapacitySafeSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    reservations = CapacitySafeReservationCommands(session_factory)
    start_at = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)

    await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            offering_id=tenant_a.offering_id,
            subject_party_id=tenant_a.subject_party_id,
            location_id=tenant_a.location_id,
            preferred_resource_id=tenant_a.resource_id,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"g18-waitlist-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    opportunity = await create_slot_opportunity(
        waitlist,
        CreateSlotOpportunityCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            offering_version_id=tenant_a.offering_version_id,
            location_id=tenant_a.location_id,
            source_event_id=uuid4(),
            start_at=start_at,
            end_at=end_at,
            idempotency_key=f"g18-opportunity-{uuid4().hex}",
        ),
    )

    booking_race = book_appointment(reservations, _book(tenant_b, start_at))
    offer_race = offer_next_waitlist_candidate(
        slot_commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            slot_opportunity_id=opportunity.id,
            offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key=f"g18-offer-{uuid4().hex}",
        ),
    )

    if winner == "booking":
        booking_result, offer_result = await _force_shared_root_winner(
            monkeypatch,
            winner_organization_id=tenant_b.organization_id,
            winner=booking_race,
            loser=offer_race,
        )
        assert not isinstance(booking_result, BaseException)
        assert offer_result is None
    else:
        offer_result, booking_result = await _force_shared_root_winner(
            monkeypatch,
            winner_organization_id=tenant_a.organization_id,
            winner=offer_race,
            loser=booking_race,
        )
        assert offer_result is not None
        assert not isinstance(offer_result, BaseException)
        assert isinstance(booking_result, AppointmentUnavailable)

    graph = admin_conn.execute(
        """
        SELECT o.status,
               (SELECT count(*)
                  FROM request_engine.slot_offers so
                 WHERE so.organization_id = o.organization_id
                   AND so.slot_opportunity_id = o.id
                   AND so.status = 'offered'),
               (SELECT count(*)
                  FROM request_engine.capacity_holds h
                 WHERE h.organization_id = o.organization_id
                   AND h.during = tstzrange(%s, %s, '[)')
                   AND h.status = 'active'
                   AND h.expires_at > clock_timestamp()),
               (SELECT count(*)
                  FROM request_engine.capacity_claims c
                 WHERE c.organization_id = o.organization_id
                   AND c.during = tstzrange(%s, %s, '[)')
                   AND c.status = 'active'),
               (SELECT count(*)
                  FROM request_engine.reservations r
                 WHERE r.organization_id = %s
                   AND r.during = tstzrange(%s, %s, '[)')
                   AND r.status = 'confirmed')
        FROM request_engine.slot_opportunities o
        WHERE o.organization_id = %s AND o.id = %s
        """,
        (
            start_at,
            end_at,
            start_at,
            end_at,
            tenant_b.organization_id,
            start_at,
            end_at,
            tenant_a.organization_id,
            opportunity.id,
        ),
    ).fetchone()
    if winner == "booking":
        assert graph == ("closed", 0, 0, 0, 1)
    else:
        assert graph == ("open", 1, 1, 1, 0)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_foreign_shared_booking_winning_race_rolls_back_reschedule_completely(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R27: force foreign capacity to win while a reschedule targets that shared root."""

    tenant_a = _reschedule_tenant(admin_conn, "g18-reschedule-a")
    tenant_b = _reschedule_tenant(admin_conn, "g18-reschedule-b")
    original_root = _reschedule_shared_root(admin_conn, "g18-original-root")
    target_root = _reschedule_shared_root(admin_conn, "g18-target-root")

    _bind_reschedule_resource(admin_conn, tenant_a, tenant_a.resource_ids[0], original_root)
    _bind_reschedule_resource(admin_conn, tenant_a, tenant_a.resource_ids[1], target_root)
    _bind_reschedule_resource(admin_conn, tenant_b, tenant_b.resource_ids[0], target_root)

    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    original_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    target_start = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)

    original = await book_appointment(
        reservations,
        _race_book_command(tenant_a, tenant_a.resource_ids[0], original_start),
    )

    foreign_booking = book_appointment(
        reservations,
        _race_book_command(tenant_b, tenant_b.resource_ids[0], target_start),
    )
    conflicting_reschedule = reschedule_reservation(
        commitments,
        _race_reschedule_command(
            tenant_a,
            reservation_id=original.id,
            expected_revision=original.revision,
            resource_id=tenant_a.resource_ids[1],
            start_at=target_start,
        ),
    )
    booking_result, reschedule_result = await _force_shared_root_winner(
        monkeypatch,
        winner_organization_id=tenant_b.organization_id,
        winner=foreign_booking,
        loser=conflicting_reschedule,
    )
    assert not isinstance(booking_result, BaseException)
    assert isinstance(reschedule_result, AppointmentUnavailable)

    original_graph = admin_conn.execute(
        """
        SELECT lower(r.during), upper(r.during), r.revision, r.status,
               c.resource_id, c.status, link.shared_capacity_identity_id
        FROM request_engine.reservations r
        JOIN request_engine.capacity_claims c
          ON c.organization_id = r.organization_id
         AND c.reservation_id = r.id
         AND c.status = 'active'
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE r.organization_id = %s AND r.id = %s
        """,
        (tenant_a.organization_id, original.id),
    ).fetchone()
    assert original_graph == (
        original_start,
        original_start + timedelta(minutes=30),
        original.revision,
        "confirmed",
        tenant_a.resource_ids[0],
        "active",
        original_root,
    )

    leaked_target_state = admin_conn.execute(
        """
        SELECT
            (SELECT count(*)
               FROM request_engine.capacity_claims c
              WHERE c.organization_id = %s
                AND c.reservation_id = %s
                AND c.resource_id = %s),
            (SELECT count(*)
               FROM request_engine.capacity_claims c
              WHERE c.organization_id = %s
                AND c.reservation_id = %s
                AND c.status = 'replaced')
        """,
        (
            tenant_a.organization_id,
            original.id,
            tenant_a.resource_ids[1],
            tenant_a.organization_id,
            original.id,
        ),
    ).fetchone()
    assert leaked_target_state == (0, 0)
