from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
)

BOOKING_OPERATIONAL_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "booking.manage_supply",
        CapabilityExposure.OPERATOR,
        "Create bounded one-day resource availability exceptions.",
        revision=RevisionPolicy.REQUIRED,
    ),
)
