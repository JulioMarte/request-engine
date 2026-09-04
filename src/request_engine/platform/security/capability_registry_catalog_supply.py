from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
)

CATALOG_SUPPLY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "catalog.manage",
        CapabilityExposure.OPERATOR,
        ("Bootstrap tenant catalog supply: register resource capabilities and create offerings."),
    ),
)
