from request_engine.platform.security.capabilities import (
    CAPABILITIES,
    CapabilityExposure,
    CapabilityKind,
    IdempotencyPolicy,
    RevisionPolicy,
)

NETWORK_RETRYABLE_RUNTIME_COMMANDS = frozenset(
    {
        "appointments.book",
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm_attendance",
        "queue.join",
        "queue.leave",
        "queue.call_next",
        "waitlist.join",
        "waitlist.leave",
        "waitlist.accept_offer",
        "waitlist.decline_offer",
        "reminders.create_plan",
        "reminders.cancel_plan",
        "requests.submit",
        "requests.cancel",
    }
)

CALLER_SELECTED_REVISION_COMMANDS = frozenset(
    {
        "appointments.cancel",
        "appointments.reschedule",
        "appointments.confirm_attendance",
        "queue.leave",
        "waitlist.leave",
        "waitlist.accept_offer",
        "waitlist.decline_offer",
        "reminders.cancel_plan",
        "requests.cancel",
    }
)


def test_network_retryable_runtime_command_inventory_is_explicit_and_complete() -> None:
    actual = {
        definition.key
        for definition in CAPABILITIES
        if definition.kind is CapabilityKind.COMMAND
        and definition.runtime_available
        and definition.exposure is not CapabilityExposure.INTERNAL
    }
    assert actual == NETWORK_RETRYABLE_RUNTIME_COMMANDS
    by_key = {definition.key: definition for definition in CAPABILITIES}
    for key in NETWORK_RETRYABLE_RUNTIME_COMMANDS:
        assert by_key[key].idempotency is IdempotencyPolicy.REQUIRED


def test_caller_selected_revision_command_inventory_is_explicit_and_complete() -> None:
    actual = {
        definition.key
        for definition in CAPABILITIES
        if definition.kind is CapabilityKind.COMMAND
        and definition.runtime_available
        and definition.exposure is not CapabilityExposure.INTERNAL
        and definition.revision is RevisionPolicy.REQUIRED
    }
    assert actual == CALLER_SELECTED_REVISION_COMMANDS

    by_key = {definition.key: definition for definition in CAPABILITIES}
    assert by_key["queue.call_next"].revision is RevisionPolicy.SERVER_SELECTED
    assert "queue.call_next" not in CALLER_SELECTED_REVISION_COMMANDS
