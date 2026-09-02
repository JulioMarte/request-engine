from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    query_capability,
)

FRONT_DESK_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "front_desk.day_board.read",
        CapabilityExposure.OPERATOR,
        "Read the tenant-scoped front-desk day board without per-subject authority.",
    ),
)
