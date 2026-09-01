from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
    query_capability,
)

PARTY_REGISTRY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "parties.register",
        CapabilityExposure.PUBLIC,
        "Register a person with contact points and identity documents.",
    ),
    command_capability(
        "parties.add_contact_point",
        CapabilityExposure.PUBLIC,
        "Add a contact point to an existing person Party.",
    ),
    command_capability(
        "parties.confirm_contact_point",
        CapabilityExposure.PUBLIC,
        "Confirm an unverified Party contact point as verified.",
    ),
    query_capability(
        "parties.lookup",
        CapabilityExposure.PUBLIC,
        "Look up Parties by phone, identity document or display-name prefix.",
    ),
)
