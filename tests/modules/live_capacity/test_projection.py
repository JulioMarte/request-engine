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


def test_active_recall_hold_degrades_the_timeline_but_keeps_workload() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        work_items=(_work(1, 20 * 60), _work(2, 30 * 60)),
        has_active_recall_hold=True,
    )

    assert result.state is ProjectionState.PARTIAL
    assert result.reasons == (ProjectionReason.ACTIVE_RECALL_HOLD,)
    assert result.projected_remaining_workload_seconds == 50 * 60
    assert all(item.estimated_start is None and item.estimated_end is None for item in result.items)
    assert all(item.remaining_seconds in (20 * 60, 30 * 60) for item in result.items)
    assert result.projected_end_at is None
    assert result.live_intake_headroom_seconds is None


def test_active_skip_degrades_the_timeline_but_keeps_workload() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        work_items=(_work(1, 20 * 60),),
        has_active_skip=True,
    )

    assert result.state is ProjectionState.PARTIAL
    assert result.reasons == (ProjectionReason.ACTIVE_SKIP,)
    assert result.projected_remaining_workload_seconds == 20 * 60
    assert all(item.estimated_start is None for item in result.items)
    assert result.live_intake_headroom_seconds is None


def test_active_triage_gate_with_open_interruption_is_indeterminate_with_both_reasons() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        work_items=(_work(1, 20 * 60),),
        has_open_interruption=True,
        has_active_recall_hold=True,
    )

    assert result.state is ProjectionState.INDETERMINATE
    assert set(result.reasons) == {
        ProjectionReason.OPEN_INTERRUPTION,
        ProjectionReason.ACTIVE_RECALL_HOLD,
    }


def test_without_triage_facts_projection_keeps_the_precise_timeline() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        work_items=(_work(1, 20 * 60),),
    )

    assert result.state is ProjectionState.KNOWN
    assert result.reasons == ()
    assert result.live_intake_headroom_seconds is not None
    assert result.projected_end_at is not None
