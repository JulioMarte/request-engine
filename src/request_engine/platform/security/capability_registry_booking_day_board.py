from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    query_capability,
)

BOOKING_DAY_BOARD_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "appointments.day_board",
        CapabilityExposure.OPERATOR,
        "Read the bounded operator reservation day board without per-subject authority.",
    ),
)
