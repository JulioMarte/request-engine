from request_engine.platform.security.capability_registry_booking_operations import (
    BOOKING_OPERATIONAL_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_delivery_live import (
    LIVE_DELIVERY_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_live_capacity import (
    LIVE_CAPACITY_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_operational_copilot import (
    OPERATIONAL_COPILOT_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_operational_recovery import (
    OPERATIONAL_RECOVERY_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_party_registry import (
    PARTY_REGISTRY_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_queue_live import LIVE_QUEUE_CAPABILITIES
from request_engine.platform.security.capability_registry_queue_same_day import (
    SAME_DAY_QUEUE_CAPABILITIES,
)
from request_engine.platform.security.capability_registry_staff_contacts import (
    STAFF_CONTACT_CAPABILITIES,
)
from request_engine.platform.security.capability_types import CapabilityDefinition

LIVE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    LIVE_QUEUE_CAPABILITIES
    + SAME_DAY_QUEUE_CAPABILITIES
    + LIVE_DELIVERY_CAPABILITIES
    + LIVE_CAPACITY_CAPABILITIES
    + BOOKING_OPERATIONAL_CAPABILITIES
    + OPERATIONAL_RECOVERY_CAPABILITIES
    + OPERATIONAL_COPILOT_CAPABILITIES
    + PARTY_REGISTRY_CAPABILITIES
    + STAFF_CONTACT_CAPABILITIES
)
