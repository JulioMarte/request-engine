from datetime import UTC, datetime, timedelta
from uuid import uuid4

from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    EstimateSource,
    ProjectionReason,
    ProjectionState,
    ProjectionWorkItem,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity


def test_active_recall_hold_makes_projection_indeterminate_without_dropping_capacity() -> None:
    observed = datetime(2035, 1, 1, 9, 0, tzinfo=UTC)
    projection = project_live_capacity(
        observed_at=observed,
        intervals=(CapacityInterval(observed, observed + timedelta(hours=4)),),
        work_items=(
            ProjectionWorkItem(
                key=uuid4(),
                duration_seconds=1800,
                source=EstimateSource.CONFIGURED_POLICY,
            ),
        ),
        has_active_recall_hold=True,
    )

    assert projection.state is ProjectionState.INDETERMINATE
    assert projection.reasons == (ProjectionReason.ACTIVE_RECALL_HOLD,)
    assert projection.remaining_operational_seconds == 4 * 60 * 60
    assert projection.projected_remaining_workload_seconds is None
    assert projection.items == ()
