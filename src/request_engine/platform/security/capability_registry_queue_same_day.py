from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
)

SAME_DAY_QUEUE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "queue.operator_select",
        CapabilityExposure.OPERATOR,
        "Call a specific waiting QueueEntry under the ServiceQueue serialization lock.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "queue.recall_hold",
        CapabilityExposure.OPERATOR,
        "Temporarily make a waiting QueueEntry non-callable without changing FIFO position.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "queue.release_recall_hold",
        CapabilityExposure.OPERATOR,
        "Release the exact active recall hold observed by an operator.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "queue.skip",
        CapabilityExposure.OPERATOR,
        "Defer the current eligible FIFO head for one selection only.",
        revision=RevisionPolicy.SERVER_SELECTED,
    ),
)
