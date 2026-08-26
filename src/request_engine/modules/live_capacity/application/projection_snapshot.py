from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from request_engine.modules.booking.contracts.live_capacity import (
    ResourceOperationalAvailabilitySnapshot,
)
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSnapshot
from request_engine.modules.live_capacity.contracts.policy import ProjectionScopePolicy
from request_engine.modules.live_capacity.contracts.projection import WorkloadEstimate
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSnapshot


@dataclass(frozen=True, slots=True)
class ProjectionSnapshot:
    observed_at: datetime
    policy: ProjectionScopePolicy
    booking: ResourceOperationalAvailabilitySnapshot
    queue: QueueProjectionSnapshot
    delivery: DeliveryProjectionSnapshot
    estimates: dict[UUID, WorkloadEstimate]
