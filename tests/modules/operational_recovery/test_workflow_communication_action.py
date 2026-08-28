from dataclasses import replace

import pytest

from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPurpose,
)
from request_engine.modules.operational_recovery.application.workflow_communication_action import (
    execute_communicate_impact_action,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionStatus,
    RecoveryIncidentStale,
)

from .workflow_communication_test_support import (
    EXPECTED_DEDUPE,
    RECIPIENT,
    TASK_ID,
    FakeCommunications,
    command,
)
from .workflow_schedule_repository_support import FakeWorkflowRepository
from .workflow_schedule_test_support import INCIDENT

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


@pytest.mark.asyncio
async def test_impact_communication_delegates_to_owner_with_stable_identity() -> None:
    repository = FakeWorkflowRepository()
    communications = FakeCommunications()
    action = await execute_communicate_impact_action(
        command(),
        repository=repository,
        communications=communications,
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(communications.requests) == 1
    request = communications.requests[0]
    assert request.recipient_party_id == RECIPIENT
    assert request.purpose is RecoveryCommunicationPurpose.IMPACT
    assert request.dedupe_key == EXPECTED_DEDUPE
    assert request.execution_id == INCIDENT
    assert request.idempotency_key == f"recovery-impact:{INCIDENT}:{RECIPIENT}:3:v1"
    assert request.render_context == {"message": "Running about 20 minutes behind."}
    owner_step = action.owner_steps["communications"]
    assert owner_step["communication_task_id"] == str(TASK_ID)  # type: ignore[index]


@pytest.mark.asyncio
async def test_impact_communication_terminal_replay_does_not_call_owner_twice() -> None:
    repository = FakeWorkflowRepository()
    communications = FakeCommunications()
    first = await execute_communicate_impact_action(
        command(),
        repository=repository,
        communications=communications,
    )
    replay = await execute_communicate_impact_action(
        command(),
        repository=repository,
        communications=communications,
    )
    assert replay.id == first.id
    assert len(communications.requests) == 1


@pytest.mark.asyncio
async def test_impact_communication_retry_reuses_owner_identity_after_response_loss() -> None:
    repository = FakeWorkflowRepository()
    communications = FakeCommunications(fail_once=True)
    with pytest.raises(TimeoutError):
        await execute_communicate_impact_action(
            command(),
            repository=repository,
            communications=communications,
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.RUNNING

    action = await execute_communicate_impact_action(
        command(),
        repository=repository,
        communications=communications,
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(communications.requests) == 2
    assert communications.requests[0].dedupe_key == communications.requests[1].dedupe_key
    assert communications.requests[0].idempotency_key == communications.requests[1].idempotency_key


@pytest.mark.asyncio
async def test_stale_impact_communication_rejects_before_owner_mutation() -> None:
    repository = FakeWorkflowRepository()
    repository.incident = replace(repository.incident, source_revision=4, revision=2)
    communications = FakeCommunications()
    with pytest.raises(RecoveryIncidentStale):
        await execute_communicate_impact_action(
            command(),
            repository=repository,
            communications=communications,
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.REJECTED
    assert communications.requests == []
