from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
)

DISCOVERY_OPERATIONAL_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "discovery.manage",
        CapabilityExposure.OPERATOR,
        "Configure Discovery classifications, public profiles and supply publications. "
        "Owner commands additionally validate exact operations.manage_discovery "
        "Representation authority and operation-specific expected revisions.",
    ),
)
