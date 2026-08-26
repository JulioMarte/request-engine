from datetime import datetime
from uuid import UUID

from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSource
from request_engine.modules.live_capacity.contracts.projection import WorkloadEstimate
from request_engine.modules.live_capacity.domain.estimation import (
    HISTORY_LOOKBACK_DAYS,
    MAX_HISTORY_SAMPLES,
    MIN_HISTORY_SAMPLES,
    resolve_workload_estimate,
)
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


async def resolve_estimates(
    snapshot: ReadSnapshot,
    *,
    delivery: DeliveryProjectionSource,
    organization_id: UUID,
    resource_id: UUID,
    observed_at: datetime,
    workload_ids: tuple[UUID, ...],
    configured_seconds: dict[UUID, int],
) -> dict[UUID, WorkloadEstimate]:
    result: dict[UUID, WorkloadEstimate] = {}
    for workload_id in workload_ids:
        resource_history = await delivery.read_completed_history(
            snapshot,
            organization_id=organization_id,
            resource_id=resource_id,
            workload_classification_id=workload_id,
            observed_at=observed_at,
            lookback_days=HISTORY_LOOKBACK_DAYS,
            limit=MAX_HISTORY_SAMPLES,
            resource_specific=True,
        )
        tenant_history = ()
        if len(resource_history) < MIN_HISTORY_SAMPLES:
            tenant_history = await delivery.read_completed_history(
                snapshot,
                organization_id=organization_id,
                resource_id=resource_id,
                workload_classification_id=workload_id,
                observed_at=observed_at,
                lookback_days=HISTORY_LOOKBACK_DAYS,
                limit=MAX_HISTORY_SAMPLES,
                resource_specific=False,
            )
        result[workload_id] = resolve_workload_estimate(
            resource_history_seconds=[item.active_service_seconds for item in resource_history],
            tenant_history_seconds=[item.active_service_seconds for item in tenant_history],
            configured_duration_seconds=configured_seconds.get(workload_id),
            planned_duration_seconds=None,
        )
    return result
