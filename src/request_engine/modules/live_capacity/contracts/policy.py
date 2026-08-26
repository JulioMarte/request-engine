from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProjectionScopePolicy:
    id: UUID
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    active: bool
    revision: int


@dataclass(frozen=True, slots=True)
class WorkloadEstimatePolicy:
    id: UUID
    workload_classification_id: UUID
    duration_seconds: int
    active: bool
    revision: int
