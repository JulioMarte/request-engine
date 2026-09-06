import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.adapters.db.reservation_reader import PostgresReservationReader
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
    cancel_reservation,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.application.queries.get_reservation_status import (
    get_reservation_status,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ReservationStatus
from request_engine.modules.tenancy.adapters.db.party_authority_reader import (
    PostgresPartyAuthorityReader,
)
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


@dataclass(frozen=True, slots=True)
class BookingFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    location_id: UUID
    offering_version_id: UUID
    requirement_id: UUID
    resource_id: UUID
    assignment_id: UUID


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_booking_fixture(conn: PgConnection) -> BookingFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"booking-{suffix}", f"Booking Practice {suffix}"),
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
    subject_party_id = _create_party(conn, organization_id, f"Patient {suffix}")
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Main office', 'America/Santo_Domingo')
        RETURNING id
        """,
        (organization_id, f"main-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (organization_id, location_id),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Medical consultation')
        RETURNING id
        """,
        (organization_id, f"consultation-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id,
            offering_id,
            version,
            duration_minutes,
            bookable,
            booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 30})),
    )
    conn.execute(
        """
        INSERT INTO request_engine.offering_version_booking_terms (
            organization_id, offering_version_id, amount, currency
        ) VALUES (%s, %s, 3500, 'DOP')
        """,
        (organization_id, offering_version_id),
    )
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'General physician')
        RETURNING id
        """,
        (organization_id, f"doctor-{suffix}"),
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
            organization_id, resource_key, display_name,
            capacity_model, capacity_units
        ) VALUES (%s, %s, 'Dr. Resource', 'exclusive', 1)
        RETURNING id
        """,
        (organization_id, f"doctor-resource-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (organization_id, resource_id, capability_id),
    )
    assignment_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        RETURNING id
        """,
        (organization_id, resource_id, location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (organization_id, assignment_id),
    )
    return BookingFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        assignment_id=assignment_id,
    )


def _create_party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, name),
    )


def _slot_query(fixture: BookingFixture) -> FindAppointmentSlotsQuery:
    return FindAppointmentSlotsQuery(
        organization_id=fixture.organization_id,
        offering_version_id=fixture.offering_version_id,
        location_id=fixture.location_id,
        resource_id=fixture.resource_id,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
        limit=20,
    )


def _book_command(
    fixture: BookingFixture,
    slot: AppointmentSlot,
    *,
    subject_party_id: UUID,
) -> BookAppointmentCommand:
    assert slot.planned_duration_minutes is not None
    assert slot.amount is not None
    assert slot.currency is not None
    assert slot.location_operational_revision is not None
    assert slot.configuration_fingerprint is not None
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=subject_party_id,
        location_id=fixture.location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"book-{uuid4().hex}",
        allow_subject_override=True,
        expected_planned_duration_minutes=slot.planned_duration_minutes,
        expected_amount=slot.amount,
        expected_currency=slot.currency,
        expected_location_operational_revision=slot.location_operational_revision,
        expected_configuration_fingerprint=slot.configuration_fingerprint,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_find_book_replay_read_cancel_and_release_slot(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_booking_fixture(admin_conn)
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = CapacitySafeReservationCommands(session_factory)
    reader = PostgresReservationReader(session_factory)
    authority_reader = PostgresPartyAuthorityReader(session_factory)

    slots = await find_appointment_slots(availability, _slot_query(fixture))
    assert len(slots) == 6
    first = slots[0]
    assert first.start_at == datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    assert first.resources[0].requirement_id == fixture.requirement_id
    assert first.resources[0].resource_id == fixture.resource_id
    assert first.resources[0].resource_location_assignment_id == fixture.assignment_id

    booking_command = _book_command(
        fixture,
        first,
        subject_party_id=fixture.subject_party_id,
    )
    reservation = await book_appointment(commands, booking_command)
    replay = await book_appointment(commands, booking_command)
    assert replay == reservation
    assert reservation.status is ReservationStatus.CONFIRMED

    stored = await get_reservation_status(
        reader,
        authority_reader,
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=reservation.id,
        allow_subject_override=True,
    )
    assert stored == reservation

    after_booking = await find_appointment_slots(availability, _slot_query(fixture))
    assert all(slot.start_at != first.start_at for slot in after_booking)

    claim_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert claim_count == (1,)

    cancelled = await cancel_reservation(
        commands,
        CancelReservationCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            reservation_id=reservation.id,
            expected_revision=reservation.revision,
            idempotency_key=f"cancel-{uuid4().hex}",
            reason="patient unavailable",
            allow_subject_override=True,
        ),
    )
    assert cancelled.status is ReservationStatus.CANCELLED

    after_cancel = await find_appointment_slots(availability, _slot_query(fixture))
    assert any(slot.start_at == first.start_at for slot in after_cancel)

    event_types = admin_conn.execute(
        """
        SELECT event_type
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND aggregate_id = %s
        ORDER BY occurred_at, id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert [row[0] for row in event_types] == [
        "reservation.created.v1",
        "reservation.cancelled.v1",
    ]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_concurrent_contextual_booking_serializes_on_resource(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_booking_fixture(admin_conn)
    second_subject = _create_party(admin_conn, fixture.organization_id, "Second patient")
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = CapacitySafeReservationCommands(session_factory)
    slot = (await find_appointment_slots(availability, _slot_query(fixture)))[0]

    first = _book_command(
        fixture,
        slot,
        subject_party_id=fixture.subject_party_id,
    )
    second = _book_command(
        fixture,
        slot,
        subject_party_id=second_subject,
    )

    outcomes = await asyncio.gather(
        book_appointment(commands, first),
        book_appointment(commands, second),
        return_exceptions=True,
    )
    successes = [outcome for outcome in outcomes if not isinstance(outcome, BaseException)]
    failures = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], AppointmentUnavailable)

    confirmed_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
          AND during = tstzrange(%s, %s, '[)')
          AND status = 'confirmed'
        """,
        (fixture.organization_id, slot.start_at, slot.end_at),
    ).fetchone()
    assert confirmed_count == (1,)
