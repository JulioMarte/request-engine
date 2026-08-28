from dataclasses import replace

import pytest

from request_engine.modules.operational_recovery.application.workflow_commands import (
    SetRecoveryIntakeCommand,
)
from request_engine.modules.operational_recovery.application.workflow_intake_action import (
    execute_intake_action,
)
from request_engine.modules.operational_recovery.application.workflow_intake_port import (
    RecoveryIntakeControlRequest,
    RecoveryIntakeControlResult,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionStatus,
    RecoveryIncidentStale,
)

from .workflow_schedule_repository_support import FakeWorkflowRepository
from .workflow_schedule_test_support import INCIDENT, ORG, PRINCIPAL, QUEUE

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


class FakeIntake:
    def __init__(self) -> None:
        self.requests: list[RecoveryIntakeControlRequest] = []

    async def set_recovery_intake_control(
        self,
        request: RecoveryIntakeControlRequest,
    ) -> RecoveryIntakeControlResult:
        self.requests.append(request)
        return RecoveryIntakeControlResult(request.service_queue_id, 7, request.accepting)


def command(*, accepting: bool = False) -> SetRecoveryIntakeCommand:
    return SetRecoveryIntakeCommand(
        organization_id=ORG,
        principal_id=PRINCIPAL,
        incident_id=INCIDENT,
        expected_source_revision=3,
        accepting=accepting,
        idempotency_key="intake-action-1",
        reason="capacity recovery",
    )


@pytest.mark.asyncio
async def test_intake_action_delegates_to_owner_with_stable_identity() -> None:
    repository = FakeWorkflowRepository()
    intake = FakeIntake()
    action = await execute_intake_action(command(), repository=repository, queue_intake=intake)
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(intake.requests) == 1
    assert intake.requests[0].service_queue_id == QUEUE
    assert intake.requests[0].idempotency_key == f"recovery-action:{action.id}:queue-intake:v1"
    assert action.owner_steps["queue_intake"]["revision"] == 7  # type: ignore[index]


@pytest.mark.asyncio
async def test_intake_action_terminal_replay_does_not_call_owner_twice() -> None:
    repository = FakeWorkflowRepository()
    intake = FakeIntake()
    first = await execute_intake_action(command(), repository=repository, queue_intake=intake)
    replay = await execute_intake_action(command(), repository=repository, queue_intake=intake)
    assert replay.id == first.id
    assert len(intake.requests) == 1


@pytest.mark.asyncio
async def test_new_stale_intake_action_rejects_before_owner_mutation() -> None:
    repository = FakeWorkflowRepository()
    repository.incident = replace(repository.incident, source_revision=4, revision=2)
    intake = FakeIntake()
    with pytest.raises(RecoveryIncidentStale):
        await execute_intake_action(command(), repository=repository, queue_intake=intake)
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.REJECTED
    assert intake.requests == []
