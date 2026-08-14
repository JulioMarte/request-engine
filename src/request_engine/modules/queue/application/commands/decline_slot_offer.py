from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import SlotOfferResolution


@dataclass(frozen=True, slots=True)
class DeclineSlotOfferCommand:
    organization_id: UUID
    principal_id: UUID
    slot_offer_id: UUID
    expected_revision: int
    idempotency_key: str
    allow_subject_override: bool = False


class DeclineSlotOfferExecutor(Protocol):
    async def decline_slot_offer(
        self,
        command: DeclineSlotOfferCommand,
    ) -> SlotOfferResolution: ...


async def decline_slot_offer(
    executor: DeclineSlotOfferExecutor,
    command: DeclineSlotOfferCommand,
) -> SlotOfferResolution:
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await executor.decline_slot_offer(command)
