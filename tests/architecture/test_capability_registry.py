from uuid import uuid4

from request_engine.platform.security.capabilities import (
    CAPABILITIES,
    CapabilityExposure,
    IdempotencyPolicy,
    canonical_capability_keys,
)
from request_engine.platform.security.context import ActorContext


def test_capability_registry_has_unique_canonical_keys_and_unambiguous_aliases() -> None:
    canonical = [definition.key for definition in CAPABILITIES]
    assert len(canonical) == len(set(canonical))

    aliases: dict[str, set[str]] = {}
    for definition in CAPABILITIES:
        assert definition.key not in definition.legacy_aliases
        for alias in definition.legacy_aliases:
            aliases.setdefault(alias, set()).add(definition.key)

    assert not (set(aliases) & set(canonical))
    assert {alias: targets for alias, targets in aliases.items() if len(targets) > 1} == {
        "catalog.read": {
            "catalog.get_offering_details",
            "catalog.search_offerings",
        },
        "queue.read": {"queue.list", "queue.status"},
    }


def test_party_authority_metadata_points_to_operator_override_capabilities() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    for definition in CAPABILITIES:
        if definition.party_scope is None:
            continue
        assert definition.exposure is CapabilityExposure.PUBLIC
        assert definition.override_capability is not None
        override = by_key[definition.override_capability]
        assert override.exposure is CapabilityExposure.OPERATOR
        assert override.party_scope is None


def test_internal_processing_is_not_public_capability_surface() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    for key in (
        "requests.record_result",
        "requests.complete",
        "requests.fail",
        "waitlist.create_opportunity",
    ):
        assert by_key[key].exposure is CapabilityExposure.INTERNAL
        assert by_key[key].party_scope is None


def test_operational_recovery_is_operator_only_and_commands_are_idempotent() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    assert by_key["operational_recovery.read"].exposure is CapabilityExposure.OPERATOR
    for key in ("operational_recovery.propose", "operational_recovery.execute"):
        assert by_key[key].exposure is CapabilityExposure.OPERATOR
        assert by_key[key].idempotency is IdempotencyPolicy.REQUIRED


def test_actor_context_accepts_registered_legacy_grants_without_exposing_new_aliases() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset(
            {
                "booking.book_appointment",
                "booking.read",
                "business.read",
                "catalog.read",
                "queue.read",
            }
        ),
    )

    assert actor.allows("appointments.book")
    assert actor.allows("appointments.read")
    assert actor.allows("business.get_info")
    assert actor.allows("catalog.search_offerings")
    assert actor.allows("catalog.get_offering_details")
    assert actor.allows("queue.list")
    assert actor.allows("queue.status")
    assert not actor.allows("appointments.cancel")


def test_canonical_registry_contains_expected_current_surface() -> None:
    assert {
        "business.get_info",
        "catalog.search_offerings",
        "catalog.get_offering_details",
        "appointments.find_slots",
        "appointments.book",
        "appointments.read",
        "appointments.cancel",
        "appointments.reschedule",
        "queue.list",
        "queue.join",
        "queue.status",
        "queue.leave",
        "waitlist.join",
        "waitlist.read",
        "waitlist.leave",
        "requests.submit",
        "requests.read",
        "requests.cancel",
        "operational_recovery.read",
        "operational_recovery.propose",
        "operational_recovery.execute",
    } <= canonical_capability_keys()
