from dataclasses import replace
from typing import cast

import pytest

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.operational_recovery.application.workflow_reschedule_action import (
    execute_reschedule_action,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryActionStatus

from .workflow_reschedule_test_support import (
    FakeBooking,
    FakeProposalRepository,
    command,
    proposal,
)
from .workflow_schedule_repository_support import FakeWorkflowRepository
from .workflow_schedule_test_support import FakeCapacity

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]


@pytest.mark.asyncio
async def test_reschedule_uses_stable_booking_identity_and_reprojects() -> None:
    workflow = FakeWorkflowRepository()
    proposals = FakeProposalRepository(proposal())
    booking = FakeBooking()
    action = await execute_reschedule_action(
        command(),
        workflow_repository=workflow,
        proposal_repository=proposals.as_port(),
        booking=cast(RecoveryBookingPort, booking),
        capacity=FakeCapacity(),
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(booking.requests) == 1
    assert booking.requests[0].idempotency_key == (
        f"recovery-action:{action.id}:booking-reschedule:v1"
    )
    assert action.owner_steps["booking_reschedule"]["revision"] == 2  # type: ignore[index]
    assert action.owner_steps["reassessment"]["source_revision"] == 4  # type: ignore[index]


@pytest.mark.asyncio
async def test_reschedule_retry_replays_after_incident_truth_advances() -> None:
    workflow = FakeWorkflowRepository()
    proposals = FakeProposalRepository(proposal())
    booking = FakeBooking(fail_once=True)
    with pytest.raises(TimeoutError):
        await execute_reschedule_action(
            command(),
            workflow_repository=workflow,
            proposal_repository=proposals.as_port(),
            booking=cast(RecoveryBookingPort, booking),
            capacity=FakeCapacity(),
        )
    assert workflow.action is not None
    assert workflow.action.status is RecoveryActionStatus.RUNNING
    workflow.incident = replace(workflow.incident, source_revision=4, revision=2)

    action = await execute_reschedule_action(
        command(),
        workflow_repository=workflow,
        proposal_repository=proposals.as_port(),
        booking=cast(RecoveryBookingPort, booking),
        capacity=FakeCapacity(),
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(booking.requests) == 2
    assert booking.requests[0].idempotency_key == booking.requests[1].idempotency_key
