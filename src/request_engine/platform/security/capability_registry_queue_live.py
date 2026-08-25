from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)

LIVE_QUEUE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "queue.list",
        CapabilityExposure.PUBLIC,
        "List active service queues.",
        legacy_aliases=frozenset({"queue.read"}),
    ),
    command_capability(
        "queue.join",
        CapabilityExposure.PUBLIC,
        "Join a service queue for an authorized subject Party.",
        party_scope="queue.join",
        override_capability="queue.subject_override",
    ),
    query_capability(
        "queue.status",
        CapabilityExposure.PUBLIC,
        "Read queue status for an authorized subject Party.",
        party_scope="queue.manage",
        override_capability="queue.subject_override",
        legacy_aliases=frozenset({"queue.read"}),
    ),
    command_capability(
        "queue.leave",
        CapabilityExposure.PUBLIC,
        "Leave a service queue for an authorized subject Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="queue.manage",
        override_capability="queue.subject_override",
    ),
    command_capability(
        "queue.call_next",
        CapabilityExposure.OPERATOR,
        "Advance a service queue by calling the deterministic next entry.",
        revision=RevisionPolicy.SERVER_SELECTED,
    ),
    command_capability(
        "queue.check_in",
        CapabilityExposure.OPERATOR,
        "Check in a reservation-backed subject or admit a walk-in to a live queue.",
    ),
    command_capability(
        "queue.classify_expected_workload",
        CapabilityExposure.OPERATOR,
        "Assign, correct, or clear expected workload while a QueueEntry is waiting or called.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "queue.mark_no_show",
        CapabilityExposure.OPERATOR,
        "Mark one called QueueEntry as no-show without fabricating service execution.",
        revision=RevisionPolicy.REQUIRED,
    ),
    query_capability(
        "queue.staff_read",
        CapabilityExposure.OPERATOR,
        "Read live queue state and bounded terminal queue history for staff operations.",
    ),
    command_capability(
        "queue.subject_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on queue subjects without delegated Party authority.",
        runtime_available=False,
    ),
    query_capability(
        "workload.list",
        CapabilityExposure.OPERATOR,
        "List active operational workload classifications used by live service.",
    ),
    command_capability(
        "workload.manage",
        CapabilityExposure.OPERATOR,
        "Create, rename, and deactivate tenant operational workload classifications.",
        revision=RevisionPolicy.OPTIONAL,
    ),
)
