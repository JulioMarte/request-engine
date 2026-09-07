from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.booking.application.commands.book_appointment import book_appointment
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.queue.application.commands.accept_slot_offer import (
    AcceptSlotOfferCommand,
    accept_slot_offer,
)
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

from .contextual_booking_support import (
    ContextualTenantFixture,
    contextual_book_command,
    contextual_reschedule_command,
    contextual_slot_at,
    create_contextual_tenant,
    uuid_row,
)

PgConnection = Connection[Any]


def _shared_root(conn: PgConnection) -> UUID:
    global_identity_id = uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", "verified shared professional"),
    )
    return uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (global_identity_id, "test.control-plane", "serialize professional capacity"),
    )


def _bind(conn: PgConnection, fixture: ContextualTenantFixture, root_id: UUID) -> UUID:
    return uuid_row(
        conn,
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            fixture.resources[0].resource_id,
            root_id,
            "test.control-plane",
            "verified tenant Resource binding",
        ),
    )


def _two_bound_tenants(
    conn: PgConnection,
) -> tuple[ContextualTenantFixture, ContextualTenantFixture, UUID]:
    tenant_a = create_contextual_tenant(conn, "shared-a")
    tenant_b = create_contextual_tenant(conn, "shared-b")
    root_id = _shared_root(conn)
    _bind(conn, tenant_a, root_id)
    _bind(conn, tenant_b, root_id)
    return tenant_a, tenant_b, root_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_cross_tenant_reschedule_conflict_rolls_back_original_commitment(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a, tenant_b, root_id = _two_bound_tenants(admin_conn)
    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    original_start = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    blocked_start = datetime(2099, 8, 17, 14, 0, tzinfo=UTC)
    resource_a = tenant_a.resources[0].resource_id
    resource_b = tenant_b.resources[0].resource_id

    original_slot = await contextual_slot_at(
        tenant_a,
        session_factory,
        resource_id=resource_a,
        start_at=original_start,
    )
    blocked_a_slot = await contextual_slot_at(
        tenant_a,
        session_factory,
        resource_id=resource_a,
        start_at=blocked_start,
    )
    blocked_b_slot = await contextual_slot_at(
        tenant_b,
        session_factory,
        resource_id=resource_b,
        start_at=blocked_start,
    )
    original = await book_appointment(
        reservations,
        contextual_book_command(tenant_a, original_slot, key_prefix="shared-original"),
    )
    await book_appointment(
        reservations,
        contextual_book_command(tenant_b, blocked_b_slot, key_prefix="shared-blocker"),
    )

    with pytest.raises(AppointmentUnavailable):
        await reschedule_reservation(
            commitments,
            contextual_reschedule_command(
                tenant_a,
                blocked_a_slot,
                reservation_id=original.id,
                expected_revision=original.revision,
                key_prefix="shared-reschedule",
            ),
        )

    stored = admin_conn.execute(
        """
        SELECT lower(r.during), upper(r.during), r.revision,
               link.shared_capacity_identity_id
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
    assert stored == (
        original_start,
        original_start + timedelta(minutes=30),
        original.revision,
        root_id,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_slot_offer_hold_blocks_foreign_booking_and_acceptance_promotes_same_claim(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a, tenant_b, root_id = _two_bound_tenants(admin_conn)
    waitlist = PostgresWaitlistCommands(session_factory)
    slot_commands = PostgresSlotOfferCommands(
        session_factory,
        capacity=CapacitySafeSlotOfferCapacity(),
        notification=PostgresSlotOfferNotificationIntent(),
    )
    reservations = CapacitySafeReservationCommands(session_factory)
    start_at = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    end_at = start_at + timedelta(minutes=30)
    foreign_slot = await contextual_slot_at(
        tenant_b,
        session_factory,
        resource_id=tenant_b.resources[0].resource_id,
        start_at=start_at,
    )

    entry = await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            offering_id=tenant_a.offering_id,
            subject_party_id=tenant_a.subject_party_id,
            location_id=tenant_a.location_id,
            preferred_resource_id=tenant_a.resources[0].resource_id,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"join-{uuid4().hex}",
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
            idempotency_key=f"opportunity-{uuid4().hex}",
        ),
    )
    offer = await offer_next_waitlist_candidate(
        slot_commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            slot_opportunity_id=opportunity.id,
            offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key=f"offer-{uuid4().hex}",
        ),
    )
    assert offer is not None
    assert offer.waitlist_entry_id == entry.id

    linked_claim = admin_conn.execute(
        """
        SELECT c.id, link.shared_capacity_identity_id
        FROM request_engine.slot_offers so
        JOIN request_engine.capacity_claims c
          ON c.organization_id = so.organization_id
         AND c.hold_id = so.capacity_hold_id
         AND c.status = 'active'
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE so.organization_id = %s AND so.id = %s
        """,
        (tenant_a.organization_id, offer.id),
    ).fetchone()
    assert linked_claim is not None
    claim_id = cast(UUID, linked_claim[0])
    assert linked_claim[1] == root_id

    with pytest.raises(AppointmentUnavailable):
        await book_appointment(
            reservations,
            contextual_book_command(
                tenant_b,
                foreign_slot,
                key_prefix="foreign-blocked-book",
            ),
        )

    accepted = await accept_slot_offer(
        slot_commands,
        AcceptSlotOfferCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            slot_offer_id=offer.id,
            expected_revision=offer.revision,
            idempotency_key=f"accept-{uuid4().hex}",
            allow_subject_override=True,
        ),
    )
    promoted = admin_conn.execute(
        """
        SELECT c.id, c.reservation_id, link.shared_capacity_identity_id
        FROM request_engine.capacity_claims c
        JOIN request_engine.shared_capacity_claim_links link
          ON link.capacity_claim_id = c.id
        WHERE c.id = %s AND c.status = 'active'
        """,
        (claim_id,),
    ).fetchone()
    assert promoted == (claim_id, accepted.reservation.id, root_id)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_booking_closes_slot_opportunity_without_orphan_hold(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
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
    foreign_slot = await contextual_slot_at(
        tenant_b,
        session_factory,
        resource_id=tenant_b.resources[0].resource_id,
        start_at=start_at,
    )

    await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            offering_id=tenant_a.offering_id,
            subject_party_id=tenant_a.subject_party_id,
            location_id=tenant_a.location_id,
            preferred_resource_id=tenant_a.resources[0].resource_id,
            earliest_start=None,
            latest_start=None,
            idempotency_key=f"join-{uuid4().hex}",
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
            idempotency_key=f"opportunity-{uuid4().hex}",
        ),
    )
    await book_appointment(
        reservations,
        contextual_book_command(tenant_b, foreign_slot, key_prefix="foreign-winner-book"),
    )

    offer = await offer_next_waitlist_candidate(
        slot_commands,
        OfferNextWaitlistCandidateCommand(
            organization_id=tenant_a.organization_id,
            principal_id=tenant_a.principal_id,
            slot_opportunity_id=opportunity.id,
            offer_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            idempotency_key=f"offer-{uuid4().hex}",
        ),
    )
    assert offer is None

    opportunity_state = admin_conn.execute(
        """
        SELECT status
        FROM request_engine.slot_opportunities
        WHERE organization_id = %s AND id = %s
        """,
        (tenant_a.organization_id, opportunity.id),
    ).fetchone()
    assert opportunity_state == ("closed",)

    offer_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.slot_offers
        WHERE organization_id = %s AND slot_opportunity_id = %s
        """,
        (tenant_a.organization_id, opportunity.id),
    ).fetchone()
    assert offer_count == (0,)

    orphan_counts = admin_conn.execute(
        """
        SELECT
            (SELECT count(*)
               FROM request_engine.capacity_holds
              WHERE organization_id = %s
                AND during = tstzrange(%s, %s, '[)')),
            (SELECT count(*)
               FROM request_engine.capacity_claims
              WHERE organization_id = %s
                AND during = tstzrange(%s, %s, '[)'))
        """,
        (
            tenant_a.organization_id,
            start_at,
            end_at,
            tenant_a.organization_id,
            start_at,
            end_at,
        ),
    ).fetchone()
    assert orphan_counts == (0, 0)
