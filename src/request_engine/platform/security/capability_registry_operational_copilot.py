from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
    query_capability,
)

OPERATIONAL_COPILOT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "operational_copilot.read",
        CapabilityExposure.OPERATOR,
        "Read authoritative owner-backed operational lookup and state used by structured tools.",
    ),
    command_capability(
        "operational_copilot.interpret",
        CapabilityExposure.OPERATOR,
        "Interpret bounded operational natural-language requests into typed owner commands. "
        "The decision carries trusted identity and is replay-safe, but no mutation executes here.",
    ),
    command_capability(
        "operational_copilot.execute",
        CapabilityExposure.OPERATOR,
        "Execute only explicitly registered copilot operations while preserving the owning "
        "module's capability, concurrency, idempotency and authority gates.",
    ),
)
