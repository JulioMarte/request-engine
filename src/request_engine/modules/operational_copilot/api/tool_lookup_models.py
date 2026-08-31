from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.booking.contracts.copilot import CopilotResourceMatch
from request_engine.modules.catalog.contracts.copilot import (
    CopilotLocationClock,
    CopilotOfferingMatch,
)
from request_engine.modules.queue.contracts.copilot import CopilotQueueMatch


class ResourceCandidateView(BaseModel):
    resource_id: UUID
    location_id: UUID
    assignment_id: UUID
    resource_availability_revision: int

    @classmethod
    def from_match(cls, value: CopilotResourceMatch) -> "ResourceCandidateView":
        return cls(
            resource_id=value.resource_id,
            location_id=value.location_id,
            assignment_id=value.assignment_id,
            resource_availability_revision=value.resource_availability_revision,
        )


class OfferingCandidateView(BaseModel):
    offering_id: UUID
    display_name: str

    @classmethod
    def from_match(cls, value: CopilotOfferingMatch) -> "OfferingCandidateView":
        return cls(offering_id=value.offering_id, display_name=value.display_name)


class QueueCandidateView(BaseModel):
    service_queue_id: UUID
    location_id: UUID

    @classmethod
    def from_match(cls, value: CopilotQueueMatch) -> "QueueCandidateView":
        return cls(service_queue_id=value.service_queue_id, location_id=value.location_id)


class LocationClockView(BaseModel):
    location_id: UUID
    timezone: str
    observed_at: datetime
    operational_day_end_at: datetime | None
    operational_revision: int

    @classmethod
    def from_clock(cls, value: CopilotLocationClock) -> "LocationClockView":
        return cls(
            location_id=value.location_id,
            timezone=value.timezone,
            observed_at=value.observed_at,
            operational_day_end_at=value.operational_day_end_at,
            operational_revision=value.operational_revision,
        )


class AssignmentDayEndView(BaseModel):
    assignment_id: UUID
    weekday: int
    day_end: time | None
