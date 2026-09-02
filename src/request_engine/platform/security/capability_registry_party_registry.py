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
    command_capability(
        "parties.add_administrative_identifier",
        CapabilityExposure.PUBLIC,
        "Add a tenant-owned third-party administrative identifier to a Party.",
    ),
    command_capability(
        "parties.rename",
        CapabilityExposure.PUBLIC,
        "Correct the display name of a person Party.",
    ),
    command_capability(
        "parties.add_document",
        CapabilityExposure.PUBLIC,
        "Add an identity document to an existing person Party.",
    ),
    command_capability(
        "parties.deactivate_contact_point",
        CapabilityExposure.PUBLIC,
        "Deactivate one Party contact point; verification is untouched.",
    ),
    command_capability(
        "parties.deactivate",
        CapabilityExposure.PUBLIC,
        "Deactivate a person Party so lookups no longer return it.",
    ),
    command_capability(
        "parties.rollback_identity",
        CapabilityExposure.PUBLIC,
        "Restore a person Party's identity from a prior recorded revision.",
    ),
    query_capability(
        "parties.lookup",
        CapabilityExposure.PUBLIC,
        "Look up Parties by phone, identity document or display-name prefix.",
    ),
    query_capability(
        "parties.read_revisions",
        CapabilityExposure.PUBLIC,
        "Read the append-only identity revision ledger of a person Party.",
    ),
)
