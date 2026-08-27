from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Mapping
from uuid import UUID

import pytest

from request_engine.modules.booking.contracts.recovery_schedule import (
    RecoveryAssignmentExtensionRequest,
    RecoveryAssignmentExtensionResult,
)
from request_engine.modules.live_capacity.contracts.projection import ProjectionState
from request_engine.modules.live_capacity.contracts.recovery import (
    RecoveryCapacityAssessment,
    RecoveryCapacityCheckpoint,
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
ORG, PRINCIPAL, AUTHORITY = UUID(int=1), UUID(int=2), UUID(int=3)
INCIDENT, QUEUE, RESOURCE = UUID(int=4), UUID(int=5), UUID(int=6)
LOCATION, ASSIGNMENT, ACTION, EXCEPTION = UUID(int=7), UUID(int=8), UUID(int=9), UUID(int=10)


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.incident = RecoveryIncident(
            id=INCIDENT, organization_id=ORG, service_queue_id=QUEUE,
            resource_id=RESOURCE, location_id=LOCATION, status=RecoveryIncidentStatus.OPEN,
            impact_kind=RecoveryImpactKind.CAPACITY_SHORTFALL, escalation_level=1,
            source_revision=3, source_fingerprint="source:v1", current_proposal_id=None,
            opened_at=NOW, last_assessed_at=NOW, resolved_at=None, revision=1,
        )
        self.action: RecoveryAction | None = None

    async def get_incident(self, *, organization_id: UUID, incident_id: UUID):
        return self.incident if organization_id == ORG and incident_id == INCIDENT else None

    async def get_open_incident(self, *, organization_id: UUID, service_queue_id: UUID):
        if organization_id == ORG and service_queue_id == QUEUE and self.incident.status is not RecoveryIncidentStatus.RESOLVED:
            return self.incident
        return None

    async def upsert_assessment(self, **kwargs: object):
        self.incident = replace(
            self.incident,
            status=(RecoveryIncidentStatus.RESOLVED if kwargs["resolve"] else RecoveryIncidentStatus.OPEN),
            impact_kind=kwargs["impact_kind"],
            escalation_level=kwargs["escalation_level"],
            source_revision=kwargs["source_revision"],
            source_fingerprint=kwargs["source_fingerprint"],
            resolved_at=NOW if kwargs["resolve"] else None,
            revision=self.incident.revision + 1,
        )
        return self.incident

    async def prepare_action(self, *, organization_id: UUID, incident_id: UUID, principal_id: UUID,
        action_kind: RecoveryActionKind, idempotency_key: str, command_fingerprint: str,
        expected_source_revision: int, payload: Mapping[str, object]):
        if self.action is not None:
            return self.action, False
        self.action = RecoveryAction(
            id=ACTION, organization_id=organization_id, incident_id=incident_id,
            action_kind=action_kind, status=RecoveryActionStatus.PREPARED,
            principal_id=principal_id, idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint, expected_source_revision=expected_source_revision,
            payload=payload, owner_steps={}, failure_code=None, created_at=NOW,
            started_at=None, completed_at=None,
        )
        return self.action, True

    async def transition_action(self, *, organization_id: UUID, action_id: UUID,
        status: RecoveryActionStatus, owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None):
        assert self.action is not None
        self.action = replace(
            self.action, status=status,
            owner_steps=self.action.owner_steps if owner_steps is None else owner_steps,
            failure_code=failure_code,
        )
        return self.action


class FakeSchedule:
    def __init__(self, *, fail_after_apply_once: bool = False) -> None:
        self.requests: list[RecoveryAssignmentExtensionRequest] = []
        self.fail_after_apply_once = fail_after_apply_once

    async def extend_assignment_hours(self, request: RecoveryAssignmentExtensionRequest):
        self.requests.append(request)
        result = RecoveryAssignmentExtensionResult(
            exception_id=EXCEPTION, assignment_id=request.assignment_id,
            start_at=request.start_at, end_at=request.end_at,
            resource_availability_revision=12,
        )
        if self.fail_after_apply_once:
            self.fail_after_apply_once = False
            raise TimeoutError("simulated timeout after Booking commit")
        return result


class FakeCapacity:
    async def assess_recovery_capacity(self, *, organization_id: UUID, service_queue_id: UUID):
        assert organization_id == ORG and service_queue_id == QUEUE
        return RecoveryCapacityAssessment(
            service_queue_id=QUEUE, resource_id=RESOURCE, location_id=LOCATION,
            observed_at=NOW, horizon_end=NOW + timedelta(hours=8),
            projection_state=ProjectionState.KNOWN, projection_reasons=(),
            executable_capacity_seconds=7200, committed_capacity_seconds=3600,
            scheduled_shortfall_seconds=0, live_shortfall_seconds=0, shortfall_seconds=0,
            source_fingerprint="source:v4", source_snapshot={},
            checkpoint=RecoveryCapacityCheckpoint(1, 12, 1, 4, ()),
            affected_commitments=(),
        )


def _command() -> ExtendRecoveryDayCommand:
    return ExtendRecoveryDayCommand(
        organization_id=ORG, principal_id=PRINCIPAL, authority_party_id=AUTHORITY,
        incident_id=INCIDENT, expected_source_revision=3, assignment_id=ASSIGNMENT,
        start_at=NOW + timedelta(hours=4), end_at=NOW + timedelta(hours=6),
        expected_resource_availability_revision=11, idempotency_key="extend-day-command",
        reason="recover same-day capacity",
    )


@pytest.mark.asyncio
async def test_extend_day_delegates_to_booking_reprojects_and_resolves() -> None:
    repository = FakeWorkflowRepository()
    schedule = FakeSchedule()
    action = await execute_extend_day_action(
        _command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
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
async def test_extend_day_retry_after_timeout_reuses_booking_idempotency_identity() -> None:
    repository = FakeWorkflowRepository()
    schedule = FakeSchedule(fail_after_apply_once=True)
    with pytest.raises(TimeoutError):
        await execute_extend_day_action(
            _command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
        )
    assert repository.action is not None
    assert repository.action.status is RecoveryActionStatus.RUNNING

    action = await execute_extend_day_action(
        _command(), repository=repository, schedule=schedule, capacity=FakeCapacity()
    )
    assert action.status is RecoveryActionStatus.SUCCEEDED
    assert len(schedule.requests) == 2
    assert schedule.requests[0].idempotency_key == schedule.requests[1].idempotency_key
