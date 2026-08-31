from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


class OperationalAssignmentRevisionConflict(RuntimeError):
    def __init__(self, assignment_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Operational assignment {assignment_id} availability revision conflict: "
            f"expected {expected}, current {actual}"
        )
        self.assignment_id = assignment_id
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True, slots=True)
class OperationalAssignmentExtensionRequest:
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
class OperationalAssignmentExtensionResult:
    exception_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    resource_availability_revision: int


class OperationalAssignmentSchedulePort(Protocol):
    async def extend_assignment_hours(
        self,
        request: OperationalAssignmentExtensionRequest,
    ) -> OperationalAssignmentExtensionResult: ...
