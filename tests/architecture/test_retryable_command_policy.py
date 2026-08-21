from request_engine.platform.security.capabilities import (
    CAPABILITIES,
    CapabilityDefinition,
    CapabilityExposure,
    CapabilityKind,
    IdempotencyPolicy,
    RevisionPolicy,
)

# These commands are current compatibility minima whose optimistic revision must
# remain caller-selected. The set is deliberately not an exhaustive snapshot: a
# future command may adopt caller-selected revision after an explicit contract
# decision without editing an equality inventory merely to become visible.
REQUIRED_CALLER_SELECTED_REVISION_COMMANDS = frozenset(
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


def _external_runtime_commands() -> list[CapabilityDefinition]:
    return [
        definition
        for definition in CAPABILITIES
        if definition.kind is CapabilityKind.COMMAND
        and definition.runtime_available
        and definition.exposure is not CapabilityExposure.INTERNAL
    ]


def test_every_external_runtime_command_requires_idempotency() -> None:
    commands = _external_runtime_commands()
    assert commands
    for definition in commands:
        assert definition.idempotency is IdempotencyPolicy.REQUIRED


def test_required_caller_selected_revision_contract_remains_supported() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    for key in REQUIRED_CALLER_SELECTED_REVISION_COMMANDS:
        assert by_key[key].revision is RevisionPolicy.REQUIRED


def test_server_selected_revision_is_explicit_for_queue_call_next() -> None:
    by_key = {definition.key: definition for definition in CAPABILITIES}
    assert by_key["queue.call_next"].revision is RevisionPolicy.SERVER_SELECTED
