from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    command_capability,
)

CATALOG_SUPPLY_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    command_capability(
        "catalog.manage",
        CapabilityExposure.OPERATOR,
        (
            "Manage tenant Catalog configuration, including Locations, service/capability "
            "configuration, Offerings, operational hours, contacts, holidays and booking terms."
        ),
    ),
)
