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
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionRequest,
    RecoveryLocationExtensionResult,
)

NOW = datetime(2026, 8, 27, 14, 0, tzinfo=UTC)
ORG, PRINCIPAL, AUTHORITY = UUID(int=1), UUID(int=2), UUID(int=3)
INCIDENT, QUEUE, RESOURCE = UUID(int=4), UUID(int=5), UUID(int=6)
LOCATION, ASSIGNMENT, ACTION = UUID(int=7), UUID(int=8), UUID(int=9)
ASSIGNMENT_EXCEPTION, LOCATION_EXCEPTION = UUID(int=10), UUID(int=11)


class FakeLocationSchedule:
    def __init__(self) -> None:
        self.requests: list[RecoveryLocationExtensionRequest] = []

    async def extend_location_hours(
        self,
        request: RecoveryLocationExtensionRequest,
    ) -> RecoveryLocationExtensionResult:
        self.requests.append(request)
        return RecoveryLocationExtensionResult(
            LOCATION_EXCEPTION,
            LOCATION,
            request.start_at,
            request.end_at,
            2,
        )


class FakeSchedule:
    def __init__(self, fail_once: bool = False) -> None:
        self.requests: list[RecoveryAssignmentExtensionRequest] = []
        self.fail_once = fail_once

    async def extend_assignment_hours(
        self,
        request: RecoveryAssignmentExtensionRequest,
    ) -> RecoveryAssignmentExtensionResult:
        self.requests.append(request)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("simulated timeout after Booking commit")
        return RecoveryAssignmentExtensionResult(
            ASSIGNMENT_EXCEPTION,
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
    ) -> RecoveryCapacityAssessment:
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
            RecoveryCapacityCheckpoint(1, 12, 2, 4, ()),
            (),
        )


def command() -> ExtendRecoveryDayCommand:
    return ExtendRecoveryDayCommand(
        organization_id=ORG,
        principal_id=PRINCIPAL,
        authority_party_id=AUTHORITY,
        incident_id=INCIDENT,
        expected_source_revision=3,
        assignment_id=ASSIGNMENT,
        start_at=NOW + timedelta(hours=4),
        end_at=NOW + timedelta(hours=6),
        expected_location_operational_revision=1,
        expected_resource_availability_revision=11,
        idempotency_key="extend-day-command",
        reason="recover same-day capacity",
    )
