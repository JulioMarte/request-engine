from datetime import datetime
from uuid import UUID

from request_engine.modules.delivery.adapters.db.live_capacity_current_source import (
    read_projection_delivery,
)
from request_engine.modules.delivery.adapters.db.live_capacity_history_source import (
    read_completed_history,
)
from request_engine.modules.delivery.contracts.live_capacity import (
    DeliveryProjectionSnapshot,
    HistoricalServiceObservation,
)
from request_engine.platform.db.read_snapshot import postgres_snapshot_session
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


class PostgresDeliveryProjectionSource:
    async def read_projection_delivery(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        resource_id: UUID,
        location_id: UUID,
        observed_at: datetime,
    ) -> DeliveryProjectionSnapshot:
        return await read_projection_delivery(
            postgres_snapshot_session(snapshot),
            organization_id=organization_id,
            resource_id=resource_id,
            location_id=location_id,
            observed_at=observed_at,
        )

    async def read_completed_history(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        resource_id: UUID,
        workload_classification_id: UUID,
        observed_at: datetime,
        lookback_days: int,
        limit: int,
        resource_specific: bool,
    ) -> tuple[HistoricalServiceObservation, ...]:
        return await read_completed_history(
            postgres_snapshot_session(snapshot),
            organization_id=organization_id,
            resource_id=resource_id,
            workload_classification_id=workload_classification_id,
            observed_at=observed_at,
            lookback_days=lookback_days,
            limit=limit,
            resource_specific=resource_specific,
        )
