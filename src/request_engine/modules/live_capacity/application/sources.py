from dataclasses import dataclass

from request_engine.modules.booking.contracts.live_capacity import OperationalAvailabilitySource
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSource
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSource


@dataclass(frozen=True, slots=True)
class LiveCapacitySources:
    booking: OperationalAvailabilitySource
    queue: QueueProjectionSource
    delivery: DeliveryProjectionSource
