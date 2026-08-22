from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetiredResourceLocationAssignmentState:
    assignment_id: UUID
    retired_at: datetime
    assignment_revision: int
    resource_availability_revision: int


@dataclass(frozen=True, slots=True)
class RetireResourceLocationAssignmentCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    assignment_id: UUID
    retired_at: datetime
    expected_assignment_revision: int
    expected_resource_availability_revision: int
    idempotency_key: str


class RetireResourceLocationAssignmentHandler(Protocol):
    async def retire_resource_location_assignment(
        self, command: RetireResourceLocationAssignmentCommand
    ) -> RetiredResourceLocationAssignmentState: ...


async def retire_resource_location_assignment(
    handler: RetireResourceLocationAssignmentHandler,
    command: RetireResourceLocationAssignmentCommand,
) -> RetiredResourceLocationAssignmentState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_assignment_revision <= 0:
        raise ValueError("expected_assignment_revision must be positive")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    return await handler.retire_resource_location_assignment(command)
