from datetime import datetime
from uuid import UUID

from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    IntakeEvaluation,
    ProjectionState,
    ProjectionWorkItem,
    WorkloadEstimate,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity

_INTAKE_SENTINEL = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")


def evaluate_intake(
    *,
    observed_at: datetime,
    intervals: tuple[CapacityInterval, ...],
    existing_work: tuple[ProjectionWorkItem, ...],
    estimate: WorkloadEstimate,
    has_open_interruption: bool = False,
    has_open_resource_activity: bool = False,
    has_active_recall_hold: bool = False,
) -> IntakeEvaluation:
    candidate = ProjectionWorkItem(
        key=_INTAKE_SENTINEL,
        duration_seconds=estimate.duration_seconds,
        source=estimate.source,
    )
    projection = project_live_capacity(
        observed_at=observed_at,
        intervals=intervals,
        work_items=(*existing_work, candidate),
        has_open_interruption=has_open_interruption,
        has_open_resource_activity=has_open_resource_activity,
        has_active_recall_hold=has_active_recall_hold,
    )
    projected_candidate = projection.items[-1] if projection.items else None
    if (
        projected_candidate is not None
        and estimate.duration_seconds is not None
        and projection.state is not ProjectionState.INDETERMINATE
        and not has_active_recall_hold
    ):
        starts_at = projected_candidate.estimated_start
        ends_at = projected_candidate.estimated_end
        fits = ends_at is not None
    else:
        fits = None
        starts_at = None
        ends_at = None
    return IntakeEvaluation(
        observed_at=projection.observed_at,
        estimate=estimate,
        estimated_start=starts_at,
        estimated_end=ends_at,
        fits_within_effective_availability=fits,
        state=projection.state,
        reasons=projection.reasons,
    )
