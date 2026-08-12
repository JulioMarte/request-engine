from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    Reservation,
    ResourceChoice,
)
from request_engine.modules.catalog.application.queries.get_business_info import BusinessInfo
from request_engine.modules.catalog.application.queries.search_offerings import OfferingSummary
from request_engine.modules.queue.application.queries.list_service_queues import ServiceQueueSummary
from request_engine.modules.queue.contracts.service_queue import QueueEntry, QueueStatus


class BusinessLocationView(BaseModel):
    id: UUID
    location_key: str
    display_name: str
    timezone: str
    public_data: dict[str, object]


class BusinessInfoView(BaseModel):
    organization_id: UUID
    organization_key: str
    display_name: str
    public_profile: dict[str, object]
    locations: tuple[BusinessLocationView, ...]

    @classmethod
    def from_contract(cls, info: BusinessInfo) -> "BusinessInfoView":
        return cls(
            organization_id=info.organization_id,
            organization_key=info.organization_key,
            display_name=info.display_name,
            public_profile=info.public_profile,
            locations=tuple(
                BusinessLocationView(
                    id=item.id,
                    location_key=item.location_key,
                    display_name=item.display_name,
                    timezone=item.timezone,
                    public_data=item.public_data,
                )
                for item in info.locations
            ),
        )


class OfferingVersionView(BaseModel):
    id: UUID
    version: int
    duration_minutes: int | None
    bookable: bool
    requestable: bool
    public_data: dict[str, object]


class OfferingView(BaseModel):
    id: UUID
    offering_key: str
    display_name: str
    description: str | None
    latest_version: OfferingVersionView

    @classmethod
    def from_contract(cls, offering: OfferingSummary) -> "OfferingView":
        version = offering.latest_version
        return cls(
            id=offering.id,
            offering_key=offering.offering_key,
            display_name=offering.display_name,
            description=offering.description,
            latest_version=OfferingVersionView(
                id=version.id,
                version=version.version,
                duration_minutes=version.duration_minutes,
                bookable=version.bookable,
                requestable=version.requestable,
                public_data=version.public_data,
            ),
        )


class ResourceChoiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: UUID
    resource_id: UUID

    def to_contract(self) -> ResourceChoice:
        return ResourceChoice(requirement_id=self.requirement_id, resource_id=self.resource_id)


class AppointmentSlotView(BaseModel):
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoiceModel, ...]

    @classmethod
    def from_contract(cls, slot: AppointmentSlot) -> "AppointmentSlotView":
        return cls(
            offering_version_id=slot.offering_version_id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            location_id=slot.location_id,
            resources=tuple(
                ResourceChoiceModel(
                    requirement_id=item.requirement_id,
                    resource_id=item.resource_id,
                )
                for item in slot.resources
            ),
        )


class BookAppointmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_version_id: UUID
    subject_party_id: UUID
    start_at: datetime
    resources: tuple[ResourceChoiceModel, ...] = Field(min_length=1, max_length=20)
    location_id: UUID | None = None
    origin_request_id: UUID | None = None


class CancelReservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=1000)


class RescheduleReservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    resources: tuple[ResourceChoiceModel, ...] = Field(min_length=1, max_length=20)
    location_id: UUID | None = None


class ReservationView(BaseModel):
    id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    attendance_status: str

    @classmethod
    def from_contract(cls, reservation: Reservation) -> "ReservationView":
        return cls(
            id=reservation.id,
            offering_version_id=reservation.offering_version_id,
            subject_party_id=reservation.subject_party_id,
            location_id=reservation.location_id,
            start_at=reservation.start_at,
            end_at=reservation.end_at,
            status=reservation.status.value,
            revision=reservation.revision,
            attendance_status=reservation.attendance_status.value,
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

    subject_party_id: UUID
    reason: str | None = Field(default=None, max_length=1000)
