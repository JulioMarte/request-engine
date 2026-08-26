from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)

LIVE_CAPACITY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "live_capacity.read",
        CapabilityExposure.OPERATOR,
        "Read one staff live-capacity projection for a configured ServiceQueue scope.",
    ),
    query_capability(
        "live_capacity.customer_read",
        CapabilityExposure.PUBLIC,
        "Read one privacy-safe live-capacity estimate for an authorized queue subject.",
        party_scope="queue.manage",
        override_capability="queue.subject_override",
    ),
    query_capability(
        "live_capacity.evaluate_intake",
        CapabilityExposure.OPERATOR,
        "Evaluate whether one additional known workload fits the current live-capacity scope.",
    ),
    command_capability(
        "live_capacity.configure_scope",
        CapabilityExposure.OPERATOR,
        "Create or revise one ServiceQueue to Resource and Location projection scope.",
        revision=RevisionPolicy.SERVER_SELECTED,
    ),
    command_capability(
        "live_capacity.configure_estimate",
        CapabilityExposure.OPERATOR,
        "Create or revise explicit workload-duration estimate policy.",
        revision=RevisionPolicy.SERVER_SELECTED,
    ),
)
