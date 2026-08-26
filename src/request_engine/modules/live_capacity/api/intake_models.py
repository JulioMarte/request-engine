from datetime import datetime

from pydantic import BaseModel

from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    IntakeEvaluation,
    ProjectionReason,
    ProjectionState,
)


class IntakeEvaluationView(BaseModel):
    observed_at: datetime
    estimated_duration_seconds: int | None
    estimate_source: EstimateSource
    estimate_sample_count: int
    estimated_start: datetime | None
    estimated_end: datetime | None
    fits_within_effective_availability: bool | None
    state: ProjectionState
    reasons: tuple[ProjectionReason, ...]

    @classmethod
    def from_contract(cls, item: IntakeEvaluation) -> "IntakeEvaluationView":
        return cls(
            observed_at=item.observed_at,
            estimated_duration_seconds=item.estimate.duration_seconds,
            estimate_source=item.estimate.source,
            estimate_sample_count=item.estimate.sample_count,
            estimated_start=item.estimated_start,
            estimated_end=item.estimated_end,
            fits_within_effective_availability=item.fits_within_effective_availability,
            state=item.state,
            reasons=item.reasons,
        )
