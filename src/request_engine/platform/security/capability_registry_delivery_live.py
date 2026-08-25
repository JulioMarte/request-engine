from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)

LIVE_DELIVERY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
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
        "Read service state, interruption history, and factual elapsed durations.",
    ),
    query_capability(
        "resource_activity.read",
        CapabilityExposure.OPERATOR,
        "Reconstruct current or historical non-service occupation for one Resource.",
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
)
