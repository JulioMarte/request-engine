from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.holds import CapacityHold


class SlotOfferCapacityUnavailable(Exception):
    """The concrete Opportunity no longer has reservable capacity."""


class SlotOfferCandidatePreferenceUnavailable(Exception):
    """Capacity exists, but not under the candidate's Resource preference."""


@dataclass(frozen=True, slots=True)
class AcquireSlotOfferHold:
    organization_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    preferred_resource_id: UUID | None
    start_at: datetime
    end_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ConsumeSlotOfferHold:
    organization_id: UUID
    hold_id: UUID


@dataclass(frozen=True, slots=True)
class ReleaseSlotOfferHold:
    organization_id: UUID
    hold_id: UUID
    terminal_status: Literal["released", "expired"]


class SlotOfferCapacityPort(Protocol):
    async def acquire_slot_offer_hold(
        self,
        transaction: object,
        request: AcquireSlotOfferHold,
    ) -> CapacityHold: ...

    async def consume_slot_offer_hold(
        self,
        transaction: object,
        request: ConsumeSlotOfferHold,
    ) -> Reservation: ...

    async def release_slot_offer_hold(
        self,
        transaction: object,
        request: ReleaseSlotOfferHold,
    ) -> CapacityHold: ...
