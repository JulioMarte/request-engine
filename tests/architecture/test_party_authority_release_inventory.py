from request_engine.platform.security.capabilities import CAPABILITIES


EXPECTED_PARTY_AUTHORITY_SURFACE = {
    "appointments.book": ("appointments.book", "appointments.subject_override"),
    "appointments.read": ("appointments.manage", "appointments.subject_override"),
    "appointments.cancel": ("appointments.manage", "appointments.subject_override"),
    "appointments.reschedule": ("appointments.manage", "appointments.subject_override"),
    "appointments.confirm_attendance": (
        "appointments.manage",
        "appointments.subject_override",
    ),
    "queue.join": ("queue.join", "queue.subject_override"),
    "queue.status": ("queue.manage", "queue.subject_override"),
    "queue.leave": ("queue.manage", "queue.subject_override"),
    "waitlist.join": ("waitlist.join", "waitlist.subject_override"),
    "waitlist.read": ("waitlist.manage", "waitlist.subject_override"),
    "waitlist.leave": ("waitlist.manage", "waitlist.subject_override"),
    "waitlist.accept_offer": ("waitlist.manage", "waitlist.subject_override"),
    "waitlist.decline_offer": ("waitlist.manage", "waitlist.subject_override"),
    "reminders.create_plan": ("reminders.manage", "reminders.subject_override"),
    "reminders.read": ("reminders.manage", "reminders.subject_override"),
    "reminders.cancel_plan": ("reminders.manage", "reminders.subject_override"),
    "requests.submit": ("requests.submit", "requests.party_override"),
    "requests.read": ("requests.manage", "requests.party_override"),
    "requests.cancel": ("requests.manage", "requests.party_override"),
}


def test_runtime_party_authority_surface_matches_release_inventory() -> None:
    actual = {
        definition.key: (definition.party_scope, definition.override_capability)
        for definition in CAPABILITIES
        if definition.runtime_available and definition.party_scope is not None
    }
    assert actual == EXPECTED_PARTY_AUTHORITY_SURFACE


def test_party_scoped_runtime_capabilities_have_explicit_override_permissions() -> None:
    for definition in CAPABILITIES:
        if not definition.runtime_available or definition.party_scope is None:
            continue
        assert definition.override_capability is not None
        override = next(
            item for item in CAPABILITIES if item.key == definition.override_capability
        )
        assert override.runtime_available is False
        assert override.party_scope is None
