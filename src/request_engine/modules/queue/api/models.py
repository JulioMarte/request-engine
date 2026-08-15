from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.queue.application.queries.list_service_queues import ServiceQueueSummary
from request_engine.modules.queue.contracts.service_queue import QueueEntry, QueueStatus
from request_engine.modules.queue.contracts.waitlist import (
    AcceptedSlotOffer,
    SlotOffer,
    WaitlistEntry,
)


class ServiceQueueView(BaseModel):
    id: UUID
    queue_key: str
    display_name: str
    location_id: UUID | None
    offering_id: UUID | None
    active: bool

    @classmethod
    def from_contract(cls, queue: ServiceQueueSummary) -> "ServiceQueueView":
        return cls(
            id=queue.id,
            queue_key=queue.queue_key,
            display_name=queue.display_name,
            location_id=queue.location_id,
            offering_id=queue.offering_id,
            active=queue.active,
        )


class QueueEntryView(BaseModel):
    id: UUID
    queue_id: UUID
    subject_party_id: UUID
    status: str
    admitted_at: datetime
    called_at: datetime | None
    revision: int

    @classmethod
    def from_contract(cls, entry: QueueEntry) -> "QueueEntryView":
        return cls(
            id=entry.id,
            queue_id=entry.queue_id,
            subject_party_id=entry.subject_party_id,
            status=entry.status.value,
            admitted_at=entry.admitted_at,
            called_at=entry.called_at,
            revision=entry.revision,
        )


class QueueStatusView(BaseModel):
    queue_id: UUID
    queue_key: str
    display_name: str
    entry: QueueEntryView | None
    entries_ahead: int | None

    @classmethod
    def from_contract(cls, queue_status: QueueStatus) -> "QueueStatusView":
        return cls(
            queue_id=queue_status.queue_id,
            queue_key=queue_status.queue_key,
            display_name=queue_status.display_name,
            entry=(
                QueueEntryView.from_contract(queue_status.entry)
                if queue_status.entry is not None
                else None
            ),
            entries_ahead=queue_status.entries_ahead,
        )


class JoinQueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_party_id: UUID
    reservation_id: UUID | None = None
    offering_id: UUID | None = None


class LeaveQueueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class JoinWaitlistBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offering_id: UUID
    subject_party_id: UUID
    location_id: UUID | None = None
    preferred_resource_id: UUID | None = None
    earliest_start: datetime | None = None
    latest_start: datetime | None = None


class LeaveWaitlistBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class WaitlistEntryView(BaseModel):
    id: UUID
    offering_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    preferred_resource_id: UUID | None
    earliest_start: datetime | None
    latest_start: datetime | None
    status: str
    revision: int
    created_at: datetime

    @classmethod
    def from_contract(cls, entry: WaitlistEntry) -> "WaitlistEntryView":
        return cls(
            id=entry.id,
            offering_id=entry.offering_id,
            subject_party_id=entry.subject_party_id,
            location_id=entry.location_id,
            preferred_resource_id=entry.preferred_resource_id,
            earliest_start=entry.earliest_start,
            latest_start=entry.latest_start,
            status=entry.status.value,
            revision=entry.revision,
            created_at=entry.created_at,
        )


class ResolveSlotOfferBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)


class SlotOfferView(BaseModel):
    """Public offer state. CapacityHold and next-candidate identities stay private."""

    id: UUID
    waitlist_entry_id: UUID
    expires_at: datetime
    status: str
    revision: int

    @classmethod
    def from_contract(cls, offer: SlotOffer) -> "SlotOfferView":
        return cls(
            id=offer.id,
            waitlist_entry_id=offer.waitlist_entry_id,
            expires_at=offer.expires_at,
            status=offer.status.value,
            revision=offer.revision,
        )


class AcceptedSlotOfferView(BaseModel):
    offer: SlotOfferView
    reservation_id: UUID
    reservation_revision: int

    @classmethod
    def from_contract(cls, accepted: AcceptedSlotOffer) -> "AcceptedSlotOfferView":
        return cls(
            offer=SlotOfferView.from_contract(accepted.offer),
            reservation_id=accepted.reservation.id,
            reservation_revision=accepted.reservation.revision,
        )
