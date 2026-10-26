"""Close (deactivate) or reopen one ServiceQueue as an explicit owner Command.

Closing is configuration, not intake control: it is refused while the queue
still holds waiting/called/serving entries (subjects physically waiting are never
silently cancelled), and it does not touch ``service_queue_intake_controls``.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SetServiceQueueActiveCommand:
    organization_id: UUID
    principal_id: UUID
    authority_party_id: UUID
    queue_id: UUID
    expected_revision: int
    active: bool
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ServiceQueueActivationState:
    queue_id: UUID
    queue_key: str
    display_name: str
    location_id: UUID | None
    offering_id: UUID | None
    active: bool
    revision: int


class SetServiceQueueActiveHandler(Protocol):
    async def set_service_queue_active(
        self, command: SetServiceQueueActiveCommand
    ) -> ServiceQueueActivationState: ...


async def set_service_queue_active(
    handler: SetServiceQueueActiveHandler,
    command: SetServiceQueueActiveCommand,
) -> ServiceQueueActivationState:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    return await handler.set_service_queue_active(command)
