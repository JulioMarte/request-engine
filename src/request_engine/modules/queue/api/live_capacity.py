from request_engine.modules.queue.adapters.db.live_capacity_source import (
    PostgresQueueProjectionSource,
)
from request_engine.modules.queue.contracts.live_capacity import QueueProjectionSource


def build_live_capacity_source() -> QueueProjectionSource:
    return PostgresQueueProjectionSource()
