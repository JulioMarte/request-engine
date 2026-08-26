from request_engine.modules.booking.adapters.db.live_capacity_source import (
    PostgresOperationalAvailabilitySource,
)
from request_engine.modules.booking.contracts.live_capacity import OperationalAvailabilitySource


def build_live_capacity_source() -> OperationalAvailabilitySource:
    return PostgresOperationalAvailabilitySource()
