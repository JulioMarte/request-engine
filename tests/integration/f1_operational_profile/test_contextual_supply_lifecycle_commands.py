from datetime import UTC, date, datetime, time
from typing import Any, cast
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.contextual_supply_lifecycle_commands import (
    PostgresContextualSupplyLifecycleCommands,
)
from request_engine.modules.booking.application.commands.retire_resource_location_assignment import (  # noqa: E501
    RetireResourceLocationAssignmentCommand,
    retire_resource_location_assignment,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityWindow,
    SetResourceLocationAvailabilityCommand,
    set_resource_location_availability,
)
from request_engine.modules.booking.application.commands.set_resource_location_schedule_exception import (  # noqa: E501
    SetResourceLocationScheduleExceptionCommand,
    set_resource_location_schedule_exception,
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


def _resource_revision(conn: PgConnection, scenario: F1ContextualScenario) -> int:
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


def _assignment_revision(conn: PgConnection, scenario: F1ContextualScenario) -> int:
    row = conn.execute(
        """
        SELECT revision
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND id = %s
        """,
        (scenario.organization_id, scenario.assignment_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _query(scenario: F1ContextualScenario) -> FindAppointmentSlotsQuery:
    return FindAppointmentSlotsQuery(
        organization_id=scenario.organization_id,
        offering_version_id=scenario.offering_version_id,
        location_id=scenario.location_id,
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
        limit=20,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_set_assignment_availability_is_authoritative_idempotent_and_revisioned(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresContextualSupplyLifecycleCommands(session_factory)
    initial_revision = _resource_revision(admin_conn, scenario)
    command = SetResourceLocationAvailabilityCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        assignment_id=scenario.assignment_id,
        windows=(
            ResourceLocationAvailabilityWindow(
                weekday=0,
                local_start=time(10),
                local_end=time(11),
                valid_from=date(2026, 1, 1),
            ),
        ),
        expected_resource_availability_revision=initial_revision,
        idempotency_key=f"availability-{uuid4().hex}",
    )

    state = await set_resource_location_availability(handler, command)
    replay = await set_resource_location_availability(handler, command)

    assert replay == state
    assert state.resource_availability_revision > initial_revision
    rows = admin_conn.execute(
        """
        SELECT weekday, local_start, local_end, valid_from, valid_until
        FROM request_engine.resource_location_availability
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
        ORDER BY weekday, local_start
        """,
        (scenario.organization_id, scenario.assignment_id),
    ).fetchall()
    assert rows == [(0, time(10), time(11), date(2026, 1, 1), None)]

    with pytest.raises(ResourceAvailabilityRevisionConflict):
        await set_resource_location_availability(
            handler,
            SetResourceLocationAvailabilityCommand(
                organization_id=scenario.organization_id,
                principal_id=scenario.principal_id,
                authority_party_id=scenario.authority_party_id,
                assignment_id=scenario.assignment_id,
                windows=command.windows,
                expected_resource_availability_revision=initial_revision,
                idempotency_key=f"availability-stale-{uuid4().hex}",
            ),
        )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_assignment_exception_can_be_created_changed_and_deactivated(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    handler = PostgresContextualSupplyLifecycleCommands(session_factory)
    revision = _resource_revision(admin_conn, scenario)
    created = await set_resource_location_schedule_exception(
        handler,
        SetResourceLocationScheduleExceptionCommand(
            organization_id=scenario.organization_id,
            principal_id=scenario.principal_id,
            authority_party_id=scenario.authority_party_id,
            assignment_id=scenario.assignment_id,
            start_at=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
            end_at=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
            exception_kind="unavailable",
            reason="doctor unavailable",
            active=True,
            expected_resource_availability_revision=revision,
            idempotency_key=f"exception-create-{uuid4().hex}",
        ),
    )
    assert created.resource_availability_revision > revision

    changed = await set_resource_location_schedule_exception(
        handler,
        SetResourceLocationScheduleExceptionCommand(
            organization_id=scenario.organization_id,
            principal_id=scenario.principal_id,
            authority_party_id=scenario.authority_party_id,
            assignment_id=scenario.assignment_id,
            exception_id=created.exception_id,
            start_at=datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
            end_at=datetime(2026, 8, 17, 14, 30, tzinfo=UTC),
            exception_kind="unavailable",
            reason="updated absence",
            active=False,
            expected_resource_availability_revision=created.resource_availability_revision,
            idempotency_key=f"exception-change-{uuid4().hex}",
        ),
    )
    assert changed.active is False
    assert changed.resource_availability_revision > created.resource_availability_revision

    stored = admin_conn.execute(
        """
        SELECT lower(during), upper(during), exception_kind, reason, active
        FROM request_engine.resource_location_schedule_exceptions
        WHERE organization_id = %s AND id = %s
        """,
        (scenario.organization_id, created.exception_id),
    ).fetchone()
    assert stored == (
        datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
        datetime(2026, 8, 17, 14, 30, tzinfo=UTC),
        "unavailable",
        "updated absence",
        False,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_retire_assignment_removes_contextual_supply_from_discovery(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    availability = PostgresAppointmentAvailabilityReader(session_factory)
    handler = PostgresContextualSupplyLifecycleCommands(session_factory)
    before = await find_appointment_slots(availability, _query(scenario))
    assert before

    retired = await retire_resource_location_assignment(
        handler,
        RetireResourceLocationAssignmentCommand(
            organization_id=scenario.organization_id,
            principal_id=scenario.principal_id,
            authority_party_id=scenario.authority_party_id,
            assignment_id=scenario.assignment_id,
            retired_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
            expected_assignment_revision=_assignment_revision(admin_conn, scenario),
            expected_resource_availability_revision=_resource_revision(admin_conn, scenario),
            idempotency_key=f"retire-{uuid4().hex}",
        ),
    )
    assert retired.resource_availability_revision > 0

    after = await find_appointment_slots(availability, _query(scenario))
    assert after == ()
