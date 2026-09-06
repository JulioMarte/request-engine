from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
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


def _uuid_row(conn: PgConnection, sql: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _add_second_concurrent_location(
    conn: PgConnection,
    scenario: F1ContextualScenario,
) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    location_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.locations (
            organization_id, location_key, display_name, timezone
        ) VALUES (%s, %s, 'Second clinic', 'America/Santo_Domingo')
        RETURNING id
        """,
        (scenario.organization_id, f"second-clinic-{suffix}"),
    )
    conn.execute(
        """
        INSERT INTO request_engine.location_operational_hours (
            organization_id, location_id, weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '08:00', '17:00')
        """,
        (scenario.organization_id, location_id),
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
        (scenario.organization_id, scenario.resource_id, location_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id, resource_location_assignment_id,
            weekday, local_start, local_end
        ) VALUES (%s, %s, 0, '09:00', '12:00')
        """,
        (scenario.organization_id, assignment_id),
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
        (scenario.organization_id, assignment_id, scenario.offering_version_id),
    )
    return location_id, assignment_id


async def _slot(
    reader: PostgresAppointmentAvailabilityReader,
    scenario: F1ContextualScenario,
    location_id: UUID,
) -> AppointmentSlot:
    slots = await find_appointment_slots(
        reader,
        FindAppointmentSlotsQuery(
            organization_id=scenario.organization_id,
            offering_version_id=scenario.offering_version_id,
            location_id=location_id,
            window_start=_WINDOW_START,
            window_end=_WINDOW_END,
            limit=10,
        ),
    )
    assert slots
    return slots[0]


def _command(
    scenario: F1ContextualScenario,
    slot: AppointmentSlot,
    *,
    subject_party_id: UUID,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        offering_version_id=scenario.offering_version_id,
        subject_party_id=subject_party_id,
        location_id=slot.location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"multilocation-capacity-{uuid4().hex}",
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
@pytest.mark.concurrency
@pytest.mark.capacity
@pytest.mark.adversarial
async def test_same_resource_can_be_assigned_to_two_locations_but_cannot_be_oversold(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    """Concurrent location assignments are legal; the Resource remains one capacity owner."""
    scenario = create_contextual_cardiology_scenario(admin_conn)
    second_location_id, second_assignment_id = _add_second_concurrent_location(admin_conn, scenario)
    second_subject_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Second patient')
        RETURNING id
        """,
        (scenario.organization_id,),
    )

    assignments = admin_conn.execute(
        """
        SELECT location_id, id
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s
          AND resource_id = %s
          AND effective_during @> '2026-08-17T13:00:00+00'::timestamptz
        ORDER BY location_id
        """,
        (scenario.organization_id, scenario.resource_id),
    ).fetchall()
    assert len(assignments) == 2
    assert {row[1] for row in assignments} == {scenario.assignment_id, second_assignment_id}

    reader = PostgresAppointmentAvailabilityReader(session_factory)
    first_slot, second_slot = await asyncio.gather(
        _slot(reader, scenario, scenario.location_id),
        _slot(reader, scenario, second_location_id),
    )
    assert first_slot.start_at == second_slot.start_at
    assert first_slot.end_at == second_slot.end_at
    assert first_slot.resources[0].resource_id == scenario.resource_id
    assert second_slot.resources[0].resource_id == scenario.resource_id
    assert first_slot.resources[0].resource_location_assignment_id == scenario.assignment_id
    assert second_slot.resources[0].resource_location_assignment_id == second_assignment_id

    commands = CapacitySafeReservationCommands(session_factory)
    results = await asyncio.gather(
        book_appointment(
            commands,
            _command(scenario, first_slot, subject_party_id=scenario.subject_party_id),
        ),
        book_appointment(
            commands,
            _command(scenario, second_slot, subject_party_id=second_subject_id),
        ),
        return_exceptions=True,
    )

    winners = [result for result in results if isinstance(result, Reservation)]
    losers = [result for result in results if isinstance(result, AppointmentUnavailable)]
    assert len(winners) == 1, results
    assert len(losers) == 1, results

    reservations = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s AND status = 'confirmed'
        """,
        (scenario.organization_id,),
    ).fetchone()
    assert reservations == (1,)
    claims = admin_conn.execute(
        """
        SELECT count(*), count(DISTINCT resource_id), count(DISTINCT resource_location_assignment_id)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND resource_id = %s
          AND status = 'active'
          AND during && tstzrange(%s, %s, '[)')
        """,
        (scenario.organization_id, scenario.resource_id, first_slot.start_at, first_slot.end_at),
    ).fetchone()
    assert claims == (1, 1, 1)
