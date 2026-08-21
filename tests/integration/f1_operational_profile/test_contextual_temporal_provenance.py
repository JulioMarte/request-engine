from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
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


async def _slot_at(
    fixture: F1ContextualScenario,
    session_factory: SessionFactory,
    *,
    window_start: datetime,
    window_end: datetime,
) -> AppointmentSlot:
    reader = PostgresAppointmentAvailabilityReader(session_factory)
    slots = await find_appointment_slots(
        reader,
        FindAppointmentSlotsQuery(
            organization_id=fixture.organization_id,
            offering_version_id=fixture.offering_version_id,
            location_id=fixture.location_id,
            window_start=window_start,
            window_end=window_end,
            limit=20,
        ),
    )
    assert slots
    return slots[0]


def _book_command(
    fixture: F1ContextualScenario,
    slot: AppointmentSlot,
) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        start_at=slot.start_at,
        resources=slot.resources,
        location_id=fixture.location_id,
        idempotency_key=f"temporal-{uuid4().hex}",
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
async def test_committed_capacity_claim_prevents_rewriting_assignment_history(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    slot = await _slot_at(
        fixture,
        session_factory,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
    )
    commands = PostgresContextualReservationCommands(session_factory)
    reservation = await book_appointment(commands, _book_command(fixture, slot))

    claim = admin_conn.execute(
        """
        SELECT resource_location_assignment_id, lower(during), upper(during)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert claim is not None
    assert claim[0] == fixture.assignment_id
    assert claim[1] == slot.start_at
    assert claim[2] == slot.end_at

    with pytest.raises(psycopg.Error) as exc_info:
        admin_conn.execute(
            """
            UPDATE request_engine.resource_location_assignments
               SET effective_during = tstzrange(
                   lower(effective_during),
                   '2026-08-17T12:00:00+00'::timestamptz,
                   '[)'
               )
             WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, fixture.assignment_id),
        )
    assert exc_info.value.sqlstate == "55000"

    assignment = admin_conn.execute(
        """
        SELECT status, upper(effective_during)
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.assignment_id),
    ).fetchone()
    assert assignment == ("active", None)

    surviving_claim = admin_conn.execute(
        """
        SELECT resource_location_assignment_id
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert surviving_claim == (fixture.assignment_id,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_future_context_terms_activate_by_effective_date_and_commit_exact_source(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    boundary = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)

    admin_conn.execute(
        """
        UPDATE request_engine.booking_context_terms
           SET effective_during = tstzrange(
               lower(effective_during), %s::timestamptz, '[)'
           )
         WHERE organization_id = %s AND id = %s
        """,
        (boundary, fixture.organization_id, fixture.context_terms_id),
    )
    future_terms_row = admin_conn.execute(
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
            tstzrange(%s::timestamptz, NULL, '[)'),
            5000, 'DOP', 60
        )
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.assignment_id,
            fixture.offering_version_id,
            boundary,
        ),
    ).fetchone()
    assert future_terms_row is not None
    future_terms_id = future_terms_row[0]

    current_slot = await _slot_at(
        fixture,
        session_factory,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
    )
    assert current_slot.amount == Decimal("4000.000000")
    assert current_slot.currency == "DOP"
    assert current_slot.planned_duration_minutes == 45

    future_slot = await _slot_at(
        fixture,
        session_factory,
        window_start=datetime(2026, 8, 24, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 24, 16, 0, tzinfo=UTC),
    )
    assert future_slot.amount == Decimal("5000.000000")
    assert future_slot.currency == "DOP"
    assert future_slot.planned_duration_minutes == 60
    assert future_slot.end_at - future_slot.start_at == (
        datetime(2026, 8, 24, 14, 0, tzinfo=UTC) - datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
    )

    commands = PostgresContextualReservationCommands(session_factory)
    reservation = await book_appointment(commands, _book_command(fixture, future_slot))

    commitment = admin_conn.execute(
        """
        SELECT amount, currency, planned_duration_minutes
        FROM request_engine.reservation_commercial_commitments
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation.id),
    ).fetchone()
    assert commitment == (Decimal("5000.000000"), "DOP", 60)

    source_rows = admin_conn.execute(
        """
        SELECT booking_context_terms_id
        FROM request_engine.reservation_commercial_commitment_context_terms
        WHERE organization_id = %s AND reservation_id = %s
        ORDER BY booking_context_terms_id
        """,
        (fixture.organization_id, reservation.id),
    ).fetchall()
    assert source_rows == [(future_terms_id,)]
    assert future_terms_id != fixture.context_terms_id
