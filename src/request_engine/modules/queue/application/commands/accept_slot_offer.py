from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import AcceptedSlotOffer


@dataclass(frozen=True, slots=True)
class AcceptSlotOfferCommand:
    organization_id: UUID
    principal_id: UUID
    slot_offer_id: UUID
    expected_revision: int
    idempotency_key: str
    allow_subject_override: bool = False


class AcceptSlotOfferExecutor(Protocol):
    async def accept_slot_offer(self, command: AcceptSlotOfferCommand) -> AcceptedSlotOffer: ...


async def accept_slot_offer(
    executor: AcceptSlotOfferExecutor,
    command: AcceptSlotOfferCommand,
) -> AcceptedSlotOffer:
    if command.expected_revision <= 0:
        raise ValueError("expected_revision must be positive")
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await executor.accept_slot_offer(command)
