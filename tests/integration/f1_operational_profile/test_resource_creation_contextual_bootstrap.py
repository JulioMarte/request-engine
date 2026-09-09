from typing import Any
from uuid import uuid4

import pytest
from psycopg import Connection

from request_engine.modules.booking.adapters.db.resource_creation_commands import (
    PostgresResourceCreationCommands,
)
from request_engine.modules.booking.application.commands.create_resource import (
    CreateResourceCommand,
    create_resource,
)
from request_engine.platform.db.session import SessionFactory

from .dummy_data import create_contextual_cardiology_scenario

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_create_resource_without_schedule_still_creates_location_assignment(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    scenario = create_contextual_cardiology_scenario(admin_conn)
    command = CreateResourceCommand(
        organization_id=scenario.organization_id,
        principal_id=scenario.principal_id,
        authority_party_id=scenario.authority_party_id,
        location_id=scenario.location_id,
        resource_key=f"unscheduled-{uuid4().hex}",
        display_name="Unscheduled Resource",
        capacity_model="exclusive",
        capacity_units=1,
        capability_ids=(),
        idempotency_key=f"create-resource-{uuid4().hex}",
        weekly_availability=(),
    )

    state = await create_resource(PostgresResourceCreationCommands(session_factory), command)

    assert state.resource_location_assignment_id is not None
    assert state.weekly_availability == ()
    assignment = admin_conn.execute(
        """
        SELECT location_id, lower(effective_during), upper(effective_during)
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s AND resource_id = %s
        """,
        (scenario.organization_id, state.resource_id),
    ).fetchall()
    assert len(assignment) == 1
    assert assignment[0][0] == scenario.location_id
    assert assignment[0][1] is not None
    assert assignment[0][2] is None
    availability_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.resource_location_availability
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
        """,
        (scenario.organization_id, state.resource_location_assignment_id),
    ).fetchone()
    assert availability_count == (0,)
