from dataclasses import replace

import pytest

from request_engine.modules.operational_recovery.application.workflow_schedule_action import (
    execute_extend_day_action,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionStatus,
    RecoveryIncidentStale,
    RecoveryIncidentStatus,
)

from .workflow_schedule_repository_support import FakeWorkflowRepository
from .workflow_schedule_test_support import (
    ACTION,
    ASSIGNMENT_EXCEPTION,
    LOCATION_EXCEPTION,
    FakeCapacity,
    FakeLocationSchedule,
    FakeSchedule,
    command,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


@pytest.mark.asyncio
async def test_extend_day_runs_both_owners_reprojects_and_resolves() -> None:
    repository = FakeWorkflowRepository()
    location = FakeLocationSchedule()
    schedule = FakeSchedule()
    action = await execute_extend_day_action(
        command(),
        repository=repository,
        location_schedule=location,
        assignment_schedule=schedule,
        capacity=FakeCapacity(),
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert repository.incident.status is RecoveryIncidentStatus.RESOLVED
    assert location.requests[0].idempotency_key == f"recovery-action:{ACTION}:location-hours:v1"
    assert schedule.requests[0].idempotency_key == f"recovery-action:{ACTION}:assignment-hours:v1"
    assert action.owner_steps["catalog_location"]["exception_id"] == str(  # type: ignore[index]
        LOCATION_EXCEPTION
    )
    assert action.owner_steps["booking_schedule"]["exception_id"] == str(  # type: ignore[index]
        ASSIGNMENT_EXCEPTION
    )


@pytest.mark.asyncio
async def test_extend_day_retry_preserves_partial_owner_step_and_identity() -> None:
    repository = FakeWorkflowRepository()
    location = FakeLocationSchedule()
    schedule = FakeSchedule(fail_once=True)
    with pytest.raises(TimeoutError):
        await execute_extend_day_action(
            command(),
            repository=repository,
            location_schedule=location,
            assignment_schedule=schedule,
            capacity=FakeCapacity(),
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.RUNNING
    assert "catalog_location" in repository.action.owner_steps
    repository.incident = replace(repository.incident, source_revision=4, revision=2)

    action = await execute_extend_day_action(
        command(),
        repository=repository,
        location_schedule=location,
        assignment_schedule=schedule,
        capacity=FakeCapacity(),
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert location.requests[0].idempotency_key == location.requests[1].idempotency_key
    assert schedule.requests[0].idempotency_key == schedule.requests[1].idempotency_key


@pytest.mark.asyncio
async def test_extend_day_new_stale_authorization_rejects_before_owner_mutation() -> None:
    repository = FakeWorkflowRepository()
    repository.incident = replace(repository.incident, source_revision=4, revision=2)
    location = FakeLocationSchedule()
    schedule = FakeSchedule()
    with pytest.raises(RecoveryIncidentStale):
        await execute_extend_day_action(
            command(),
            repository=repository,
            location_schedule=location,
            assignment_schedule=schedule,
            capacity=FakeCapacity(),
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.REJECTED
    assert location.requests == []
    assert schedule.requests == []
