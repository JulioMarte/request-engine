from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
)

STAFF_CONTACT_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "staff.manage_own_admin_contact",
        CapabilityExposure.PUBLIC,
        "Register the staff principal's own administrative contact and request"
        " its one-time verification code.",
    ),
    command_capability(
        "staff.confirm_own_admin_contact",
        CapabilityExposure.PUBLIC,
        "Confirm the staff principal's own administrative contact with the"
        " one-time verification code.",
    ),
)
