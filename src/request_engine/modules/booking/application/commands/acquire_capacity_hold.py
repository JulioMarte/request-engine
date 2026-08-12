from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.booking.contracts.holds import CapacityHold


@dataclass(frozen=True, slots=True)
class AcquireCapacityHoldCommand:
    organization_id: UUID
    principal_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    start_at: datetime
    expires_at: datetime
    resources: tuple[ResourceChoice, ...]
    idempotency_key: str
    location_id: UUID | None = None


class AcquireCapacityHoldHandler(Protocol):
    async def acquire_capacity_hold(self, command: AcquireCapacityHoldCommand) -> CapacityHold: ...


async def acquire_capacity_hold(
    handler: AcquireCapacityHoldHandler,
    command: AcquireCapacityHoldCommand,
) -> CapacityHold:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if not command.resources:
        raise ValueError("at least one ResourceChoice is required")
    return await handler.acquire_capacity_hold(command)
