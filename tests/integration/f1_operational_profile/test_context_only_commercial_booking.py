from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
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

from .dummy_data import create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _create_context_only_offering(
    conn: PgConnection,
    *,
    organization_id: UUID,
    assignment_id: UUID,
    source_requirement_id: UUID,
) -> tuple[UUID, UUID, UUID]:
    capability_row = conn.execute(
        """
        SELECT capability_id
        FROM request_engine.offering_resource_requirements
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, source_requirement_id),
    ).fetchone()
    assert capability_row is not None
    capability_id = cast(UUID, capability_row[0])

    offering_row = conn.execute(
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Context-only cardiology consultation')
        RETURNING id
        """,
        (organization_id, f"context-only-{uuid4().hex}"),
    ).fetchone()
    assert offering_row is not None
    offering_id = cast(UUID, offering_row[0])

    version_row = conn.execute(
        """
        INSERT INTO request_engine.offering_versions (
            organization_id,
            offering_id,
            version,
            duration_minutes,
            bookable,
            booking_policy
        ) VALUES (%s, %s, 1, 30, true, '{"slot_step_minutes": 30}'::jsonb)
        RETURNING id
        """,
        (organization_id, offering_id),
    ).fetchone()
    assert version_row is not None
    offering_version_id = cast(UUID, version_row[0])

    requirement_row = conn.execute(
        """
        INSERT INTO request_engine.offering_resource_requirements (
            organization_id,
            offering_version_id,
            capability_id,
            ordinal,
            quantity
        ) VALUES (%s, %s, %s, 1, 1)
        RETURNING id
        """,
        (organization_id, offering_version_id, capability_id),
    ).fetchone()
    assert requirement_row is not None
    requirement_id = cast(UUID, requirement_row[0])

    context_row = conn.execute(
        """
        INSERT INTO request_engine.booking_context_terms (
            organization_id,
            resource_location_assignment_id,
            offering_version_id,
            effective_during,
            amount,
            currency
        ) VALUES (
            %s,
            %s,
            %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)'),
            4200,
            'DOP'
        )
        RETURNING id
        """,
        (organization_id, assignment_id, offering_version_id),
    ).fetchone()
    assert context_row is not None
    context_terms_id = cast(UUID, context_row[0])

    return offering_version_id, requirement_id, context_terms_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_context_only_price_books_without_fabricating_base_source(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    offering_version_id, requirement_id, context_terms_id = _create_context_only_offering(
        admin_conn,
        organization_id=fixture.organization_id,
        assignment_id=fixture.assignment_id,
        source_requirement_id=fixture.requirement_id,
    )

    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = PostgresContextualReservationCommands(session_factory)
    slots = await find_appointment_slots(
        availability,
        FindAppointmentSlotsQuery(
            organization_id=fixture.organization_id,
            offering_version_id=offering_version_id,
            location_id=fixture.location_id,
            window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
            window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
            limit=20,
        ),
    )
    assert slots
    slot = cast(AppointmentSlot, slots[0])
    assert slot.amount == Decimal("4200.000000")
    assert slot.currency == "DOP"
    assert slot.planned_duration_minutes == 30
    assert slot.resources[0].requirement_id == requirement_id
    assert slot.resources[0].resource_location_assignment_id == fixture.assignment_id
    assert slot.configuration_fingerprint is not None

    reservation = await book_appointment(
        commands,
        BookAppointmentCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            offering_version_id=offering_version_id,
            subject_party_id=fixture.subject_party_id,
            location_id=fixture.location_id,
            start_at=slot.start_at,
            resources=slot.resources,
            idempotency_key=f"f1-context-only-{uuid4().hex}",
            allow_subject_override=True,
            expected_planned_duration_minutes=slot.planned_duration_minutes,
            expected_amount=slot.amount,
            expected_currency=slot.currency,
            expected_location_operational_revision=slot.location_operational_revision,
            expected_configuration_fingerprint=slot.configuration_fingerprint,
        ),
    )

    commitment = admin_conn.execute(
        """
        SELECT
            offering_version_booking_terms_id,
            amount,
            currency,
            planned_duration_minutes,
            configuration_fingerprint
        FROM request_engine.reservation_commercial_commitments
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert commitment == (
        None,
        Decimal("4200.000000"),
        "DOP",
        30,
        slot.configuration_fingerprint,
    )

    context_sources = admin_conn.execute(
        """
        SELECT booking_context_terms_id
        FROM request_engine.reservation_commercial_commitment_context_terms
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert context_sources == [(context_terms_id,)]
