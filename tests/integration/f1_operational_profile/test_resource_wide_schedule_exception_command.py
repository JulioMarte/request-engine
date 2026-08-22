from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.resource_schedule_exception_commands import (
    PostgresResourceScheduleExceptionCommands,
)
from request_engine.modules.booking.application.commands.set_resource_schedule_exception import (
    SetResourceScheduleExceptionCommand,
    set_resource_schedule_exception,
)
from request_engine.modules.booking.application.operational_errors import (
    ResourceAvailabilityRevisionConflict,
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
        """
        SELECT availability_revision
        FROM request_engine.resources
        WHERE organization_id = %s AND id = %s
        """,
        (scenario.organization_id, scenario.resource_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


async def _slots(
    scenario: F1ContextualScenario,
    session_factory: SessionFactory,
) -> tuple[datetime, ...]:
    slots = await find_appointment_slots(
        PostgresAppointmentAvailabilityReader(session_factory),
        FindAppointmentSlotsQuery(
            organization_id=scenario.organization_id,
            offering_version_id=scenario.offering_version_id,
            location_id=scenario.location_id,
            window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
            window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
            limit=20,
        ),
    )
    return tuple(slot.start_at for slot in slots)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.contract
@pytest.mark.adversarial
async def test_resource_wide_exception_is_semantic_idempotent_revisioned_and_effective(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresResourceScheduleExceptionCommands(session_factory)
    initial_revision = _revision(admin_conn, scenario)
    assert datetime(2026, 8, 17, 13, 0, tzinfo=UTC) in await _slots(scenario, session_factory)

    create_command = SetResourceScheduleExceptionCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        resource_id=scenario.resource_id,
        start_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        end_at=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
        exception_kind="unavailable",
        reason="Resource-wide absence",
        expected_resource_availability_revision=initial_revision,
        idempotency_key=f"resource-wide-create-{uuid4().hex}",
    )
    created = await set_resource_schedule_exception(handler, create_command)
    replay = await set_resource_schedule_exception(handler, create_command)
    assert replay == created
    assert created.resource_availability_revision > initial_revision
    assert datetime(2026, 8, 17, 13, 0, tzinfo=UTC) not in await _slots(scenario, session_factory)

    changed = await set_resource_schedule_exception(
        handler,
        SetResourceScheduleExceptionCommand(
            organization_id=scenario.organization_id,
            principal_id=scenario.principal_id,
            authority_party_id=scenario.authority_party_id,
            resource_id=scenario.resource_id,
            exception_id=created.exception_id,
            start_at=datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
            end_at=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
            exception_kind="unavailable",
            reason="Updated Resource-wide absence",
            expected_resource_availability_revision=created.resource_availability_revision,
            idempotency_key=f"resource-wide-update-{uuid4().hex}",
        ),
    )
    assert changed.resource_availability_revision > created.resource_availability_revision
    starts = await _slots(scenario, session_factory)
    assert datetime(2026, 8, 17, 13, 0, tzinfo=UTC) in starts
    assert datetime(2026, 8, 17, 15, 0, tzinfo=UTC) not in starts

    with pytest.raises(ResourceAvailabilityRevisionConflict):
        await set_resource_schedule_exception(
            handler,
            SetResourceScheduleExceptionCommand(
                organization_id=scenario.organization_id,
                principal_id=scenario.principal_id,
                authority_party_id=scenario.authority_party_id,
                resource_id=scenario.resource_id,
                start_at=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
                end_at=datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
                exception_kind="unavailable",
                expected_resource_availability_revision=initial_revision,
                idempotency_key=f"resource-wide-stale-{uuid4().hex}",
            ),
        )
