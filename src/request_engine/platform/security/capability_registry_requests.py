from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    RevisionPolicy,
    command_capability,
    query_capability,
)

REQUEST_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "requests.submit",
        CapabilityExposure.PUBLIC,
        "Submit durable business demand.",
        party_scope="requests.submit",
        override_capability="requests.party_override",
    ),
    query_capability(
        "requests.read",
        CapabilityExposure.PUBLIC,
        "Read a Request for its authorized requester Party.",
        party_scope="requests.manage",
        override_capability="requests.party_override",
    ),
    command_capability(
        "requests.cancel",
        CapabilityExposure.PUBLIC,
        "Cancel a Request for its authorized requester Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="requests.manage",
        override_capability="requests.party_override",
    ),
    command_capability(
        "requests.record_result",
        CapabilityExposure.INTERNAL,
        "Record a validated result while processing a Request.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "requests.complete",
        CapabilityExposure.INTERNAL,
        "Complete Request processing.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "requests.fail",
        CapabilityExposure.INTERNAL,
        "Fail Request processing with a classified error.",
        revision=RevisionPolicy.REQUIRED,
    ),
    command_capability(
        "requests.party_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on Requests without requester Party authority.",
        runtime_available=False,
    ),
)
