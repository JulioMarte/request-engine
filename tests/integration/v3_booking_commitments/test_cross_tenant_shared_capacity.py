import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
    CapacitySafeSlotOfferCapacity,
)
from request_engine.modules.booking.application.commands.acquire_capacity_hold import (
    AcquireCapacityHoldCommand,
    acquire_capacity_hold,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
    reschedule_reservation,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.booking.contracts.appointments import ResourceChoice
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

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class TenantBookingFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    offering_id: UUID
    offering_version_id: UUID
    location_id: UUID
    requirement_id: UUID
    resource_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, label: str) -> TenantBookingFixture:
    suffix = f"{label}-{uuid4().hex}"
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (suffix, suffix),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {suffix}"),
    )
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, %s, 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}", f"Main {suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}", f"Consult {suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes, bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 15})),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}", f"Doctor {suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}", f"Doctor {suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.availability_schedules (
            organization_id, resource_id, weekday, local_start, local_end, timezone
        ) VALUES (%s, %s, 0, '09:00', '12:00', 'America/Santo_Domingo')
        """,
        (organization_id, resource_id),
    )
    return TenantBookingFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        location_id=location_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _shared_root(conn: PgConnection) -> UUID:
    global_identity_id = _uuid_row(
        conn,
        "SELECT request_admin.create_global_identity('person', NULL, %s, %s)",
        ("test.control-plane", "verified shared professional"),
    )
    return _uuid_row(
        conn,
        "SELECT request_admin.create_shared_capacity_identity(%s, %s, %s)",
        (global_identity_id, "test.control-plane", "serialize professional capacity"),
    )


def _bind(conn: PgConnection, fixture: TenantBookingFixture, root_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        "SELECT request_admin.activate_shared_capacity_binding(%s, %s, %s, %s, %s)",
        (
            fixture.organization_id,
            fixture.resource_id,
            root_id,
            "test.control-plane",
            "verified tenant Resource binding",
        ),
    )


def _choice(fixture: TenantBookingFixture) -> tuple[ResourceChoice, ...]:
    return (ResourceChoice(fixture.requirement_id, fixture.resource_id),)


def _book(fixture: TenantBookingFixture, start_at: datetime) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        resources=_choice(fixture),
        idempotency_key=f"book-{uuid4().hex}",
        allow_subject_override=True,
    )


def _hold(fixture: TenantBookingFixture, start_at: datetime) -> AcquireCapacityHoldCommand:
    return AcquireCapacityHoldCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        resources=_choice(fixture),
        idempotency_key=f"hold-{uuid4().hex}",
        allow_subject_override=True,
    )


def _two_bound_tenants(
    conn: PgConnection,
) -> tuple[TenantBookingFixture, TenantBookingFixture, UUID]:
    tenant_a = _fixture(conn, "shared-a")
    tenant_b = _fixture(conn, "shared-b")
    root_id = _shared_root(conn)
    _bind(conn, tenant_a, root_id)
    _bind(conn, tenant_b, root_id)
    return tenant_a, tenant_b, root_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_cross_tenant_hold_and_direct_booking_block_each_other(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    tenant_a, tenant_b, _ = _two_bound_tenants(admin_conn)
    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)

    first_start = datetime(2099, 8, 17, 13, 0, tzinfo=UTC)
    await acquire_capacity_hold(commitments, _hold(tenant_a, first_start))
    with pytest.raises(AppointmentUnavailable):
        await book_appointment(reservations, _book(tenant_b, first_start))

    second_start = datetime(2099, 8, 17, 14, 0, tzinfo=UTC)
    await book_appointment(reservations, _book(tenant_a, second_start))
    with pytest.raises(AppointmentUnavailable):
        await acquire_capacity_hold(commitments, _hold(tenant_b, second_start))


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

    original = await book_appointment(reservations, _book(tenant_a, original_start))
    await book_appointment(reservations, _book(tenant_b, blocked_start))

    with pytest.raises(AppointmentUnavailable):
        await reschedule_reservation(
            commitments,
            RescheduleReservationCommand(
                organization_id=tenant_a.organization_id,
                principal_id=tenant_a.principal_id,
                reservation_id=original.id,
                expected_revision=original.revision,
                location_id=tenant_a.location_id,
                start_at=blocked_start,
                resources=_choice(tenant_a),
                idempotency_key=f"reschedule-{uuid4().hex}",
                allow_subject_override=True,
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

    entry = await join_waitlist(
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
        await book_appointment(reservations, _book(tenant_b, start_at))

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
    await book_appointment(reservations, _book(tenant_b, start_at))

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
