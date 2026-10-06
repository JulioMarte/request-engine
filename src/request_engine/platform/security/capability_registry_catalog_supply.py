from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
    query_capability,
)

CATALOG_SUPPLY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    query_capability(
        "catalog.read_configuration",
        CapabilityExposure.OPERATOR,
        "Read tenant capability vocabulary and exact-version Offering configuration/revisions.",
    ),
    command_capability(
        "catalog.manage",
        CapabilityExposure.OPERATOR,
        (
            "Manage tenant Catalog configuration, including Locations, service/capability "
            "configuration, Offerings, operational hours, contacts, holidays and booking terms."
        ),
    ),
)
