from dataclasses import replace
from typing import cast
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.operational_recovery.application import (
    workflow_replace_resource_action as replace_resource_action,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ReplaceResourceRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionKind,
    RecoveryActionStatus,
)

from .workflow_reschedule_test_support import (
    INCIDENT,
    NOW,
    ORG,
    PRINCIPAL,
    PROPOSAL,
    REQUIREMENT,
    RESERVATION,
    FakeBooking,
    FakeProposalRepository,
    proposal,
)
from .workflow_schedule_repository_support import FakeWorkflowRepository
from .workflow_schedule_test_support import FakeCapacity

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]

ALTERNATE_RESOURCE = UUID(int=99)


def replacement_proposal() -> RescheduleProposal:
    current = proposal()
    affected = current.affected[0]
    assert affected.target is not None
    replacement = replace(
        affected.target,
        start_at=affected.original_start_at,
        end_at=affected.original_end_at,
        resources=(ResourceChoice(REQUIREMENT, ALTERNATE_RESOURCE),),
    )
    return replace(
        current,
        affected=(replace(affected, replacement_target=replacement),),
    )


def command() -> ReplaceResourceRecoveryActionCommand:
    return ReplaceResourceRecoveryActionCommand(
        ORG,
        PRINCIPAL,
        INCIDENT,
        3,
        PROPOSAL,
        RESERVATION,
        "source:v3",
        "proposal:v3",
        "replace-resource-action-1",
        True,
    )


@pytest.mark.asyncio
async def test_replace_resource_uses_same_time_alternate_target_and_reprojects() -> None:
    workflow = FakeWorkflowRepository()
    proposals = FakeProposalRepository(replacement_proposal())
    booking = FakeBooking()
    action = await replace_resource_action.execute_replace_resource_action(
        command(),
        workflow_repository=workflow,
        proposal_repository=proposals.as_port(),
        booking=cast(RecoveryBookingPort, booking),
        capacity=FakeCapacity(),
    )
    request = booking.requests[0]
    assert action.action_kind is RecoveryActionKind.REPLACE_RESOURCE
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert request.start_at == NOW
    assert request.resources[0].resource_id == ALTERNATE_RESOURCE
    assert request.idempotency_key == f"recovery-action:{action.id}:booking-replace-resource:v1"
    assert action.owner_steps["reassessment"]["source_revision"] == 4  # type: ignore[index]


@pytest.mark.asyncio
async def test_replace_resource_retry_resumes_after_source_revision_advances() -> None:
    workflow = FakeWorkflowRepository()
    proposals = FakeProposalRepository(replacement_proposal())
    booking = FakeBooking(fail_once=True)
    with pytest.raises(TimeoutError):
        await replace_resource_action.execute_replace_resource_action(
            command(),
            workflow_repository=workflow,
            proposal_repository=proposals.as_port(),
            booking=cast(RecoveryBookingPort, booking),
            capacity=FakeCapacity(),
        )
    assert workflow.action is not None
    assert workflow.action.status is RecoveryActionStatus.RUNNING
    workflow.incident = replace(workflow.incident, source_revision=4, revision=2)
    action = await replace_resource_action.execute_replace_resource_action(
        command(),
        workflow_repository=workflow,
        proposal_repository=proposals.as_port(),
        booking=cast(RecoveryBookingPort, booking),
        capacity=FakeCapacity(),
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(booking.requests) == 2
    assert booking.requests[0].idempotency_key == booking.requests[1].idempotency_key
