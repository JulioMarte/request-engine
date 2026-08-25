from request_engine.platform.security.capability_registry_delivery_live import (
    LIVE_DELIVERY_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_queue_live import (
    LIVE_QUEUE_CAPABILITIES,
)
from request_engine.platform.security.capability_types import CapabilityDefinition

LIVE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    LIVE_QUEUE_CAPABILITIES + LIVE_DELIVERY_CAPABILITIES
)
