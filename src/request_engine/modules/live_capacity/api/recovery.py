from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilitySource,
)
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSource
from request_engine.modules.live_capacity.adapters.db.recovery_source import (
    PostgresRecoveryCapacitySource,
)
from request_engine.modules.live_capacity.application.sources import LiveCapacitySources
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSource
from request_engine.platform.db.session import SessionFactory


def build_recovery_capacity_source(
    session_factory: SessionFactory,
    *,
    booking_source: OperationalAvailabilitySource,
    queue_source: QueueProjectionSource,
    delivery_source: DeliveryProjectionSource,
) -> RecoveryCapacitySource:
    return PostgresRecoveryCapacitySource(
        session_factory,
        LiveCapacitySources(
            booking=booking_source,
            queue=queue_source,
            delivery=delivery_source,
        ),
    )
