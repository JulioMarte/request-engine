from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

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
from request_engine.modules.booking.application.errors import AppointmentOptionStale
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _slot_query(fixture: F1ContextualScenario) -> FindAppointmentSlotsQuery:
    return FindAppointmentSlotsQuery(
        organization_id=fixture.organization_id,
        offering_version_id=fixture.offering_version_id,
        location_id=fixture.location_id,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
        limit=20,
    )


def _book_command(fixture: F1ContextualScenario, slot: object) -> BookAppointmentCommand:
    typed = cast(AppointmentSlot, slot)
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        location_id=fixture.location_id,
        start_at=typed.start_at,
        resources=typed.resources,
        idempotency_key=f"f1-book-{uuid4().hex}",
        allow_subject_override=True,
        expected_planned_duration_minutes=typed.planned_duration_minutes,
        expected_amount=typed.amount,
        expected_currency=typed.currency,
        expected_location_operational_revision=typed.location_operational_revision,
        expected_configuration_fingerprint=typed.configuration_fingerprint,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_find_and_book_persists_assignment_and_commercial_provenance(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = PostgresContextualReservationCommands(session_factory)

    slots = await find_appointment_slots(availability, _slot_query(fixture))
    assert slots
    slot = slots[0]
    assert slot.start_at == datetime(2026, 8, 17, 13, 0, tzinfo=UTC)
    assert slot.end_at == datetime(2026, 8, 17, 13, 45, tzinfo=UTC)
    assert slot.amount == Decimal("4000.000000")
    assert slot.currency == "DOP"
    assert slot.planned_duration_minutes == 45
    assert slot.configuration_fingerprint is not None
    assert slot.resources[0].resource_location_assignment_id == fixture.assignment_id

    reservation = await book_appointment(commands, _book_command(fixture, slot))

    claim = admin_conn.execute(
        """
        SELECT resource_location_assignment_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert claim == (fixture.assignment_id,)

    commitment = admin_conn.execute(
        """
        SELECT amount, currency, planned_duration_minutes, configuration_fingerprint
        FROM request_engine.reservation_commercial_commitments
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert commitment is not None
    assert commitment[0] == Decimal("4000.000000")
    assert commitment[1] == "DOP"
    assert commitment[2] == 45
    assert commitment[3] == slot.configuration_fingerprint

    context_sources = admin_conn.execute(
        """
        SELECT booking_context_terms_id
        FROM request_engine.reservation_commercial_commitment_context_terms
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert context_sources == [(fixture.context_terms_id,)]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_book_rejects_price_change_after_slot_discovery(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = PostgresContextualReservationCommands(session_factory)
    slot = (await find_appointment_slots(availability, _slot_query(fixture)))[0]

    admin_conn.execute(
        """
        UPDATE request_engine.booking_context_terms
           SET amount = 4100
         WHERE organization_id = %s
           AND id = %s
        """,
        (fixture.organization_id, fixture.context_terms_id),
    )

    with pytest.raises(AppointmentOptionStale):
        await book_appointment(commands, _book_command(fixture, slot))

    reservations = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
        """,
        (fixture.organization_id,),
    ).fetchone()
    assert reservations == (0,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_book_rejects_assignment_retirement_after_slot_discovery(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = PostgresContextualReservationCommands(session_factory)
    slot = (await find_appointment_slots(availability, _slot_query(fixture)))[0]

    admin_conn.execute(
        """
        UPDATE request_engine.resource_location_assignments
           SET status = 'retired',
               effective_during = tstzrange(
                   lower(effective_during),
                   '2026-08-17T12:00:00+00'::timestamptz,
                   '[)'
               )
         WHERE organization_id = %s
           AND id = %s
        """,
        (fixture.organization_id, fixture.assignment_id),
    )

    with pytest.raises(AppointmentOptionStale):
        await book_appointment(commands, _book_command(fixture, slot))


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_contextual_book_rejects_location_closure_after_slot_discovery(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    commands = PostgresContextualReservationCommands(session_factory)
    slot = (await find_appointment_slots(availability, _slot_query(fixture)))[0]

    admin_conn.execute(
        """
        INSERT INTO request_engine.location_hours_exceptions (
            organization_id, location_id, during, exception_kind, reason
        ) VALUES (
            %s, %s,
            tstzrange('2026-08-17T13:00:00+00'::timestamptz,
                      '2026-08-17T14:00:00+00'::timestamptz, '[)'),
            'unavailable', 'one-day closure'
        )
        """,
        (fixture.organization_id, fixture.location_id),
    )

    with pytest.raises(AppointmentOptionStale):
        await book_appointment(commands, _book_command(fixture, slot))
