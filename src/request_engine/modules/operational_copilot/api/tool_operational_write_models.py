from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from request_engine.modules.operational_copilot.contracts import (
    ExtendOperationalDayIntent,
    SetOperationalIntakeIntent,
)


class SetOperationalIntakeBody(BaseModel):
    service_queue_id: UUID
    accepting: bool
    expected_intake_revision: int = Field(ge=0)
    reason: str | None = None
    effective_until: datetime | None = None

    def to_intent(self) -> SetOperationalIntakeIntent:
        return SetOperationalIntakeIntent(**self.model_dump())


class ExtendOperationalDayBody(BaseModel):
    assignment_id: UUID
    start_at: datetime
    end_at: datetime
    expected_resource_availability_revision: int = Field(ge=0)
    reason: str

    def to_intent(self) -> ExtendOperationalDayIntent:
        return ExtendOperationalDayIntent(**self.model_dump())
