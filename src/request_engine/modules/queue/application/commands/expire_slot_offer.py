from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import SlotOfferResolution


@dataclass(frozen=True, slots=True)
class ExpireSlotOfferCommand:
    organization_id: UUID
    principal_id: UUID
    slot_offer_id: UUID
    expected_revision: int
    idempotency_key: str


class ExpireSlotOfferExecutor(Protocol):
    async def expire_slot_offer(
        self,
        command: ExpireSlotOfferCommand,
    ) -> SlotOfferResolution: ...


async def expire_slot_offer(
    executor: ExpireSlotOfferExecutor,
    command: ExpireSlotOfferCommand,
) -> SlotOfferResolution:
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await executor.expire_slot_offer(command)
