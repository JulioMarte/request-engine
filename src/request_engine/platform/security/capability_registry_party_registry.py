from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
    query_capability,
)

PARTY_REGISTRY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "organization.bootstrap",
        CapabilityExposure.OPERATOR,
        (
            "Establish the initial principal's delegated operational authority "
            "over the tenant business Party."
        ),
    ),
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
    command_capability(
        "identity_exchange.publish",
        CapabilityExposure.OPERATOR,
        "Publish a consented portable identity snapshot for an operator-witnessed Party.",
    ),
    command_capability(
        "identity_exchange.match",
        CapabilityExposure.OPERATOR,
        "Resolve an operator-witnessed cédula to an opaque portable identity candidate.",
    ),
    command_capability(
        "identity_exchange.adopt",
        CapabilityExposure.OPERATOR,
        "Adopt a consented portable identity into a new tenant-owned Party.",
    ),
    query_capability(
        "parties.lookup",
        CapabilityExposure.PUBLIC,
        "Look up Parties by phone, identity document or display-name prefix.",
    ),
    query_capability(
        "parties.lookup_administrative_identifier",
        CapabilityExposure.PUBLIC,
        "Read and resolve tenant-owned Party administrative identifiers.",
    ),
    query_capability(
        "parties.read_revisions",
        CapabilityExposure.PUBLIC,
        "Read the append-only identity revision ledger of a person Party.",
    ),
)
