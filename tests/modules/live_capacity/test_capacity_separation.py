from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    EstimateSource,
    ProjectionWorkItem,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.temporal]

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def _work(key: int, seconds: int) -> ProjectionWorkItem:
    return ProjectionWorkItem(UUID(int=key), seconds, EstimateSource.CONFIGURED_POLICY)


def test_scheduled_and_live_headroom_are_explicit_and_can_diverge() -> None:
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=2)),),
        scheduled_work_items=(_work(1, 30 * 60), _work(2, 30 * 60)),
        work_items=(_work(3, 45 * 60), _work(4, 45 * 60)),
    )

    assert result.scheduled_committed_workload_seconds == 60 * 60
    assert result.scheduled_headroom_seconds == 60 * 60
    assert result.live_intake_headroom_seconds == 30 * 60
    assert result.live_headroom_seconds == result.live_intake_headroom_seconds
    assert result.live_vs_scheduled_headroom_delta_seconds == -30 * 60


def test_unknown_scheduled_commitment_does_not_fabricate_scheduled_headroom() -> None:
    unknown = ProjectionWorkItem(UUID(int=5), None, EstimateSource.UNKNOWN)
    result = project_live_capacity(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=1)),),
        scheduled_work_items=(unknown,),
        work_items=(_work(6, 10 * 60),),
    )

    assert result.scheduled_committed_workload_seconds is None
    assert result.scheduled_headroom_seconds is None
    assert result.live_intake_headroom_seconds == 50 * 60
    assert result.live_vs_scheduled_headroom_delta_seconds is None
