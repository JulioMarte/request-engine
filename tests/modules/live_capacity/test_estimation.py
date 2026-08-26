import pytest

from request_engine.modules.live_capacity.contracts.projection import EstimateSource
from request_engine.modules.live_capacity.domain.estimation import resolve_workload_estimate

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_resource_history_wins_with_robust_median() -> None:
    estimate = resolve_workload_estimate(
        resource_history_seconds=[900, 1200, 1200, 1500, 7200],
        tenant_history_seconds=[1800] * 5,
        configured_duration_seconds=2400,
        planned_duration_seconds=3000,
    )

    assert estimate.duration_seconds == 1200
    assert estimate.source is EstimateSource.RESOURCE_HISTORY
    assert estimate.sample_count == 5


def test_insufficient_resource_history_falls_back_to_tenant_history() -> None:
    estimate = resolve_workload_estimate(
        resource_history_seconds=[600, 600, 900, 900],
        tenant_history_seconds=[1200, 1200, 1500, 1800, 2400],
        configured_duration_seconds=3000,
        planned_duration_seconds=3600,
    )

    assert estimate.duration_seconds == 1500
    assert estimate.source is EstimateSource.TENANT_HISTORY


def test_estimator_bounds_eligible_history_to_sixty_four_samples() -> None:
    estimate = resolve_workload_estimate(
        resource_history_seconds=[0, 0, *([600] * 64), *([7200] * 64)],
        tenant_history_seconds=[],
        configured_duration_seconds=None,
        planned_duration_seconds=None,
    )

    assert estimate.duration_seconds == 600
    assert estimate.sample_count == 64


def test_policy_then_planned_then_unknown_fallback_is_explicit() -> None:
    configured = resolve_workload_estimate(
        resource_history_seconds=[],
        tenant_history_seconds=[],
        configured_duration_seconds=1500,
        planned_duration_seconds=1800,
    )
    planned = resolve_workload_estimate(
        resource_history_seconds=[],
        tenant_history_seconds=[],
        configured_duration_seconds=None,
        planned_duration_seconds=1800,
    )
    unknown = resolve_workload_estimate(
        resource_history_seconds=[],
        tenant_history_seconds=[],
        configured_duration_seconds=None,
        planned_duration_seconds=None,
    )

    assert (configured.duration_seconds, configured.source) == (
        1500,
        EstimateSource.CONFIGURED_POLICY,
    )
    assert (planned.duration_seconds, planned.source) == (
        1800,
        EstimateSource.PLANNED_DURATION,
    )
    assert unknown.duration_seconds is None
    assert unknown.source is EstimateSource.UNKNOWN
