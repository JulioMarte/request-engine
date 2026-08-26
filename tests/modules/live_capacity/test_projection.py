from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    EstimateSource,
    ProjectionReason,
    ProjectionState,
    ProjectionWorkItem,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.temporal]

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def _work(key: int, seconds: int | None, active: int = 0) -> ProjectionWorkItem:
    return ProjectionWorkItem(
        UUID(int=key), seconds, EstimateSource.CONFIGURED_POLICY, active_service_seconds=active
    )


def test_projection_uses_discontinuous_effective_intervals() -> None:
    intervals = (
        CapacityInterval(NOW, NOW + timedelta(minutes=30)),
        CapacityInterval(NOW + timedelta(hours=1), NOW + timedelta(hours=2)),
    )

    result = project_live_capacity(
        observed_at=NOW,
        intervals=intervals,
        work_items=(_work(1, 45 * 60), _work(2, 30 * 60)),
    )

    assert result.state is ProjectionState.KNOWN
    assert result.remaining_operational_seconds == 90 * 60
    assert result.projected_remaining_workload_seconds == 75 * 60
    assert result.items[0].estimated_end == NOW + timedelta(hours=1, minutes=15)
    assert result.items[1].estimated_start == NOW + timedelta(hours=1, minutes=15)
    assert result.projected_end_at == NOW + timedelta(hours=1, minutes=45)
    assert result.live_headroom_seconds == 15 * 60


def test_current_service_counts_only_estimated_remaining_work() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=1)),),
        work_items=(_work(1, 30 * 60, active=20 * 60),),
    )

    assert result.projected_remaining_workload_seconds == 10 * 60
    assert result.projected_end_at == NOW + timedelta(minutes=10)


def test_unknown_duration_is_partial_and_never_fabricates_eta() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        work_items=(_work(1, None), _work(2, 20 * 60)),
    )

    assert result.state is ProjectionState.PARTIAL
    assert result.reasons == (ProjectionReason.UNKNOWN_WORKLOAD_DURATION,)
    assert result.projected_remaining_workload_seconds is None
    assert result.projected_end_at is None
    assert all(item.estimated_start is None for item in result.items)


def test_open_interruption_blocks_false_precision() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        work_items=(_work(1, 20 * 60),),
        has_open_interruption=True,
    )

    assert result.state is ProjectionState.INDETERMINATE
    assert result.reasons == (ProjectionReason.OPEN_INTERRUPTION,)
    assert result.projected_end_at is None
    assert result.live_headroom_seconds is None
