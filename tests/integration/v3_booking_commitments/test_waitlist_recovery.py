import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.reservation_commands import (
    PostgresReservationCommands,
)
from request_engine.modules.booking.adapters.db.waitlist_commands import PostgresWaitlistCommands
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.modules.booking.application.waitlist import (
    AcceptSlotOfferCommand,
    CreateSlotOpportunityCommand,
    DeclineSlotOfferCommand,
    JoinWaitlistCommand,
    OfferNextWaitlistCandidateCommand,
    accept_slot_offer,
    create_slot_opportunity,
    decline_slot_offer,
    join_waitlist,
    offer_next_waitlist_candidate,
)
from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.waitlist import SlotOfferStatus, SlotOpportunityStatus
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class WaitlistFixture:
    organization_id: UUID
    principal_id: UUID
    initial_subject_id: UUID
    first_waitlist_subject_id: UUID
    second_waitlist_subject_id: UUID
    competitor_subject_id: UUID
    location_id: UUID
    offering_id: UUID
    offering_version_id: UUID
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


def _party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, name),
    )


def _fixture(conn: PgConnection) -> WaitlistFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Waitlist Practice') RETURNING id
        """,
        (f"waitlist-{suffix}",),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s) RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    initial_subject_id = _party(conn, organization_id, "Initial patient")
    first_waitlist_subject_id = _party(conn, organization_id, "First standby patient")
    second_waitlist_subject_id = _party(conn, organization_id, "Second standby patient")
    competitor_subject_id = _party(conn, organization_id, "Competing patient")
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo') RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Medical consultation') RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, requestable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, true, %s::jsonb) RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 30})),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'General physician') RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 1, 1) RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, location_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'Dr. Waitlist', 'exclusive', 1) RETURNING id
        """,
        (organization_id, location_id, f"doctor-{suffix}"),
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
    return WaitlistFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        initial_subject_id=initial_subject_id,
        first_waitlist_subject_id=first_waitlist_subject_id,
        second_waitlist_subject_id=second_waitlist_subject_id,
        competitor_subject_id=competitor_subject_id,
        location_id=location_id,
        offering_id=offering_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
    )


def _book_command(
    fixture: WaitlistFixture, subject_party_id: UUID, start_at: datetime, key: str
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=subject_party_id,
        location_id=fixture.location_id,
        start_at=start_at,
        resources=(ResourceChoice(fixture.requirement_id, fixture.resource_id),),
        idempotency_key=key,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_cancelled_slot_decline_then_accept_promotes_hold_atomically(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    reservations = PostgresReservationCommands(session_factory)
    waitlist = PostgresWaitlistCommands(session_factory)
    start_at = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)

    original = await book_appointment(
        reservations,
        _book_command(fixture, fixture.initial_subject_id, start_at, f"book-{uuid4().hex}"),
    )
    await cancel_reservation(
        reservations,
        CancelReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=original.id,
            reason="patient_cancelled",
            idempotency_key=f"cancel-{uuid4().hex}",
        ),
    )
    cancellation_event = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND aggregate_id = %s
          AND event_type = 'reservation.cancelled.v1'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (fixture.organization_id, original.id),
    ).fetchone()
    assert cancellation_event is not None
    source_event_id = cast(UUID, cancellation_event[0])

    first = await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_id=fixture.offering_id,
            subject_party_id=fixture.first_waitlist_subject_id,
            location_id=fixture.location_id,
            idempotency_key=f"join-first-{uuid4().hex}",
        ),
    )
    second = await join_waitlist(
        waitlist,
        JoinWaitlistCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_id=fixture.offering_id,
            subject_party_id=fixture.second_waitlist_subject_id,
            location_id=fixture.location_id,
            idempotency_key=f"join-second-{uuid4().hex}",
        ),
    )

    opportunity_command = CreateSlotOpportunityCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        source_event_id=source_event_id,
        source_reservation_id=original.id,
        idempotency_key=f"opportunity-{uuid4().hex}",
    )
    opportunity = await create_slot_opportunity(waitlist, opportunity_command)
    assert await create_slot_opportunity(waitlist, opportunity_command) == opportunity
    assert opportunity.status is SlotOpportunityStatus.OPEN

    first_offer = await offer_next_waitlist_candidate(
        waitlist,
        OfferNextWaitlistCandidateCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_opportunity_id=opportunity.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            idempotency_key=f"offer-first-{uuid4().hex}",
        ),
    )
    assert first_offer.waitlist_entry_id == first.id
    assert first_offer.status is SlotOfferStatus.OFFERED

    held_claim = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND hold_id = %s
          AND reservation_id IS NULL
          AND status = 'active'
        """,
        (fixture.organization_id, first_offer.capacity_hold_id),
    ).fetchone()
    assert held_claim is not None

    declined = await decline_slot_offer(
        waitlist,
        DeclineSlotOfferCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_offer_id=first_offer.id,
            idempotency_key=f"decline-{uuid4().hex}",
        ),
    )
    assert declined.status is SlotOfferStatus.DECLINED
    released = admin_conn.execute(
        """
        SELECT h.status, c.status
        FROM request_engine.capacity_holds h
        JOIN request_engine.capacity_claims c
          ON c.organization_id = h.organization_id AND c.hold_id = h.id
        WHERE h.organization_id = %s AND h.id = %s
        """,
        (fixture.organization_id, first_offer.capacity_hold_id),
    ).fetchone()
    assert released == ("released", "released")

    second_offer = await offer_next_waitlist_candidate(
        waitlist,
        OfferNextWaitlistCandidateCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            slot_opportunity_id=opportunity.id,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            idempotency_key=f"offer-second-{uuid4().hex}",
        ),
    )
    assert second_offer.waitlist_entry_id == second.id
    second_claim = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND hold_id = %s
          AND reservation_id IS NULL
          AND status = 'active'
        """,
        (fixture.organization_id, second_offer.capacity_hold_id),
    ).fetchone()
    assert second_claim is not None
    second_claim_id = cast(UUID, second_claim[0])

    accept_command = AcceptSlotOfferCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        slot_offer_id=second_offer.id,
        idempotency_key=f"accept-{uuid4().hex}",
    )
    accepted = await accept_slot_offer(waitlist, accept_command)
    replay = await accept_slot_offer(waitlist, accept_command)
    assert replay == accepted
    assert accepted.offer.status is SlotOfferStatus.ACCEPTED
    assert accepted.reservation.subject_party_id == fixture.second_waitlist_subject_id
    assert accepted.reservation.start_at == start_at

    final = admin_conn.execute(
        """
        SELECT so.status, w.status, h.status, c.id, c.status, c.reservation_id
        FROM request_engine.slot_opportunities so
        JOIN request_engine.slot_offers offer
          ON offer.organization_id = so.organization_id
         AND offer.slot_opportunity_id = so.id
        JOIN request_engine.waitlist_entries w
          ON w.organization_id = offer.organization_id
         AND w.id = offer.waitlist_entry_id
        JOIN request_engine.capacity_holds h
          ON h.organization_id = offer.organization_id
         AND h.id = offer.capacity_hold_id
        JOIN request_engine.capacity_claims c
          ON c.organization_id = h.organization_id
         AND c.hold_id = h.id
        WHERE so.organization_id = %s
          AND so.id = %s
          AND offer.id = %s
        """,
        (fixture.organization_id, opportunity.id, second_offer.id),
    ).fetchone()
    assert final is not None
    assert final[0] == "filled"
    assert final[1] == "fulfilled"
    assert final[2] == "consumed"
    assert final[3] == second_claim_id
    assert final[4] == "active"
    assert final[5] == accepted.reservation.id

    reservations_for_slot = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
          AND during = tstzrange(%s, %s, '[)')
          AND status = 'confirmed'
        """,
        (
            fixture.organization_id,
            start_at,
            start_at + timedelta(minutes=30),
        ),
    ).fetchone()
    assert reservations_for_slot == (1,)
