from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    EstimateSource,
    ProjectionWorkItem,
    WorkloadEstimate,
)
from request_engine.modules.live_capacity.domain.intake import evaluate_intake

pytestmark = [pytest.mark.unit, pytest.mark.contract]

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)


def test_additional_known_workload_reports_fit_without_mutation() -> None:
    existing = ProjectionWorkItem(
        key=UUID(int=1),
        duration_seconds=30 * 60,
        source=EstimateSource.CONFIGURED_POLICY,
    )
    estimate = WorkloadEstimate(20 * 60, EstimateSource.CONFIGURED_POLICY)

    result = evaluate_intake(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=1)),),
        existing_work=(existing,),
        estimate=estimate,
    )

    assert result.fits_within_effective_availability is True
    assert result.estimated_start == NOW + timedelta(minutes=30)
    assert result.estimated_end == NOW + timedelta(minutes=50)


def test_additional_workload_reports_not_fit_when_horizon_is_exhausted() -> None:
    existing = ProjectionWorkItem(
        key=UUID(int=1),
        duration_seconds=50 * 60,
        source=EstimateSource.CONFIGURED_POLICY,
    )
    estimate = WorkloadEstimate(20 * 60, EstimateSource.CONFIGURED_POLICY)

    result = evaluate_intake(
        observed_at=NOW,
        intervals=(CapacityInterval(NOW, NOW + timedelta(hours=1)),),
        existing_work=(existing,),
        estimate=estimate,
    )

    assert result.fits_within_effective_availability is False
    assert result.estimated_start == NOW + timedelta(minutes=50)
    assert result.estimated_end is None
