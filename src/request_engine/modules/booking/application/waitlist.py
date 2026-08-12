from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.waitlist import (
    AcceptedSlotOffer,
    SlotOffer,
    SlotOpportunity,
    WaitlistEntry,
)


@dataclass(frozen=True, slots=True)
class JoinWaitlistCommand:
    organization_id: UUID
    principal_id: UUID
    offering_id: UUID
    subject_party_id: UUID
    idempotency_key: str
    location_id: UUID | None = None
    preferred_resource_id: UUID | None = None
    earliest_start: datetime | None = None
    latest_start: datetime | None = None


@dataclass(frozen=True, slots=True)
class LeaveWaitlistCommand:
    organization_id: UUID
    principal_id: UUID
    waitlist_entry_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CreateSlotOpportunityCommand:
    organization_id: UUID
    principal_id: UUID
    source_event_id: UUID
    source_reservation_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OfferNextWaitlistCandidateCommand:
    organization_id: UUID
    principal_id: UUID
    slot_opportunity_id: UUID
    expires_at: datetime
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class AcceptSlotOfferCommand:
    organization_id: UUID
    principal_id: UUID
    slot_offer_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class DeclineSlotOfferCommand:
    organization_id: UUID
    principal_id: UUID
    slot_offer_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class ExpireSlotOfferCommand:
    organization_id: UUID
    principal_id: UUID
    slot_offer_id: UUID
    idempotency_key: str


class WaitlistCommands(Protocol):
    async def join_waitlist(self, command: JoinWaitlistCommand) -> WaitlistEntry: ...

    async def leave_waitlist(self, command: LeaveWaitlistCommand) -> WaitlistEntry: ...

    async def create_slot_opportunity(
        self, command: CreateSlotOpportunityCommand
    ) -> SlotOpportunity: ...

    async def offer_next_waitlist_candidate(
        self, command: OfferNextWaitlistCandidateCommand
    ) -> SlotOffer: ...

    async def accept_slot_offer(self, command: AcceptSlotOfferCommand) -> AcceptedSlotOffer: ...

    async def decline_slot_offer(self, command: DeclineSlotOfferCommand) -> SlotOffer: ...

    async def expire_slot_offer(self, command: ExpireSlotOfferCommand) -> SlotOffer: ...


class WaitlistReader(Protocol):
    async def get_waitlist_entry(
        self, *, organization_id: UUID, waitlist_entry_id: UUID
    ) -> WaitlistEntry | None: ...

    async def get_slot_offer(
        self, *, organization_id: UUID, slot_offer_id: UUID
    ) -> SlotOffer | None: ...


async def join_waitlist(handler: WaitlistCommands, command: JoinWaitlistCommand) -> WaitlistEntry:
    _require_idempotency(command.idempotency_key)
    if (
        command.earliest_start is not None
        and command.latest_start is not None
        and command.latest_start < command.earliest_start
    ):
        raise ValueError("latest_start must be >= earliest_start")
    return await handler.join_waitlist(command)


async def leave_waitlist(handler: WaitlistCommands, command: LeaveWaitlistCommand) -> WaitlistEntry:
    _require_idempotency(command.idempotency_key)
    return await handler.leave_waitlist(command)


async def create_slot_opportunity(
    handler: WaitlistCommands, command: CreateSlotOpportunityCommand
) -> SlotOpportunity:
    _require_idempotency(command.idempotency_key)
    return await handler.create_slot_opportunity(command)


async def offer_next_waitlist_candidate(
    handler: WaitlistCommands, command: OfferNextWaitlistCandidateCommand
) -> SlotOffer:
    _require_idempotency(command.idempotency_key)
    return await handler.offer_next_waitlist_candidate(command)


async def accept_slot_offer(
    handler: WaitlistCommands, command: AcceptSlotOfferCommand
) -> AcceptedSlotOffer:
    _require_idempotency(command.idempotency_key)
    return await handler.accept_slot_offer(command)


async def decline_slot_offer(
    handler: WaitlistCommands, command: DeclineSlotOfferCommand
) -> SlotOffer:
    _require_idempotency(command.idempotency_key)
    return await handler.decline_slot_offer(command)


async def expire_slot_offer(
    handler: WaitlistCommands, command: ExpireSlotOfferCommand
) -> SlotOffer:
    _require_idempotency(command.idempotency_key)
    return await handler.expire_slot_offer(command)


async def get_waitlist_entry(
    reader: WaitlistReader, *, organization_id: UUID, waitlist_entry_id: UUID
) -> WaitlistEntry | None:
    return await reader.get_waitlist_entry(
        organization_id=organization_id,
        waitlist_entry_id=waitlist_entry_id,
    )


def _require_idempotency(key: str) -> None:
    if not key:
        raise ValueError("idempotency_key is required")
