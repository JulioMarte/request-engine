from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import SlotOpportunity


@dataclass(frozen=True, slots=True)
class CreateSlotOpportunityCommand:
    organization_id: UUID
    principal_id: UUID
    offering_version_id: UUID
    source_event_id: UUID
    start_at: datetime
    end_at: datetime
    idempotency_key: str
    location_id: UUID | None = None
    source_reservation_id: UUID | None = None


class CreateSlotOpportunityExecutor(Protocol):
    async def create_slot_opportunity(
        self,
        command: CreateSlotOpportunityCommand,
    ) -> SlotOpportunity: ...


async def create_slot_opportunity(
    executor: CreateSlotOpportunityExecutor,
    command: CreateSlotOpportunityCommand,
) -> SlotOpportunity:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    if command.end_at <= command.start_at:
        raise ValueError("end_at must be after start_at")
    return await executor.create_slot_opportunity(command)
