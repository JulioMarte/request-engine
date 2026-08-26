from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    capacity_intervals,
    existing_work,
    has_open_interruption,
    scheduled_commitments,
)
from request_engine.modules.live_capacity.application.queries.projection import (
    ReadStaffLiveCapacityQuery,
)
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.staff_projection import (
    StaffLiveCapacityProjection,
)
from request_engine.modules.live_capacity.domain.projection import project_live_capacity
from request_engine.platform.db.read_snapshot import tenant_read_snapshot
from request_engine.platform.db.session import SessionFactory


class PostgresLiveCapacityReader:
    def __init__(self, session_factory: SessionFactory, sources: LiveCapacitySources) -> None:
        self._session_factory = session_factory
        self._sources = sources

    async def staff_projection(
        self, query: ReadStaffLiveCapacityQuery
    ) -> StaffLiveCapacityProjection:
        async with tenant_read_snapshot(self._session_factory, query.organization_id) as session:
            snapshot = await capture_projection_snapshot(
                session,
                sources=self._sources,
                organization_id=query.organization_id,
                service_queue_id=query.service_queue_id,
            )
        projection = project_live_capacity(
            observed_at=snapshot.observed_at,
            intervals=capacity_intervals(snapshot),
            work_items=existing_work(snapshot),
            scheduled_work_items=scheduled_commitments(snapshot),
            has_open_interruption=has_open_interruption(snapshot),
            has_open_resource_activity=snapshot.delivery.open_resource_activity is not None,
        )
        return StaffLiveCapacityProjection(
            service_queue_id=query.service_queue_id,
            resource_id=snapshot.policy.resource_id,
            location_id=snapshot.policy.location_id,
            projection=projection,
        )
