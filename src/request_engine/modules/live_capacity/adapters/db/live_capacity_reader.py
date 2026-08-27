from request_engine.modules.live_capacity.adapters.db.projection_snapshot import (
    capture_projection_snapshot,
)
from request_engine.modules.live_capacity.application.projection_assembly import (
    assemble_live_capacity_projection,
)
from request_engine.modules.live_capacity.application.queries.projection import (
    ReadStaffLiveCapacityQuery,
)
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.staff_projection import (
    StaffLiveCapacityProjection,
)
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
        projection = assemble_live_capacity_projection(snapshot)
        return StaffLiveCapacityProjection(
            service_queue_id=query.service_queue_id,
            resource_id=snapshot.policy.resource_id,
            location_id=snapshot.policy.location_id,
            projection=projection,
        )
