from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentExtensionRequest,
    RecoveryAssignmentExtensionResult,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ExtendRecoveryDayCommand,
)
from request_engine.modules.operational_recovery.application.workflow_schedule_action import (
    execute_extend_day_action,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryImpactKind,
    RecoveryIncident,
    RecoveryIncidentStatus,
)

pytestmark = [pytest.mark.unit, pytest.mark.invariant, pytest.mark.contract]

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)
ORG = UUID(int=1)
PRINCIPAL = UUID(int=2)
AUTHORITY = UUID(int=3)
INCIDENT = UUID(int=4)
QUEUE = UUID(int=5)
RESOURCE = UUID(int=6)
LOCATION = UUID(int=7)
ASSIGNMENT = UUID(int=8)
ACTION = UUID(int=9)
EXCEPTION = UUID(int=10)


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.incident = RecoveryIncident(
            id=INCIDENT,
            organization_id=ORG,
            service_queue_id=QUEUE,
            resource_id=RESOURCE,
            location_id=LOCATION,
            status=RecoveryIncidentStatus.OPEN,
            impact_kind=RecoveryImpactKind.CAPACITY_SHORTFALL,
            escalation_level=1,
            source_revision=3,
            source_fingerprint="source:v1",
            current_proposal_id=None,
            opened_at=NOW,
            last_assessed_at=NOW,
            resolved_at=None,
            revision=1,
        )
        self.action: RecoveryAction | None = None

    async def get_incident(self, *, organization_id: UUID, incident_id: UUID):
        assert organization_id == ORG
        return self.incident if incident_id == INCIDENT else None

    async def prepare_action(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        principal_id: UUID,
        action_kind: RecoveryActionKind,
        idempotency_key: str,
        command_fingerprint: str,
        expected_source_revision: int,
        payload: Mapping[str, object],
    ):
        if self.action is not None:
            return self.action, False
        self.action = RecoveryAction(
            id=ACTION,
            organization_id=organization_id,
            incident_id=incident_id,
            action_kind=action_kind,
            status=RecoveryActionStatus.PREPARED,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
            expected_source_revision=expected_source_revision,
            payload=payload,
            owner_steps={},
            failure_code=None,
            created_at=NOW,
            started_at=None,
            completed_at=None,
        )
        return self.action, True

    async def transition_action(
        self,
        *,
        organization_id: UUID,
        action_id: UUID,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
    ):
        assert self.action is not None
        assert organization_id == ORG
        assert action_id == ACTION
        self.action = replace(
            self.action,
            status=status,
            owner_steps=self.action.owner_steps if owner_steps is None else owner_steps,
            failure_code=failure_code,
            started_at=NOW if status is RecoveryActionStatus.RUNNING else self.action.started_at,
            completed_at=(
                NOW if status in {RecoveryActionStatus.SUCCEEDED, RecoveryActionStatus.REJECTED}
                else self.action.completed_at
            ),
        )
        return self.action


class FakeSchedule:
    def __init__(self, *, fail_after_apply_once: bool = False) -> None:
        self.requests: list[RecoveryAssignmentExtensionRequest] = []
        self.fail_after_apply_once = fail_after_apply_once

    async def extend_assignment_hours(self, request: RecoveryAssignmentExtensionRequest):
        self.requests.append(request)
        result = RecoveryAssignmentExtensionResult(
            exception_id=EXCEPTION,
            assignment_id=request.assignment_id,
            start_at=request.start_at,
            end_at=request.end_at,
            resource_availability_revision=12,
        )
        if self.fail_after_apply_once:
            self.fail_after_apply_once = False
            raise TimeoutError("simulated timeout after Booking commit")
        return result


def _command() -> ExtendRecoveryDayCommand:
    return ExtendRecoveryDayCommand(
        organization_id=ORG,
        principal_id=PRINCIPAL,
        authority_party_id=AUTHORITY,
        incident_id=INCIDENT,
        expected_source_revision=3,
        assignment_id=ASSIGNMENT,
        start_at=NOW + timedelta(hours=4),
        end_at=NOW + timedelta(hours=6),
        expected_resource_availability_revision=11,
        idempotency_key="extend-day-command",
        reason="recover same-day capacity",
    )


@pytest.mark.asyncio
async def test_extend_day_delegates_to_booking_and_records_authoritative_result() -> None:
    repository = FakeWorkflowRepository()
    schedule = FakeSchedule()

    action = await execute_extend_day_action(
        _command(),
        repository=repository,
        schedule=schedule,
    )

    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert action.action_kind is RecoveryActionKind.EXTEND_DAY
    assert len(schedule.requests) == 1
    request = schedule.requests[0]
    assert request.assignment_id == ASSIGNMENT
    assert request.expected_resource_availability_revision == 11
    assert request.idempotency_key == f"recovery-action:{ACTION}:extend-day:v1"
    assert action.owner_steps["booking_schedule"]["exception_id"] == str(EXCEPTION)
    assert action.owner_steps["booking_schedule"]["resource_availability_revision"] == 12


@pytest.mark.asyncio
async def test_extend_day_retry_after_timeout_reuses_booking_idempotency_identity() -> None:
    repository = FakeWorkflowRepository()
    schedule = FakeSchedule(fail_after_apply_once=True)

    with pytest.raises(TimeoutError):
        await execute_extend_day_action(
            _command(),
            repository=repository,
            schedule=schedule,
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.RUNNING

    action = await execute_extend_day_action(
        _command(),
        repository=repository,
        schedule=schedule,
    )

    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(schedule.requests) == 2
    assert schedule.requests[0].idempotency_key == schedule.requests[1].idempotency_key
