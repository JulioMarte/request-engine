from dataclasses import dataclass
from enum import StrEnum


class CapabilityExposure(StrEnum):
    PUBLIC = "public"
    OPERATOR = "operator"
    INTERNAL = "internal"


class CapabilityKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"


class IdempotencyPolicy(StrEnum):
    NONE = "none"
    REQUIRED = "required"


class RevisionPolicy(StrEnum):
    NONE = "none"
    REQUIRED = "required"
    SERVER_SELECTED = "server_selected"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    key: str
    exposure: CapabilityExposure
    description: str
    kind: CapabilityKind
    idempotency: IdempotencyPolicy
    revision: RevisionPolicy
    schema_version: int = 1
    party_scope: str | None = None
    override_capability: str | None = None
    legacy_aliases: frozenset[str] = frozenset()
    runtime_available: bool = True

    @property
    def discoverable(self) -> bool:
        return self.exposure is not CapabilityExposure.INTERNAL


def _query(
    key: str,
    exposure: CapabilityExposure,
    description: str,
    *,
    party_scope: str | None = None,
    override_capability: str | None = None,
    legacy_aliases: frozenset[str] = frozenset(),
    runtime_available: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        exposure=exposure,
        description=description,
        kind=CapabilityKind.QUERY,
        idempotency=IdempotencyPolicy.NONE,
        revision=RevisionPolicy.NONE,
        party_scope=party_scope,
        override_capability=override_capability,
        legacy_aliases=legacy_aliases,
        runtime_available=runtime_available,
    )


def _command(
    key: str,
    exposure: CapabilityExposure,
    description: str,
    *,
    revision: RevisionPolicy = RevisionPolicy.NONE,
    party_scope: str | None = None,
    override_capability: str | None = None,
    legacy_aliases: frozenset[str] = frozenset(),
    runtime_available: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        exposure=exposure,
        description=description,
        kind=CapabilityKind.COMMAND,
        idempotency=IdempotencyPolicy.REQUIRED,
        revision=revision,
        party_scope=party_scope,
        override_capability=override_capability,
        legacy_aliases=legacy_aliases,
        runtime_available=runtime_available,
    )


# This registry is the executable machine-facing product contract. HTTP, discovery,
# OpenAPI fitness tests and future tool-schema adapters consume the same definitions.
CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    _query(
        "business.get_info",
        CapabilityExposure.PUBLIC,
        "Read structured public/operational business information.",
        legacy_aliases=frozenset({"business.read"}),
        runtime_available=False,
    ),
    _query(
        "catalog.search_offerings",
        CapabilityExposure.PUBLIC,
        "Search the tenant offering catalog.",
        legacy_aliases=frozenset({"catalog.read"}),
    ),
    _query(
        "catalog.get_offering_details",
        CapabilityExposure.PUBLIC,
        "Read one offering and its exposed version details.",
        legacy_aliases=frozenset({"catalog.read"}),
    ),
    _query(
        "appointments.find_slots",
        CapabilityExposure.PUBLIC,
        "Find appointment slots without committing capacity.",
        legacy_aliases=frozenset({"booking.find_slots"}),
    ),
    _command(
        "appointments.book",
        CapabilityExposure.PUBLIC,
        "Book an appointment for an authorized subject Party.",
        party_scope="appointments.book",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.book_appointment"}),
    ),
    _query(
        "appointments.read",
        CapabilityExposure.PUBLIC,
        "Read an appointment for an authorized subject Party.",
        party_scope="appointments.manage",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.read"}),
    ),
    _command(
        "appointments.cancel",
        CapabilityExposure.PUBLIC,
        "Cancel an appointment for an authorized subject Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="appointments.manage",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.cancel_reservation"}),
    ),
    _command(
        "appointments.reschedule",
        CapabilityExposure.PUBLIC,
        "Reschedule an appointment for an authorized subject Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="appointments.manage",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.reschedule_reservation"}),
    ),
    _command(
        "appointments.subject_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on appointment subjects without delegated Party authority.",
        legacy_aliases=frozenset({"booking.subject_override"}),
        runtime_available=False,
    ),
    _query(
        "queue.list",
        CapabilityExposure.PUBLIC,
        "List active service queues.",
        legacy_aliases=frozenset({"queue.read"}),
    ),
    _command(
        "queue.join",
        CapabilityExposure.PUBLIC,
        "Join a service queue for an authorized subject Party.",
        party_scope="queue.join",
        override_capability="queue.subject_override",
    ),
    _query(
        "queue.status",
        CapabilityExposure.PUBLIC,
        "Read queue status for an authorized subject Party.",
        party_scope="queue.manage",
        override_capability="queue.subject_override",
        legacy_aliases=frozenset({"queue.read"}),
    ),
    _command(
        "queue.leave",
        CapabilityExposure.PUBLIC,
        "Leave a service queue for an authorized subject Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="queue.manage",
        override_capability="queue.subject_override",
    ),
    _command(
        "queue.call_next",
        CapabilityExposure.OPERATOR,
        "Advance a service queue by calling the deterministic next entry.",
        revision=RevisionPolicy.SERVER_SELECTED,
    ),
    _command(
        "queue.subject_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on queue subjects without delegated Party authority.",
        runtime_available=False,
    ),
    _command(
        "waitlist.join",
        CapabilityExposure.PUBLIC,
        "Join an Offering waitlist for an authorized subject Party.",
        party_scope="waitlist.join",
        override_capability="waitlist.subject_override",
    ),
    _query(
        "waitlist.read",
        CapabilityExposure.PUBLIC,
        "Read a waitlist entry for an authorized subject Party.",
        party_scope="waitlist.manage",
        override_capability="waitlist.subject_override",
    ),
    _command(
        "waitlist.leave",
        CapabilityExposure.PUBLIC,
        "Cancel an active waitlist entry for an authorized subject Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="waitlist.manage",
        override_capability="waitlist.subject_override",
    ),
    _command(
        "waitlist.subject_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on waitlist subjects without delegated Party authority.",
        runtime_available=False,
    ),
    _command(
        "waitlist.create_opportunity",
        CapabilityExposure.INTERNAL,
        "Create a deduplicated slot opportunity from a capacity-release event.",
    ),
    _command(
        "requests.submit",
        CapabilityExposure.PUBLIC,
        "Submit durable business demand.",
        party_scope="requests.submit",
        override_capability="requests.party_override",
    ),
    _query(
        "requests.read",
        CapabilityExposure.PUBLIC,
        "Read a Request for its authorized requester Party.",
        party_scope="requests.manage",
        override_capability="requests.party_override",
    ),
    _command(
        "requests.cancel",
        CapabilityExposure.PUBLIC,
        "Cancel a Request for its authorized requester Party.",
        revision=RevisionPolicy.REQUIRED,
        party_scope="requests.manage",
        override_capability="requests.party_override",
    ),
    _command(
        "requests.record_result",
        CapabilityExposure.INTERNAL,
        "Record a validated result while processing a Request.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _command(
        "requests.complete",
        CapabilityExposure.INTERNAL,
        "Complete Request processing.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _command(
        "requests.fail",
        CapabilityExposure.INTERNAL,
        "Fail Request processing with a classified error.",
        revision=RevisionPolicy.REQUIRED,
    ),
    _command(
        "requests.party_override",
        CapabilityExposure.OPERATOR,
        "Permission to operate on Requests without requester Party authority.",
        runtime_available=False,
    ),
)

CAPABILITY_BY_KEY = {definition.key: definition for definition in CAPABILITIES}


def capability_definition(key: str) -> CapabilityDefinition | None:
    return CAPABILITY_BY_KEY.get(key)


def capability_is_known(key: str) -> bool:
    if key in CAPABILITY_BY_KEY:
        return True
    return any(key in definition.legacy_aliases for definition in CAPABILITIES)


def grant_satisfies(granted_key: str, required_key: str) -> bool:
    """Return whether one materialized grant satisfies one canonical requirement."""

    if granted_key == required_key:
        return True
    definition = CAPABILITY_BY_KEY.get(required_key)
    return definition is not None and granted_key in definition.legacy_aliases


def canonical_capability_keys() -> frozenset[str]:
    return frozenset(CAPABILITY_BY_KEY)
