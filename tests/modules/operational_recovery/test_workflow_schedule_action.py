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
    EXCEPTION,
    FakeCapacity,
    FakeSchedule,
    command,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


@pytest.mark.asyncio
async def test_extend_day_delegates_to_booking_reprojects_and_resolves() -> None:
    repository = FakeWorkflowRepository()
    schedule = FakeSchedule()
    action = await execute_extend_day_action(
        command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert repository.incident.status is RecoveryIncidentStatus.RESOLVED
    assert len(schedule.requests) == 1
    assert schedule.requests[0].idempotency_key == f"recovery-action:{ACTION}:extend-day:v1"
    booking_step = action.owner_steps["booking_schedule"]
    assert isinstance(booking_step, dict)
    assert booking_step["exception_id"] == str(EXCEPTION)
    reassessment = action.owner_steps["reassessment"]
    assert isinstance(reassessment, dict)
    assert reassessment["source_revision"] == 4
    assert reassessment["incident_status"] == "resolved"


@pytest.mark.asyncio
async def test_extend_day_retry_resumes_running_action_after_source_advances() -> None:
    repository = FakeWorkflowRepository()
    schedule = FakeSchedule(fail_once=True)
    with pytest.raises(TimeoutError):
        await execute_extend_day_action(
            command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.RUNNING
    repository.incident = replace(repository.incident, source_revision=4, revision=2)

    action = await execute_extend_day_action(
        command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(schedule.requests) == 2
    assert schedule.requests[0].idempotency_key == schedule.requests[1].idempotency_key


@pytest.mark.asyncio
async def test_extend_day_new_stale_authorization_is_rejected_before_owner_mutation() -> None:
    repository = FakeWorkflowRepository()
    repository.incident = replace(repository.incident, source_revision=4, revision=2)
    schedule = FakeSchedule()

    with pytest.raises(RecoveryIncidentStale):
        await execute_extend_day_action(
            command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
        )

    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.REJECTED
    assert repository.action.failure_code == "STALE_RECOVERY_INCIDENT"
    assert schedule.requests == []
