from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.contracts.discovery import PublishedSlotQuery

_MAX_BATCH_QUERIES = 200


class PublishedSlotQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: UUID
    publication_id: UUID
    publication_revision: int = Field(ge=1)
    mapping_id: UUID
    mapping_revision: int = Field(ge=1)
    offering_version_id: UUID
    window_start: datetime
    window_end: datetime
    location_id: UUID
    resource_id: UUID | None = None
    limit: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def validate_window(self) -> "PublishedSlotQueryBody":
        if self.window_start.utcoffset() is None or self.window_end.utcoffset() is None:
            raise ValueError("gateway window must be timezone-aware")
        if self.window_end <= self.window_start:
            raise ValueError("gateway window_end must be after window_start")
        if self.window_end - self.window_start > timedelta(days=7):
            raise ValueError("gateway window cannot exceed 7 days")
        return self

    def to_contract(self) -> PublishedSlotQuery:
        return PublishedSlotQuery(
            organization_id=self.organization_id,
            publication_id=self.publication_id,
            publication_revision=self.publication_revision,
            mapping_id=self.mapping_id,
            mapping_revision=self.mapping_revision,
            offering_version_id=self.offering_version_id,
            window_start=self.window_start,
            window_end=self.window_end,
            location_id=self.location_id,
            resource_id=self.resource_id,
            limit=self.limit,
        )


class PublishedSlotBatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: tuple[PublishedSlotQueryBody, ...] = Field(
        min_length=1,
        max_length=_MAX_BATCH_QUERIES,
    )


class ResourceChoiceView(BaseModel):
    requirement_id: UUID
    resource_id: UUID
    resource_location_assignment_id: UUID | None = None
    assignment_revision: int | None = None
    availability_revision: int | None = None

    @classmethod
    def from_contract(cls, choice: ResourceChoice) -> "ResourceChoiceView":
        return cls(
            requirement_id=choice.requirement_id,
            resource_id=choice.resource_id,
            resource_location_assignment_id=choice.resource_location_assignment_id,
            assignment_revision=choice.assignment_revision,
            availability_revision=choice.availability_revision,
        )


class PublishedSlotView(BaseModel):
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoiceView, ...]
    planned_duration_minutes: int | None = None
    amount: Decimal | None = None
    currency: str | None = None
    location_operational_revision: int | None = None
    configuration_fingerprint: str | None = None

    @classmethod
    def from_contract(cls, slot: AppointmentSlot) -> "PublishedSlotView":
        return cls(
            offering_version_id=slot.offering_version_id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            location_id=slot.location_id,
            resources=tuple(ResourceChoiceView.from_contract(item) for item in slot.resources),
            planned_duration_minutes=slot.planned_duration_minutes,
            amount=slot.amount,
            currency=slot.currency,
            location_operational_revision=slot.location_operational_revision,
            configuration_fingerprint=slot.configuration_fingerprint,
        )
