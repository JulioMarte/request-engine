import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
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
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
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
    assignment_revision: int
    availability_revision: int


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


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


def _create_fixture(conn: PgConnection) -> BookingFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"commitments-{suffix}", f"Commitment Practice {suffix}"),
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
        (organization_id, f"consult-{suffix}"),
    )
    offering_version_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_versions (
            organization_id, offering_id, version, duration_minutes,
            bookable, booking_policy
        ) VALUES (%s, %s, 1, 30, true, %s::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id, json.dumps({"slot_step_minutes": 15})),
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
        (organization_id, f"physician-{suffix}"),
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
        (organization_id, f"doctor-{suffix}"),
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
    provenance = conn.execute(
        """
        SELECT a.revision, r.availability_revision
        FROM request_engine.resource_location_assignments a
        JOIN request_engine.resources r
          ON r.organization_id = a.organization_id
         AND r.id = a.resource_id
        WHERE a.organization_id = %s AND a.id = %s
        """,
        (organization_id, assignment_id),
    ).fetchone()
    assert provenance is not None
    return BookingFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        location_id=location_id,
        offering_version_id=offering_version_id,
        requirement_id=requirement_id,
        resource_id=resource_id,
        assignment_id=assignment_id,
        assignment_revision=cast(int, provenance[0]),
        availability_revision=cast(int, provenance[1]),
    )


async def _slot_at(
    fixture: BookingFixture,
    session_factory: SessionFactory,
    start_at: datetime,
) -> AppointmentSlot:
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=fixture.organization_id,
            offering_version_id=fixture.offering_version_id,
            location_id=fixture.location_id,
            resource_id=fixture.resource_id,
            window_start=start_at,
            window_end=start_at + timedelta(hours=1),
            limit=20,
        ),
    )
    slot = next((candidate for candidate in slots if candidate.start_at == start_at), None)
    if slot is None:
        raise AssertionError("expected contextual appointment option was not available")
    return slot


def _contextual_book_command(
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


def _reschedule_command(
    fixture: BookingFixture,
    slot: AppointmentSlot,
    *,
    reservation_id: UUID,
    expected_revision: int,
    key: str,
) -> RescheduleReservationCommand:
    assert slot.planned_duration_minutes is not None
    assert slot.amount is not None
    assert slot.currency is not None
    assert slot.location_operational_revision is not None
    assert slot.configuration_fingerprint is not None
    return RescheduleReservationCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        reservation_id=reservation_id,
        expected_revision=expected_revision,
        location_id=fixture.location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        expected_planned_duration_minutes=slot.planned_duration_minutes,
        expected_amount=slot.amount,
        expected_currency=slot.currency,
        expected_location_operational_revision=slot.location_operational_revision,
        expected_configuration_fingerprint=slot.configuration_fingerprint,
        idempotency_key=key,
        allow_subject_override=True,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_self_overlap_reschedule_replaces_claim_without_self_conflict(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    original_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    new_start = datetime(2026, 8, 17, 13, 15, tzinfo=UTC)
    original_slot = await _slot_at(fixture, session_factory, original_start)
    target_slot = await _slot_at(fixture, session_factory, new_start)

    reservation = await book_appointment(
        reservations,
        _contextual_book_command(
            fixture,
            original_slot,
            subject_party_id=fixture.subject_party_id,
        ),
    )
    old_claim = admin_conn.execute(
        """
        SELECT id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert old_claim is not None
    old_claim_id = cast(UUID, old_claim[0])

    moved = await reschedule_reservation(
        commitments,
        _reschedule_command(
            fixture,
            target_slot,
            reservation_id=reservation.id,
            expected_revision=reservation.revision,
            key=f"reschedule-{uuid4().hex}",
        ),
    )
    assert moved.id == reservation.id
    assert moved.start_at == new_start
    assert moved.end_at == datetime(2026, 8, 17, 13, 45, tzinfo=UTC)
    assert moved.revision == reservation.revision + 1

    claim_rows = admin_conn.execute(
        """
        SELECT id, status, replaced_by_claim_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
        ORDER BY created_at, id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert len(claim_rows) == 2
    old_row = next(row for row in claim_rows if row[0] == old_claim_id)
    new_row = next(row for row in claim_rows if row[0] != old_claim_id)
    assert old_row[1] == "replaced"
    assert old_row[2] == new_row[0]
    assert new_row[1] == "active"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_failed_reschedule_rolls_back_original_reservation_and_claim(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    first_subject = fixture.subject_party_id
    second_subject = _create_party(admin_conn, fixture.organization_id, "Second patient")
    first_start = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    blocked_start = datetime(2026, 8, 17, 13, 30, tzinfo=UTC)
    first_slot = await _slot_at(fixture, session_factory, first_start)
    blocked_slot = await _slot_at(fixture, session_factory, blocked_start)

    first = await book_appointment(
        reservations,
        _contextual_book_command(fixture, first_slot, subject_party_id=first_subject),
    )
    await book_appointment(
        reservations,
        _contextual_book_command(fixture, blocked_slot, subject_party_id=second_subject),
    )

    with pytest.raises(AppointmentUnavailable):
        await reschedule_reservation(
            commitments,
            _reschedule_command(
                fixture,
                blocked_slot,
                reservation_id=first.id,
                expected_revision=first.revision,
                key=f"reschedule-fail-{uuid4().hex}",
            ),
        )

    stored = admin_conn.execute(
        """
        SELECT lower(during), upper(during), revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, first.id),
    ).fetchone()
    assert stored == (
        first_start,
        datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
        first.revision,
    )
    active_claims = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, first.id),
    ).fetchone()
    assert active_claims == (1,)
