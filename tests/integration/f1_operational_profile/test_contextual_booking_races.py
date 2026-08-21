import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from psycopg import Connection
from sqlalchemy import text

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
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _query(fixture: F1ContextualScenario) -> FindAppointmentSlotsQuery:
    return FindAppointmentSlotsQuery(
        organization_id=fixture.organization_id,
        offering_version_id=fixture.offering_version_id,
        location_id=fixture.location_id,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
        limit=10,
    )


def _command(fixture: F1ContextualScenario, slot: AppointmentSlot) -> BookAppointmentCommand:
    return BookAppointmentCommand(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        offering_version_id=fixture.offering_version_id,
        subject_party_id=fixture.subject_party_id,
        start_at=slot.start_at,
        resources=slot.resources,
        idempotency_key=f"race-{uuid4().hex}",
        location_id=fixture.location_id,
        allow_subject_override=True,
        expected_planned_duration_minutes=slot.planned_duration_minutes,
        expected_amount=slot.amount,
        expected_currency=slot.currency,
        expected_location_operational_revision=slot.location_operational_revision,
        expected_configuration_fingerprint=slot.configuration_fingerprint,
    )


async def _discovered_slot(
    fixture: F1ContextualScenario,
    session_factory: SessionFactory,
) -> AppointmentSlot:
    reader = PostgresAppointmentAvailabilityReader(session_factory)
    slots = await find_appointment_slots(reader, _query(fixture))
    assert slots
    return cast(AppointmentSlot, slots[0])


async def _assert_blocked(task: asyncio.Task[object]) -> None:
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_book_serializes_behind_context_price_change_and_fails_stale(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    slot = await _discovered_slot(fixture, session_factory)
    commands = PostgresContextualReservationCommands(session_factory)

    async with tenant_transaction(session_factory, fixture.organization_id) as config_session:
        await config_session.execute(
            text(
                """
                SELECT id
                FROM request_engine.resource_location_assignments
                WHERE organization_id = :organization_id AND id = :assignment_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "assignment_id": fixture.assignment_id,
            },
        )
        booking_task = asyncio.create_task(
            book_appointment(commands, _command(fixture, slot))
        )
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                UPDATE request_engine.booking_context_terms
                   SET amount = 4100
                 WHERE organization_id = :organization_id AND id = :terms_id
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "terms_id": fixture.context_terms_id,
            },
        )

    with pytest.raises(AppointmentOptionStale):
        await asyncio.wait_for(booking_task, timeout=5)
    assert _reservation_count(admin_conn, fixture) == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_book_serializes_behind_location_closure_and_fails_stale(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    slot = await _discovered_slot(fixture, session_factory)
    commands = PostgresContextualReservationCommands(session_factory)

    async with tenant_transaction(session_factory, fixture.organization_id) as config_session:
        await config_session.execute(
            text(
                """
                SELECT id
                FROM request_engine.locations
                WHERE organization_id = :organization_id AND id = :location_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "location_id": fixture.location_id,
            },
        )
        booking_task = asyncio.create_task(
            book_appointment(commands, _command(fixture, slot))
        )
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                INSERT INTO request_engine.location_hours_exceptions (
                    organization_id, location_id, during, exception_kind, reason
                ) VALUES (
                    :organization_id,
                    :location_id,
                    tstzrange(
                        '2026-08-17T13:00:00+00'::timestamptz,
                        '2026-08-17T14:00:00+00'::timestamptz,
                        '[)'
                    ),
                    'unavailable',
                    'concurrent closure'
                )
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "location_id": fixture.location_id,
            },
        )

    with pytest.raises(AppointmentOptionStale):
        await asyncio.wait_for(booking_task, timeout=5)
    assert _reservation_count(admin_conn, fixture) == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_book_serializes_behind_assignment_retirement_and_fails_stale(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = create_contextual_cardiology_scenario(admin_conn)
    slot = await _discovered_slot(fixture, session_factory)
    commands = PostgresContextualReservationCommands(session_factory)

    async with tenant_transaction(session_factory, fixture.organization_id) as config_session:
        # Match the production lifecycle lock order: Location -> Resource -> Assignment.
        await config_session.execute(
            text(
                """
                SELECT id FROM request_engine.locations
                WHERE organization_id = :organization_id AND id = :location_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "location_id": fixture.location_id,
            },
        )
        await config_session.execute(
            text(
                """
                SELECT id FROM request_engine.resources
                WHERE organization_id = :organization_id AND id = :resource_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "resource_id": fixture.resource_id,
            },
        )
        await config_session.execute(
            text(
                """
                SELECT id FROM request_engine.resource_location_assignments
                WHERE organization_id = :organization_id AND id = :assignment_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "assignment_id": fixture.assignment_id,
            },
        )
        booking_task = asyncio.create_task(
            book_appointment(commands, _command(fixture, slot))
        )
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                UPDATE request_engine.resource_location_assignments
                   SET status = 'retired',
                       effective_during = tstzrange(
                           lower(effective_during),
                           '2026-08-17T12:00:00+00'::timestamptz,
                           '[)'
                       )
                 WHERE organization_id = :organization_id AND id = :assignment_id
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "assignment_id": fixture.assignment_id,
            },
        )

    with pytest.raises(AppointmentOptionStale):
        await asyncio.wait_for(booking_task, timeout=5)
    assert _reservation_count(admin_conn, fixture) == 0


def _reservation_count(conn: PgConnection, fixture: F1ContextualScenario) -> int:
    row = conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reservations
        WHERE organization_id = %s
        """,
        (fixture.organization_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
