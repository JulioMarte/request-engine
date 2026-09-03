from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class EstimateSource(StrEnum):
    RESOURCE_HISTORY = "resource_history"
    TENANT_HISTORY = "tenant_history"
    CONFIGURED_POLICY = "configured_policy"
    PLANNED_DURATION = "planned_duration"
    UNKNOWN = "unknown"


class ProjectionState(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    INDETERMINATE = "indeterminate"


class ProjectionReason(StrEnum):
    UNKNOWN_WORKLOAD_DURATION = "unknown_workload_duration"
    OPEN_INTERRUPTION = "open_interruption"
    OPEN_RESOURCE_ACTIVITY = "open_resource_activity"
    NO_REMAINING_AVAILABILITY = "no_remaining_availability"
    ACTIVE_RECALL_HOLD = "active_recall_hold"
    ACTIVE_SKIP = "active_skip"


@dataclass(frozen=True, slots=True)
class CapacityInterval:
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True, slots=True)
class WorkloadEstimate:
    duration_seconds: int | None
    source: EstimateSource
    sample_count: int = 0


@dataclass(frozen=True, slots=True)
class ProjectionWorkItem:
    key: UUID
    duration_seconds: int | None
    source: EstimateSource
    queue_entry_id: UUID | None = None
    reservation_id: UUID | None = None
    active_service_seconds: int = 0


@dataclass(frozen=True, slots=True)
class ProjectedWorkItem:
    key: UUID
    estimated_start: datetime | None
    estimated_end: datetime | None
    remaining_seconds: int | None
    source: EstimateSource


@dataclass(frozen=True, slots=True)
class LiveCapacityProjection:
    observed_at: datetime
    state: ProjectionState
    reasons: tuple[ProjectionReason, ...]
    remaining_operational_seconds: int
    projected_remaining_workload_seconds: int | None
    projected_end_at: datetime | None
    live_headroom_seconds: int | None
    items: tuple[ProjectedWorkItem, ...]
    scheduled_committed_workload_seconds: int | None = None
    scheduled_headroom_seconds: int | None = None
    live_intake_headroom_seconds: int | None = None
    live_vs_scheduled_headroom_delta_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class IntakeEvaluation:
    observed_at: datetime
    estimate: WorkloadEstimate
    estimated_start: datetime | None
    estimated_end: datetime | None
    fits_within_effective_availability: bool | None
    state: ProjectionState
    reasons: tuple[ProjectionReason, ...]
