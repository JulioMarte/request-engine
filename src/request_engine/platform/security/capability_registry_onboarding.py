from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    query_capability,
)

ONBOARDING_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "onboarding.read",
        CapabilityExposure.OPERATOR,
        "Read the advisory onboarding readiness report for the organization.",
    ),
)
