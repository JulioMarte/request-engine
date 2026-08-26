from request_engine.modules.delivery.adapters.db.live_capacity_source import (
    PostgresDeliveryProjectionSource,
)
from request_engine.modules.delivery.contracts.live_capacity import DeliveryProjectionSource


def build_live_capacity_source() -> DeliveryProjectionSource:
    return PostgresDeliveryProjectionSource()
