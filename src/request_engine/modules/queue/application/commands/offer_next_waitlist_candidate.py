from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.queue.contracts.waitlist import SlotOffer


@dataclass(frozen=True, slots=True)
class OfferNextWaitlistCandidateCommand:
    organization_id: UUID
    principal_id: UUID
    slot_opportunity_id: UUID
    offer_expires_at: datetime
    idempotency_key: str


class OfferNextWaitlistCandidateExecutor(Protocol):
    async def offer_next_waitlist_candidate(
        self,
        command: OfferNextWaitlistCandidateCommand,
    ) -> SlotOffer | None: ...


async def offer_next_waitlist_candidate(
    executor: OfferNextWaitlistCandidateExecutor,
    command: OfferNextWaitlistCandidateCommand,
) -> SlotOffer | None:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    return await executor.offer_next_waitlist_candidate(command)
