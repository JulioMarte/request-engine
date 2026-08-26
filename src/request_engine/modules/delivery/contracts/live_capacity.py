from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.platform.db.read_snapshot_types import ReadSnapshot


@dataclass(frozen=True, slots=True)
class ActiveServiceProjectionFact:
    service_session_id: UUID
    queue_entry_id: UUID
    resource_id: UUID
    location_id: UUID
    status: str
    actual_workload_classification_id: UUID | None
    started_at: datetime
    active_service_seconds: int
    has_open_interruption: bool


@dataclass(frozen=True, slots=True)
class ResourceOccupationProjectionFact:
    resource_activity_id: UUID
    resource_id: UUID
    location_id: UUID | None
    started_at: datetime
    has_known_end: bool


@dataclass(frozen=True, slots=True)
class DeliveryProjectionSnapshot:
    observed_at: datetime
    active_service: ActiveServiceProjectionFact | None
    open_resource_activity: ResourceOccupationProjectionFact | None


@dataclass(frozen=True, slots=True)
class HistoricalServiceObservation:
    service_session_id: UUID
    resource_id: UUID
    workload_classification_id: UUID
    completed_at: datetime
    active_service_seconds: int


class DeliveryProjectionSource(Protocol):
    async def read_projection_delivery(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        resource_id: UUID,
        location_id: UUID,
        observed_at: datetime,
    ) -> DeliveryProjectionSnapshot: ...

    async def read_completed_history(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        resource_id: UUID,
        workload_classification_id: UUID,
        observed_at: datetime,
        lookback_days: int,
        limit: int,
        resource_specific: bool,
    ) -> tuple[HistoricalServiceObservation, ...]: ...
