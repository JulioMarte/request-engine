from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
)

OPERATIONAL_COPILOT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "operational_copilot.interpret",
        CapabilityExposure.OPERATOR,
        "Interpret bounded operational natural-language requests into typed owner commands. "
        "The decision carries trusted identity and is replay-safe, but no mutation executes here.",
    ),
)
