from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.application.errors import (
    CustomerProjectionTargetNotFound,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    capacity_intervals,
    existing_work,
    has_open_interruption,
)
from request_engine.modules.live_capacity.application.queries.customer_projection import (
    ReadCustomerLiveCapacityQuery,
)
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.customer_projection import (
    CustomerLiveCapacityProjection,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity
from request_engine.platform.db.read_snapshot import tenant_read_snapshot
from request_engine.platform.db.session import SessionFactory


class PostgresCustomerLiveCapacityReader:
    def __init__(self, session_factory: SessionFactory, sources: LiveCapacitySources) -> None:
        self._session_factory = session_factory
        self._sources = sources

    async def customer_projection(
        self, query: ReadCustomerLiveCapacityQuery
    ) -> CustomerLiveCapacityProjection:
        async with tenant_read_snapshot(self._session_factory, query.organization_id) as snapshot:
            projection_snapshot = await capture_projection_snapshot(
                snapshot,
                sources=self._sources,
                organization_id=query.organization_id,
                service_queue_id=query.service_queue_id,
            )
            target = await self._sources.queue.read_customer_projection_target(
                snapshot,
                organization_id=query.organization_id,
                principal_id=query.principal_id,
                queue_id=query.service_queue_id,
                subject_party_id=query.subject_party_id,
                allow_subject_override=query.allow_subject_override,
            )
        if target is None:
            raise CustomerProjectionTargetNotFound(query.service_queue_id)

        projection = project_live_capacity(
            observed_at=projection_snapshot.observed_at,
            intervals=capacity_intervals(projection_snapshot),
            work_items=existing_work(projection_snapshot),
            has_open_interruption=has_open_interruption(projection_snapshot),
            has_open_resource_activity=(
                projection_snapshot.delivery.open_resource_activity is not None
            ),
        )
        item_key = target.queue_entry_id
        active = projection_snapshot.delivery.active_service
        if active is not None and active.queue_entry_id == target.queue_entry_id:
            item_key = active.service_session_id
        projected = next((item for item in projection.items if item.key == item_key), None)
        estimated_start = projected.estimated_start if projected is not None else None
        wait_seconds = (
            max(0, int((estimated_start - projection.observed_at).total_seconds()))
            if estimated_start is not None
            else None
        )
        return CustomerLiveCapacityProjection(
            observed_at=projection.observed_at,
            entries_ahead=target.entries_ahead,
            estimated_wait_seconds=wait_seconds,
            estimated_start=estimated_start,
        )
