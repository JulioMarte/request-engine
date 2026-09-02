from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
)

QUEUE_TRIAGE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "queue.operator_select",
        CapabilityExposure.OPERATOR,
        "Call one specific waiting queue entry with a closed audited reason.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "queue.recall_hold",
        CapabilityExposure.OPERATOR,
        "Temporarily gate one waiting queue entry behind a closed recall condition.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "queue.skip",
        CapabilityExposure.OPERATOR,
        "Defer the current eligible FIFO head for exactly one later selection.",
        revision=RevisionPolicy.REQUIRED,
    ),
)
