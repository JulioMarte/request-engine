from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.contextual_terms_supersession_commands import (
    PostgresContextualTermsSupersessionCommands,
)
from request_engine.modules.booking.application.commands.supersede_booking_context_terms import (
    SupersedeBookingContextTermsCommand,
    supersede_booking_context_terms,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
    find_appointment_slots,
)
from request_engine.platform.db.session import SessionFactory

from .dummy_data import F1ContextualScenario, create_contextual_cardiology_scenario

PgConnection = Connection[Any]


def _revision(conn: PgConnection, scenario: F1ContextualScenario) -> int:
    row = conn.execute(
        "SELECT revision FROM request_engine.booking_context_terms WHERE organization_id=%s AND id=%s",
        (scenario.organization_id, scenario.context_terms_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


async def _slot(
    scenario: F1ContextualScenario,
    session_factory: SessionFactory,
    start: datetime,
) -> object:
    return (
        await find_appointment_slots(
            PostgresAppointmentAvailabilityReader(session_factory),
            FindAppointmentSlotsQuery(
                organization_id=scenario.organization_id,
                offering_version_id=scenario.offering_version_id,
                location_id=scenario.location_id,
                window_start=start,
                window_end=start.replace(hour=17),
                limit=20,
            ),
        )
    )[0]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_future_terms_are_scheduled_through_semantic_cutover(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    cutover = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
    command = SupersedeBookingContextTermsCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        current_context_terms_id=scenario.context_terms_id,
        expected_current_revision=_revision(admin_conn, scenario),
        effective_from=cutover,
        amount=Decimal("5000"),
        currency="DOP",
        planned_duration_minutes=60,
        bookable=True,
        idempotency_key=f"future-terms-{uuid4().hex}",
    )
    handler = PostgresContextualTermsSupersessionCommands(session_factory)
    future = await supersede_booking_context_terms(handler, command)
    replay = await supersede_booking_context_terms(handler, command)
    assert replay == future
    assert future.effective_from == cutover

    ranges = admin_conn.execute(
        """
        SELECT id, lower(effective_during), upper(effective_during)
        FROM request_engine.booking_context_terms
        WHERE organization_id=%s AND resource_location_assignment_id=%s
          AND offering_version_id=%s ORDER BY lower(effective_during)
        """,
        (scenario.organization_id, scenario.assignment_id, scenario.offering_version_id),
    ).fetchall()
    assert ranges[0][0] == scenario.context_terms_id
    assert ranges[0][2] == cutover
    assert ranges[1][0] == future.context_terms_id
    assert ranges[1][1] == cutover

    current = cast(Any, await _slot(scenario, session_factory, datetime(2026, 8, 17, 13, tzinfo=UTC)))
    after = cast(Any, await _slot(scenario, session_factory, datetime(2026, 8, 24, 13, tzinfo=UTC)))
    assert (current.amount, current.planned_duration_minutes) == (Decimal("4000.000000"), 45)
    assert (after.amount, after.planned_duration_minutes) == (Decimal("5000.000000"), 60)
