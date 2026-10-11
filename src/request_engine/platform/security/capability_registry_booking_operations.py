from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)

BOOKING_OPERATIONAL_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "booking.read_supply",
        CapabilityExposure.OPERATOR,
        "Read resource supply configuration and current concurrency revisions.",
    ),
    command_capability(
        "booking.manage_supply",
        CapabilityExposure.OPERATOR,
        (
            "Manage Booking supply, including Resources, Location assignments, availability "
            "and bounded operational schedule adjustments."
        ),
        revision=RevisionPolicy.REQUIRED,
    ),
)
