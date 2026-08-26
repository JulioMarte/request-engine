from collections.abc import Sequence

from request_engine.modules.live_capacity.contracts.projection import (
    EstimateSource,
    WorkloadEstimate,
)

MIN_HISTORY_SAMPLES = 5
MAX_HISTORY_SAMPLES = 64
HISTORY_LOOKBACK_DAYS = 90


def _median_seconds(samples: Sequence[int]) -> int:
    ordered = sorted(samples)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle] + 1) // 2


def _historical_estimate(samples: Sequence[int], source: EstimateSource) -> WorkloadEstimate | None:
    eligible = tuple(value for value in samples if value > 0)[:MAX_HISTORY_SAMPLES]
    if len(eligible) < MIN_HISTORY_SAMPLES:
        return None
    return WorkloadEstimate(
        duration_seconds=_median_seconds(eligible),
        source=source,
        sample_count=len(eligible),
    )


def resolve_workload_estimate(
    *,
    resource_history_seconds: Sequence[int],
    tenant_history_seconds: Sequence[int],
    configured_duration_seconds: int | None,
    planned_duration_seconds: int | None,
) -> WorkloadEstimate:
    resource = _historical_estimate(resource_history_seconds, EstimateSource.RESOURCE_HISTORY)
    if resource is not None:
        return resource
    tenant = _historical_estimate(tenant_history_seconds, EstimateSource.TENANT_HISTORY)
    if tenant is not None:
        return tenant
    if configured_duration_seconds is not None and configured_duration_seconds > 0:
        return WorkloadEstimate(configured_duration_seconds, EstimateSource.CONFIGURED_POLICY)
    if planned_duration_seconds is not None and planned_duration_seconds > 0:
        return WorkloadEstimate(planned_duration_seconds, EstimateSource.PLANNED_DURATION)
    return WorkloadEstimate(None, EstimateSource.UNKNOWN)
