from dataclasses import dataclass
from uuid import UUID

from request_engine.modules.live_capacity.contracts.projection import LiveCapacityProjection


@dataclass(frozen=True, slots=True)
class StaffLiveCapacityProjection:
    service_queue_id: UUID
    resource_id: UUID
    location_id: UUID
    projection: LiveCapacityProjection
