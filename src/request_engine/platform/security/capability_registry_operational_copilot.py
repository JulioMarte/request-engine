from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    query_capability,
)

OPERATIONAL_COPILOT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "operational_copilot.interpret",
        CapabilityExposure.OPERATOR,
        "Interpret bounded operational natural-language requests into typed owner commands. "
        "No mutation is executed by this surface.",
    ),
)
