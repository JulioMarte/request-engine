from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RecoveryAssignmentExtensionRequest:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_resource_availability_revision: int
    idempotency_key: str
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryAssignmentExtensionResult:
    exception_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    resource_availability_revision: int


class RecoveryAssignmentSchedulePort(Protocol):
    async def extend_assignment_hours(
        self,
        request: RecoveryAssignmentExtensionRequest,
    ) -> RecoveryAssignmentExtensionResult: ...
