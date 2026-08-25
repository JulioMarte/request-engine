from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)

LIVE_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
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
        "Read the privacy-controlled staff live queue projection.",
    ),
    command_capability(
        "queue.subject_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on queue subjects without delegated Party authority.",
        runtime_available=False,
    ),
    command_capability(
        "service_session.start",
        CapabilityExposure.OPERATOR,
        "Start actual service for one called QueueEntry on the actual Resource and Location.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "service_session.pause",
        CapabilityExposure.OPERATOR,
        "Pause an active ServiceSession and persist one interruption.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "service_session.resume",
        CapabilityExposure.OPERATOR,
        "Resume a paused ServiceSession by closing its exact open interruption.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "service_session.complete",
        CapabilityExposure.OPERATOR,
        "Complete actual service and its QueueEntry atomically.",
        revision=RevisionPolicy.REQUIRED,
    ),
    query_capability(
        "service_session.read",
        CapabilityExposure.OPERATOR,
        "Read actual service execution status and durable interruption duration.",
    ),
    command_capability(
        "resource_activity.start",
        CapabilityExposure.OPERATOR,
        "Start non-patient operational occupation of one Resource.",
    ),
    command_capability(
        "resource_activity.end",
        CapabilityExposure.OPERATOR,
        "End one open ResourceActivity.",
        revision=RevisionPolicy.REQUIRED,
    ),
    query_capability(
        "workload.list",
        CapabilityExposure.OPERATOR,
        "List active operational workload classifications used by live service.",
    ),
)
