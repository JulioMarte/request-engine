from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

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
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryImpactKind,
    RecoveryIncident,
    RecoveryIncidentStatus,
)

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)
ORG, PRINCIPAL, AUTHORITY = UUID(int=1), UUID(int=2), UUID(int=3)
INCIDENT, QUEUE, RESOURCE = UUID(int=4), UUID(int=5), UUID(int=6)
LOCATION, ASSIGNMENT, ACTION, EXCEPTION = UUID(int=7), UUID(int=8), UUID(int=9), UUID(int=10)


class FakeWorkflowRepository:
    def __init__(self) -> None:
        self.incident = RecoveryIncident(
            INCIDENT,
            ORG,
            QUEUE,
            RESOURCE,
            LOCATION,
            RecoveryIncidentStatus.OPEN,
            RecoveryImpactKind.CAPACITY_SHORTFALL,
            1,
            3,
            "source:v1",
            None,
            NOW,
            NOW,
            None,
            1,
        )
        self.action: RecoveryAction | None = None

    async def get_incident(self, *, organization_id: UUID, incident_id: UUID):
        return self.incident if organization_id == ORG and incident_id == INCIDENT else None

    async def get_open_incident(self, *, organization_id: UUID, service_queue_id: UUID):
        return self.incident if organization_id == ORG and service_queue_id == QUEUE else None

    async def upsert_assessment(self, **kwargs: object):
        status = (
            RecoveryIncidentStatus.RESOLVED
            if kwargs["resolve"]
            else RecoveryIncidentStatus.OPEN
        )
        self.incident = replace(
            self.incident,
            status=status,
            source_revision=kwargs["source_revision"],
            source_fingerprint=kwargs["source_fingerprint"],
            revision=self.incident.revision + 1,
        )
        return self.incident

    async def prepare_action(self, **kwargs: object):
        if self.action is not None:
            return self.action, False
        self.action = RecoveryAction(
            ACTION,
            ORG,
            INCIDENT,
            kwargs["action_kind"],
            RecoveryActionStatus.PREPARED,
            PRINCIPAL,
            kwargs["idempotency_key"],
            kwargs["command_fingerprint"],
            kwargs["expected_source_revision"],
            kwargs["payload"],
            {},
            None,
            NOW,
            None,
            None,
        )
        return self.action, True

    async def transition_action(
        self,
        *,
        status: RecoveryActionStatus,
        owner_steps: Mapping[str, object] | None = None,
        failure_code: str | None = None,
        **_: object,
    ):
        assert self.action is not None
        self.action = replace(
            self.action,
            status=status,
            owner_steps=self.action.owner_steps if owner_steps is None else owner_steps,
            failure_code=failure_code,
        )
        return self.action


class FakeSchedule:
    def __init__(self, fail_once: bool = False) -> None:
        self.requests: list[RecoveryAssignmentExtensionRequest] = []
        self.fail_once = fail_once

    async def extend_assignment_hours(self, request: RecoveryAssignmentExtensionRequest):
        self.requests.append(request)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("simulated timeout after Booking commit")
        return RecoveryAssignmentExtensionResult(
            EXCEPTION,
            ASSIGNMENT,
            request.start_at,
            request.end_at,
            12,
        )


class FakeCapacity:
    async def assess_recovery_capacity(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ):
        return RecoveryCapacityAssessment(
            QUEUE,
            RESOURCE,
            LOCATION,
            NOW,
            NOW + timedelta(hours=8),
            ProjectionState.KNOWN,
            (),
            7200,
            3600,
            0,
            0,
            0,
            "source:v4",
            {},
            RecoveryCapacityCheckpoint(1, 12, 1, 4, ()),
            (),
        )


def command() -> ExtendRecoveryDayCommand:
    return ExtendRecoveryDayCommand(
        ORG,
        PRINCIPAL,
        AUTHORITY,
        INCIDENT,
        3,
        ASSIGNMENT,
        NOW + timedelta(hours=4),
        NOW + timedelta(hours=6),
        11,
        "extend-day-command",
        "recover same-day capacity",
    )
