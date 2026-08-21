from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.contextual_reservation_commands import (
    PostgresContextualReservationCommands,
)
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    book_appointment,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _add_second_contextual_requirement(
    conn: PgConnection,
    fixture: F1ContextualScenario,
) -> tuple[UUID, UUID, UUID, UUID]:
    suffix = uuid4().hex
    capability_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resource_capabilities (
            organization_id, capability_key, display_name
        ) VALUES (%s, %s, 'Cardiology assistant')
        RETURNING id
        """,
        (fixture.organization_id, f"cardiology-assistant-{suffix}"),
    )
    requirement_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id, offering_version_id, capability_id, ordinal, quantity
        ) VALUES (%s, %s, %s, 2, 1)
        RETURNING id
        """,
        (fixture.organization_id, fixture.offering_version_id, capability_id),
    )
    resource_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, 'Context Assistant', 'exclusive', 1)
        RETURNING id
        """,
        (fixture.organization_id, f"assistant-{suffix}"),
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
    context_terms_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id,
            resource_location_assignment_id,
            offering_version_id,
            effective_during,
            amount,
            currency,
            planned_duration_minutes
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)'),
            4000, 'DOP', 45
        )
        RETURNING id
        """,
        (fixture.organization_id, assignment_id, fixture.offering_version_id),
    )
    return requirement_id, resource_id, assignment_id, context_terms_id


def _book_command(
    fixture: F1ContextualScenario,
    slot: AppointmentSlot,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        location_id=fixture.location_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"multi-context-{uuid4().hex}",
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
async def test_multi_resource_booking_preserves_every_contextual_commercial_source(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    second_requirement_id, second_resource_id, second_assignment_id, second_context_terms_id = (
        _add_second_contextual_requirement(admin_conn, fixture)
    )

    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=fixture.organization_id,
            offering_version_id=fixture.offering_version_id,
            location_id=fixture.location_id,
            window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
            window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
            limit=20,
        ),
    )
    assert slots
    slot = slots[0]
    assert slot.amount == Decimal("4000.000000")
    assert slot.currency == "DOP"
    assert slot.planned_duration_minutes == 45
    assert len(slot.resources) == 2
    assert {choice.requirement_id for choice in slot.resources} == {
        fixture.requirement_id,
        second_requirement_id,
    }
    assert {choice.resource_id for choice in slot.resources} == {
        fixture.resource_id,
        second_resource_id,
    }
    assert {choice.resource_location_assignment_id for choice in slot.resources} == {
        fixture.assignment_id,
        second_assignment_id,
    }

    reservation = await book_appointment(
        PostgresContextualReservationCommands(session_factory),
        _book_command(fixture, slot),
    )

    commitment = admin_conn.execute(
        """
        SELECT offering_version_booking_terms_id, amount, currency, planned_duration_minutes
        FROM request_engine.reservation_commercial_commitments
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert commitment is not None
    assert commitment[0] is not None
    assert commitment[1:] == (Decimal("4000.000000"), "DOP", 45)

    context_sources = admin_conn.execute(
        """
        SELECT booking_context_terms_id
        FROM request_engine.reservation_commercial_commitment_context_terms
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY booking_context_terms_id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert {row[0] for row in context_sources} == {
        fixture.context_terms_id,
        second_context_terms_id,
    }
    assert len(context_sources) == 2

    claim_assignments = admin_conn.execute(
        """
        SELECT resource_location_assignment_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        ORDER BY resource_location_assignment_id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert {row[0] for row in claim_assignments} == {
        fixture.assignment_id,
        second_assignment_id,
    }
    assert len(claim_assignments) == 2
