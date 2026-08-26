from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    ProjectedWorkItem,
    ProjectionReason,
    ProjectionState,
)
from request_engine.modules.live_capacity.contracts.staff_projection import (
    StaffLiveCapacityProjection,
)


class ProjectedWorkItemView(BaseModel):
    key: UUID
    estimated_start: datetime | None
    estimated_end: datetime | None
    remaining_seconds: int | None
    source: EstimateSource

    @classmethod
    def from_contract(cls, item: ProjectedWorkItem) -> "ProjectedWorkItemView":
        return cls(
            key=item.key,
            estimated_start=item.estimated_start,
            estimated_end=item.estimated_end,
            remaining_seconds=item.remaining_seconds,
            source=item.source,
        )


class StaffLiveCapacityProjectionView(BaseModel):
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    observed_at: datetime
    state: ProjectionState
    reasons: tuple[ProjectionReason, ...]
    remaining_operational_seconds: int
    scheduled_committed_workload_seconds: int | None
    scheduled_headroom_seconds: int | None
    projected_remaining_workload_seconds: int | None
    projected_end_at: datetime | None
    live_headroom_seconds: int | None
    live_intake_headroom_seconds: int | None
    live_vs_scheduled_headroom_delta_seconds: int | None
    items: tuple[ProjectedWorkItemView, ...]

    @classmethod
    def from_contract(cls, item: StaffLiveCapacityProjection) -> "StaffLiveCapacityProjectionView":
        projection = item.projection
        return cls(
            service_queue_id=item.service_queue_id,
            resource_id=item.resource_id,
            location_id=item.location_id,
            observed_at=projection.observed_at,
            state=projection.state,
            reasons=projection.reasons,
            remaining_operational_seconds=projection.remaining_operational_seconds,
            scheduled_committed_workload_seconds=projection.scheduled_committed_workload_seconds,
            scheduled_headroom_seconds=projection.scheduled_headroom_seconds,
            projected_remaining_workload_seconds=projection.projected_remaining_workload_seconds,
            projected_end_at=projection.projected_end_at,
            live_headroom_seconds=projection.live_headroom_seconds,
            live_intake_headroom_seconds=projection.live_intake_headroom_seconds,
            live_vs_scheduled_headroom_delta_seconds=(
                projection.live_vs_scheduled_headroom_delta_seconds
            ),
            items=tuple(ProjectedWorkItemView.from_contract(value) for value in projection.items),
        )
