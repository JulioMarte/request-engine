from dataclasses import dataclass
from enum import StrEnum


class CapabilityExposure(StrEnum):
    PUBLIC = "public"
    OPERATOR = "operator"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    key: str
    exposure: CapabilityExposure
    description: str
    party_scope: str | None = None
    override_capability: str | None = None
    legacy_aliases: frozenset[str] = frozenset()


# Capability keys are a public contract. Additions are cheap; renames/removals require an
# explicit compatibility decision. Party authority is deliberately metadata on top of a
# technical capability grant: possessing a capability never implies authority over a Party.
CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    CapabilityDefinition(
        key="business.get_info",
        exposure=CapabilityExposure.PUBLIC,
        description="Read structured public/operational business information.",
        legacy_aliases=frozenset({"business.read"}),
    ),
    CapabilityDefinition(
        key="catalog.search_offerings",
        exposure=CapabilityExposure.PUBLIC,
        description="Search the tenant offering catalog.",
        legacy_aliases=frozenset({"catalog.read"}),
    ),
    CapabilityDefinition(
        key="catalog.get_offering_details",
        exposure=CapabilityExposure.PUBLIC,
        description="Read one offering and its exposed version details.",
        legacy_aliases=frozenset({"catalog.read"}),
    ),
    CapabilityDefinition(
        key="appointments.find_slots",
        exposure=CapabilityExposure.PUBLIC,
        description="Find appointment slots without committing capacity.",
        legacy_aliases=frozenset({"booking.find_slots"}),
    ),
    CapabilityDefinition(
        key="appointments.book",
        exposure=CapabilityExposure.PUBLIC,
        description="Book an appointment for an authorized subject Party.",
        party_scope="appointments.book",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.book_appointment"}),
    ),
    CapabilityDefinition(
        key="appointments.read",
        exposure=CapabilityExposure.PUBLIC,
        description="Read an appointment for an authorized subject Party.",
        party_scope="appointments.manage",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.read"}),
    ),
    CapabilityDefinition(
        key="appointments.cancel",
        exposure=CapabilityExposure.PUBLIC,
        description="Cancel an appointment for an authorized subject Party.",
        party_scope="appointments.manage",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.cancel_reservation"}),
    ),
    CapabilityDefinition(
        key="appointments.reschedule",
        exposure=CapabilityExposure.PUBLIC,
        description="Reschedule an appointment for an authorized subject Party.",
        party_scope="appointments.manage",
        override_capability="appointments.subject_override",
        legacy_aliases=frozenset({"booking.reschedule_reservation"}),
    ),
    CapabilityDefinition(
        key="appointments.subject_override",
        exposure=CapabilityExposure.OPERATOR,
        description="Operate on appointment subjects without delegated Party authority.",
        legacy_aliases=frozenset({"booking.subject_override"}),
    ),
    CapabilityDefinition(
        key="queue.list",
        exposure=CapabilityExposure.PUBLIC,
        description="List active service queues.",
        legacy_aliases=frozenset({"queue.read"}),
    ),
    CapabilityDefinition(
        key="queue.join",
        exposure=CapabilityExposure.PUBLIC,
        description="Join a service queue for an authorized subject Party.",
        party_scope="queue.join",
        override_capability="queue.subject_override",
    ),
    CapabilityDefinition(
        key="queue.status",
        exposure=CapabilityExposure.PUBLIC,
        description="Read queue status for an authorized subject Party.",
        party_scope="queue.manage",
        override_capability="queue.subject_override",
        legacy_aliases=frozenset({"queue.read"}),
    ),
    CapabilityDefinition(
        key="queue.leave",
        exposure=CapabilityExposure.PUBLIC,
        description="Leave a service queue for an authorized subject Party.",
        party_scope="queue.manage",
        override_capability="queue.subject_override",
    ),
    CapabilityDefinition(
        key="queue.call_next",
        exposure=CapabilityExposure.OPERATOR,
        description="Advance a service queue by calling the deterministic next entry.",
    ),
    CapabilityDefinition(
        key="queue.subject_override",
        exposure=CapabilityExposure.OPERATOR,
        description="Operate on queue subjects without delegated Party authority.",
    ),
    CapabilityDefinition(
        key="requests.submit",
        exposure=CapabilityExposure.PUBLIC,
        description="Submit durable business demand.",
        party_scope="requests.submit",
        override_capability="requests.party_override",
    ),
    CapabilityDefinition(
        key="requests.read",
        exposure=CapabilityExposure.PUBLIC,
        description="Read a Request for its authorized requester Party.",
        party_scope="requests.manage",
        override_capability="requests.party_override",
    ),
    CapabilityDefinition(
        key="requests.cancel",
        exposure=CapabilityExposure.PUBLIC,
        description="Cancel a Request for its authorized requester Party.",
        party_scope="requests.manage",
        override_capability="requests.party_override",
    ),
    CapabilityDefinition(
        key="requests.record_result",
        exposure=CapabilityExposure.INTERNAL,
        description="Record a validated result while processing a Request.",
    ),
    CapabilityDefinition(
        key="requests.complete",
        exposure=CapabilityExposure.INTERNAL,
        description="Complete Request processing.",
    ),
    CapabilityDefinition(
        key="requests.fail",
        exposure=CapabilityExposure.INTERNAL,
        description="Fail Request processing with a classified error.",
    ),
    CapabilityDefinition(
        key="requests.party_override",
        exposure=CapabilityExposure.OPERATOR,
        description="Operate on Requests without requester Party authority.",
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
