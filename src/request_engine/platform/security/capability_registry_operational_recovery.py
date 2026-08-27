from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
    query_capability,
)


OPERATIONAL_RECOVERY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "operational_recovery.read",
        CapabilityExposure.OPERATOR,
        "Read an immutable operational-recovery proposal and its provenance.",
    ),
    command_capability(
        "operational_recovery.propose",
        CapabilityExposure.OPERATOR,
        "Create an immutable proposal for a material operational capacity shortfall.",
    ),
    command_capability(
        "operational_recovery.execute",
        CapabilityExposure.OPERATOR,
        "Explicitly execute one proposal-bound Reservation recovery action.",
    ),
)