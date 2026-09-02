from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from request_engine.modules.operational_copilot.api.models import F6RequestBody
from request_engine.modules.operational_copilot.contracts import (
    ExtendOperationalDayIntent,
    SetOperationalIntakeIntent,
)


class SetOperationalIntakeBody(F6RequestBody):
    service_queue_id: UUID
    accepting: bool
    expected_intake_revision: int = Field(ge=1)
    reason: str | None = None
    effective_until: datetime | None = None

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("reason cannot be blank")
        return value

    @field_validator("effective_until")
    @classmethod
    def validate_effective_until(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("effective_until must be timezone-aware")
        return value

    def to_intent(self) -> SetOperationalIntakeIntent:
        return SetOperationalIntakeIntent(**self.model_dump())


class ExtendOperationalDayBody(F6RequestBody):
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_resource_availability_revision: int = Field(ge=1)
    reason: str

    def to_intent(self) -> ExtendOperationalDayIntent:
        return ExtendOperationalDayIntent(**self.model_dump())
