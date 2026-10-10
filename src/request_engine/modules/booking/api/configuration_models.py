"""Typed HTTP receipts for booking supply commands; not application state types."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AvailabilityWindowView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


class ResourceBootstrapView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    resource_id: UUID
    resource_key: str
    display_name: str
    capacity_model: Literal["exclusive", "units"]
    capacity_units: int
    availability_revision: int
    capability_ids: tuple[UUID, ...]
    weekly_availability: tuple[AvailabilityWindowView, ...]
    resource_location_assignment_id: UUID | None


class ResourceAssignmentView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    assignment_id: UUID
    resource_id: UUID
    location_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    assignment_revision: int
    resource_availability_revision: int


class RetiredResourceAssignmentView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    assignment_id: UUID
    retired_at: datetime
    assignment_revision: int
    resource_availability_revision: int


class ResourceAvailabilityView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    assignment_id: UUID
    windows: tuple[AvailabilityWindowView, ...]
    resource_availability_revision: int


class BookingContextTermsView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    context_terms_id: UUID
    resource_location_assignment_id: UUID
    offering_version_id: UUID
    effective_from: datetime
    effective_until: datetime | None
    amount: Decimal | None = Field(
        description="Exact decimal amount serialized as a JSON string, never a binary float.",
        examples=["19.90"],
    )
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool
    revision: int


class AssignmentScheduleExceptionView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    exception_id: UUID
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    reason: str | None
    active: bool
    resource_availability_revision: int


class ResourceScheduleExceptionView(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    exception_id: UUID
    resource_id: UUID
    start_at: datetime
    end_at: datetime
    exception_kind: Literal["available", "unavailable"]
    reason: str | None
    resource_availability_revision: int
