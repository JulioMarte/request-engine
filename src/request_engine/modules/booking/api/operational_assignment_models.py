from datetime import date, time
from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class AssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    resource_id: UUID
    location_id: UUID
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None = None
    expected_resource_availability_revision: int = Field(gt=0)

    @model_validator(mode="after")
    def effective_interval(self) -> Self:
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("effective_until must be after effective_from")
        return self


class RetireAssignmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    retired_at: AwareDatetime
    expected_assignment_revision: int = Field(gt=0)
    expected_resource_availability_revision: int = Field(gt=0)


class AvailabilityWindowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weekday: int = Field(ge=0, le=6)
    local_start: time
    local_end: time
    valid_from: date | None = None
    valid_until: date | None = None

    @model_validator(mode="after")
    def local_interval(self) -> Self:
        if self.local_start.tzinfo is not None or self.local_end.tzinfo is not None:
            raise ValueError("availability uses local wall-clock time without an offset")
        if self.local_start >= self.local_end:
            raise ValueError("local_start must be before local_end")
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError("valid_until must be on or after valid_from")
        return self


class AvailabilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    authority_party_id: UUID
    expected_resource_availability_revision: int = Field(gt=0)
    windows: tuple[AvailabilityWindowBody, ...]
