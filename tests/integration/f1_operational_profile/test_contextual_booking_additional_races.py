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
from request_engine.modules.booking.application.errors import (
    AppointmentOptionStale,
    OfferingVersionNotFound,
)
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


def _command(
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
        idempotency_key=f"additional-race-{uuid4().hex}",
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
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        _query(fixture),
    )
    assert slots
    return slots[0]


async def _assert_blocked(task: asyncio.Task[object]) -> None:
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.1)


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


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_assignment_exception_serializes_before_book_and_makes_option_stale(
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
                FROM request_engine.resources
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
        booking_task = asyncio.create_task(book_appointment(commands, _command(fixture, slot)))
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                INSERT INTO request_engine.resource_location_schedule_exceptions (
                    organization_id,
                    resource_location_assignment_id,
                    during,
                    exception_kind
                ) VALUES (
                    :organization_id,
                    :assignment_id,
                    tstzrange(:start_at, :end_at, '[)'),
                    'unavailable'
                )
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "assignment_id": fixture.assignment_id,
                "start_at": slot.start_at,
                "end_at": slot.end_at,
            },
        )

    with pytest.raises(AppointmentOptionStale):
        await asyncio.wait_for(booking_task, timeout=5)
    assert _reservation_count(admin_conn, fixture) == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_resource_wide_exception_serializes_before_book_and_makes_option_stale(
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
                FROM request_engine.resources
                WHERE organization_id = :organization_id AND id = :resource_id
                FOR UPDATE
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "resource_id": fixture.resource_id,
            },
        )
        booking_task = asyncio.create_task(book_appointment(commands, _command(fixture, slot)))
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                INSERT INTO request_engine.schedule_exceptions (
                    organization_id,
                    resource_id,
                    during,
                    exception_kind
                ) VALUES (
                    :organization_id,
                    :resource_id,
                    tstzrange(:start_at, :end_at, '[)'),
                    'unavailable'
                )
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "resource_id": fixture.resource_id,
                "start_at": slot.start_at,
                "end_at": slot.end_at,
            },
        )

    with pytest.raises(AppointmentOptionStale):
        await asyncio.wait_for(booking_task, timeout=5)
    assert _reservation_count(admin_conn, fixture) == 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_recurring_location_hours_change_serializes_and_makes_option_stale(
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
        booking_task = asyncio.create_task(book_appointment(commands, _command(fixture, slot)))
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                UPDATE request_engine.location_operational_hours
                   SET local_start = '10:00'::time
                 WHERE organization_id = :organization_id
                   AND location_id = :location_id
                   AND weekday = 0
                   AND active
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
async def test_offering_deactivation_serializes_before_book_and_makes_option_stale(
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
                SELECT o.id
                FROM request_engine.offerings o
                JOIN request_engine.offering_versions ov
                  ON ov.organization_id = o.organization_id
                 AND ov.offering_id = o.id
                WHERE ov.organization_id = :organization_id
                  AND ov.id = :offering_version_id
                FOR UPDATE OF o
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "offering_version_id": fixture.offering_version_id,
            },
        )
        booking_task = asyncio.create_task(book_appointment(commands, _command(fixture, slot)))
        await _assert_blocked(cast(asyncio.Task[object], booking_task))
        await config_session.execute(
            text(
                """
                UPDATE request_engine.offerings
                   SET active = false,
                       updated_at = clock_timestamp()
                 WHERE organization_id = :organization_id
                   AND id = (
                       SELECT offering_id
                       FROM request_engine.offering_versions
                       WHERE organization_id = :organization_id
                         AND id = :offering_version_id
                   )
                """
            ),
            {
                "organization_id": fixture.organization_id,
                "offering_version_id": fixture.offering_version_id,
            },
        )

    with pytest.raises(AppointmentOptionStale):
        await asyncio.wait_for(booking_task, timeout=5)
    assert _reservation_count(admin_conn, fixture) == 0

    with pytest.raises(OfferingVersionNotFound):
        await find_appointment_slots(
            PostgresAppointmentAvailabilityReader(session_factory),
            _query(fixture),
        )
