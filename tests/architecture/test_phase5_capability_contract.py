import asyncio
from uuid import uuid4

from request_engine.platform.security.capabilities import (
    CAPABILITIES,
    CapabilityExposure,
    CapabilityKind,
    IdempotencyPolicy,
    RevisionPolicy,
)
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.discovery import (
    BaselineTenantCapabilityPolicy,
    discover_capabilities,
)


def test_every_discoverable_command_declares_network_idempotency() -> None:
    for definition in CAPABILITIES:
        if not definition.discoverable or definition.kind is not CapabilityKind.COMMAND:
            continue
        assert definition.idempotency is IdempotencyPolicy.REQUIRED, definition.key


def test_queries_never_require_idempotency_or_expected_revision() -> None:
    for definition in CAPABILITIES:
        if definition.kind is not CapabilityKind.QUERY:
            continue
        assert definition.idempotency is IdempotencyPolicy.NONE, definition.key
        assert definition.revision is RevisionPolicy.NONE, definition.key


def test_caller_selected_mutations_declare_expected_revision() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    for key in (
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm_attendance",
        "queue.leave",
        "waitlist.leave",
        "waitlist.accept_offer",
        "waitlist.decline_offer",
        "reminders.cancel_plan",
        "requests.cancel",
        "requests.record_result",
        "requests.complete",
        "requests.fail",
    ):
        assert by_key[key].revision is RevisionPolicy.REQUIRED

    assert by_key["queue.call_next"].revision is RevisionPolicy.SERVER_SELECTED
    assert by_key["appointments.book"].revision is RevisionPolicy.NONE
    assert by_key["queue.join"].revision is RevisionPolicy.NONE
    assert by_key["waitlist.join"].revision is RevisionPolicy.NONE
    assert by_key["reminders.create_plan"].revision is RevisionPolicy.NONE
    assert by_key["requests.submit"].revision is RevisionPolicy.NONE


def test_discovery_hides_internal_and_ungranted_operator_capabilities() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"appointments.find_slots", "appointments.book"}),
    )

    discovered = asyncio.run(discover_capabilities(actor, BaselineTenantCapabilityPolicy()))
    by_key = {item.definition.key: item for item in discovered}

    assert "requests.complete" not in by_key
    assert "queue.call_next" not in by_key
    assert by_key["appointments.find_slots"].actor_granted is True
    assert by_key["appointments.book"].actor_granted is True
    assert by_key["appointments.cancel"].actor_granted is False
    assert by_key["appointments.cancel"].tenant_enabled is True
    assert not hasattr(by_key["appointments.cancel"], "context_executable")


def test_discovery_shows_only_granted_operator_capabilities() -> None:
    actor = ActorContext(
        organization_id=uuid4(),
        principal_id=uuid4(),
        capabilities=frozenset({"queue.call_next"}),
    )

    discovered = asyncio.run(discover_capabilities(actor, BaselineTenantCapabilityPolicy()))
    operator_keys = {
        item.definition.key
        for item in discovered
        if item.definition.exposure is CapabilityExposure.OPERATOR
    }
    assert operator_keys == {"queue.call_next"}


def test_permission_only_capabilities_are_not_claimed_as_runtime_operations() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    for key in (
        "appointments.subject_override",
        "queue.subject_override",
        "waitlist.subject_override",
        "reminders.subject_override",
        "requests.party_override",
    ):
        assert by_key[key].runtime_available is False
