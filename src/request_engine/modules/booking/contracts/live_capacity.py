from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.db.read_snapshot_types import ReadSnapshot


@dataclass(frozen=True, slots=True)
class OperationalAvailabilityInterval:
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class PlannedWorkloadFact:
    reservation_id: UUID
    offering_version_id: UUID
    planned_starts_at: datetime
    planned_ends_at: datetime
    planned_duration_seconds: int | None
    subject_party_id: UUID | None = None
    reservation_revision: int = 1


@dataclass(frozen=True, slots=True)
class ResourceOperationalAvailabilitySnapshot:
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    horizon_end: datetime
    configuration_valid: bool
    remaining_intervals: tuple[OperationalAvailabilityInterval, ...]
    planned_same_day_work: tuple[PlannedWorkloadFact, ...]


class OperationalAvailabilitySource(Protocol):
    async def read_operational_availability(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        resource_id: UUID,
        location_id: UUID,
        observed_at: datetime,
    ) -> ResourceOperationalAvailabilitySnapshot: ...
