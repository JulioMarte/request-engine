from __future__ import annotations

import asyncio
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
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.errors import AppointmentUnavailable
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, Reservation
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]
_WINDOW_START = datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
_WINDOW_END = datetime(2026, 8, 17, 14, 0, tzinfo=UTC)


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _capability_for_requirement(conn: PgConnection, requirement_id: UUID) -> UUID:
    return _uuid_row(
        conn,
        """
        SELECT capability_id
        FROM request_engine.offering_resource_requirements
        WHERE id = %s
        """,
        (requirement_id,),
    )


def _add_resource_for_capability(
    conn: PgConnection,
    fixture: F1ContextualScenario,
    *,
    capability_id: UUID,
    display_name: str,
    key_prefix: str,
) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (fixture.organization_id, f"{key_prefix}-{suffix}", display_name),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_capability_assignments (
            organization_id, resource_id, capability_id
        ) VALUES (%s, %s, %s)
        """,
        (fixture.organization_id, resource_id, capability_id),
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
        (fixture.organization_id, resource_id, fixture.location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (fixture.organization_id, assignment_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id, resource_location_assignment_id,
            offering_version_id, effective_during,
            amount, currency, planned_duration_minutes
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)'),
            4000, 'DOP', 45
        )
        """,
        (fixture.organization_id, assignment_id, fixture.offering_version_id),
    )
    return resource_id, assignment_id


def _add_auxiliary_requirement(
    conn: PgConnection,
    fixture: F1ContextualScenario,
    *,
    ordinal: int,
    capability_key: str,
    display_name: str,
    resource_name: str,
) -> tuple[UUID, UUID, UUID]:
    suffix = uuid4().hex
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (fixture.organization_id, f"{capability_key}-{suffix}", display_name),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, %s, 1)
        RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id, capability_id, ordinal),
    )
    resource_id, assignment_id = _add_resource_for_capability(
        conn,
        fixture,
        capability_id=capability_id,
        display_name=resource_name,
        key_prefix=capability_key,
    )
    return requirement_id, resource_id, assignment_id


def _book_command(
    fixture: F1ContextualScenario,
    slot: AppointmentSlot,
    *,
    subject_party_id: UUID,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=subject_party_id,
        location_id=fixture.location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"dental-contention-{uuid4().hex}",
        allow_subject_override=True,
        expected_planned_duration_minutes=slot.planned_duration_minutes,
        expected_amount=slot.amount,
        expected_currency=slot.currency,
        expected_location_operational_revision=slot.location_operational_revision,
        expected_configuration_fingerprint=slot.configuration_fingerprint,
    )


def _choice_by_requirement(slot: AppointmentSlot, requirement_id: UUID) -> UUID:
    choice = next(choice for choice in slot.resources if choice.requirement_id == requirement_id)
    return choice.resource_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
@pytest.mark.capacity
@pytest.mark.adversarial
async def test_two_dentists_cannot_double_book_one_chair_and_one_assistant(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """A dental visit needs dentist + chair + assistant; auxiliary capacity must be authoritative."""
    fixture = create_contextual_cardiology_scenario(admin_conn)
    dentist_capability_id = _capability_for_requirement(admin_conn, fixture.requirement_id)
    second_dentist_id, _ = _add_resource_for_capability(
        admin_conn,
        fixture,
        capability_id=dentist_capability_id,
        display_name="Second dentist",
        key_prefix="dentist",
    )
    chair_requirement_id, chair_id, _ = _add_auxiliary_requirement(
        admin_conn,
        fixture,
        ordinal=2,
        capability_key="dental-chair",
        display_name="Dental chair",
        resource_name="Chair 1",
    )
    assistant_requirement_id, assistant_id, _ = _add_auxiliary_requirement(
        admin_conn,
        fixture,
        ordinal=3,
        capability_key="dental-assistant",
        display_name="Dental assistant",
        resource_name="Assistant 1",
    )
    second_patient_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Second dental patient')
        RETURNING id
        """,
        (fixture.organization_id,),
    )

    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=fixture.organization_id,
            offering_version_id=fixture.offering_version_id,
            location_id=fixture.location_id,
            window_start=_WINDOW_START,
            window_end=_WINDOW_END,
            limit=20,
        ),
    )
    same_start = [slot for slot in slots if slot.start_at == _WINDOW_START]
    assert len(same_start) >= 2
    assert all(len(slot.resources) == 3 for slot in same_start)
    assert {
        _choice_by_requirement(slot, fixture.requirement_id) for slot in same_start
    } >= {fixture.resource_id, second_dentist_id}
    assert {
        _choice_by_requirement(slot, chair_requirement_id) for slot in same_start
    } == {chair_id}
    assert {
        _choice_by_requirement(slot, assistant_requirement_id) for slot in same_start
    } == {assistant_id}

    first_slot = next(
        slot
        for slot in same_start
        if _choice_by_requirement(slot, fixture.requirement_id) == fixture.resource_id
    )
    second_slot = next(
        slot
        for slot in same_start
        if _choice_by_requirement(slot, fixture.requirement_id) == second_dentist_id
    )
    commands = CapacitySafeReservationCommands(session_factory)
    results = await asyncio.gather(
        book_appointment(
            commands,
            _book_command(fixture, first_slot, subject_party_id=fixture.subject_party_id),
        ),
        book_appointment(
            commands,
            _book_command(fixture, second_slot, subject_party_id=second_patient_id),
        ),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, Reservation)]
    losers = [result for result in results if isinstance(result, AppointmentUnavailable)]
    assert len(winners) == 1, results
    assert len(losers) == 1, results

    claims = admin_conn.execute(
        """
        SELECT resource_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, winners[0].id),
    ).fetchall()
    assert len(claims) == 3
    claimed_resources = {row[0] for row in claims}
    assert chair_id in claimed_resources
    assert assistant_id in claimed_resources
