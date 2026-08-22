from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel


class AssignmentBody(BaseModel):
    authority_party_id: UUID
    resource_id: UUID
    location_id: UUID
    effective_from: datetime
    effective_until: datetime | None = None
    expected_resource_availability_revision: int


class RetireAssignmentBody(BaseModel):
    authority_party_id: UUID
    retired_at: datetime
    expected_assignment_revision: int
    expected_resource_availability_revision: int


class AvailabilityWindowBody(BaseModel):
    weekday: int
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None


class AvailabilityBody(BaseModel):
    authority_party_id: UUID
    expected_resource_availability_revision: int
    windows: tuple[AvailabilityWindowBody, ...]
