from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResourceLocationAssignmentState:
    assignment_id: UUID
    resource_id: UUID
    location_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    assignment_revision: int
    resource_availability_revision: int


@dataclass(frozen=True, slots=True)
class AssignResourceToLocationCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    resource_id: UUID
    location_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    expected_resource_availability_revision: int
    idempotency_key: str


class AssignResourceToLocationHandler(Protocol):
    async def assign_resource_to_location(
        self,
        command: AssignResourceToLocationCommand,
    ) -> ResourceLocationAssignmentState: ...


async def assign_resource_to_location(
    handler: AssignResourceToLocationHandler,
    command: AssignResourceToLocationCommand,
) -> ResourceLocationAssignmentState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_resource_availability_revision <= 0:
        raise ValueError("expected_resource_availability_revision must be positive")
    return await handler.assign_resource_to_location(command)
