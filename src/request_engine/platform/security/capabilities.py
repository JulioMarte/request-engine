from request_engine.platform.security.capability_registry_foundation import FOUNDATION_CAPABILITIES
from request_engine.platform.security.capability_registry_front_desk import FRONT_DESK_CAPABILITIES
from request_engine.platform.security.capability_registry_live import LIVE_CAPABILITIES
from request_engine.platform.security.capability_registry_requests import REQUEST_CAPABILITIES
from request_engine.platform.security.capability_registry_waitlist import (
    WAITLIST_REMINDER_CAPABILITIES,
)
from request_engine.platform.security.capability_types import (
    CapabilityDefinition,
    CapabilityExposure,
    CapabilityKind,
    IdempotencyPolicy,
    RevisionPolicy,
)

CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    FOUNDATION_CAPABILITIES
    + FRONT_DESK_CAPABILITIES
    + LIVE_CAPABILITIES
    + WAITLIST_REMINDER_CAPABILITIES
    + REQUEST_CAPABILITIES
)
CAPABILITY_BY_KEY = {definition.key: definition for definition in CAPABILITIES}


def capability_definition(key: str) -> CapabilityDefinition | None:
    return CAPABILITY_BY_KEY.get(key)


def capability_is_known(key: str) -> bool:
    if key in CAPABILITY_BY_KEY:
        return True
    return any(key in definition.legacy_aliases for definition in CAPABILITIES)


def grant_satisfies(granted_key: str, required_key: str) -> bool:
    if granted_key == required_key:
        return True
    definition = CAPABILITY_BY_KEY.get(required_key)
    return definition is not None and granted_key in definition.legacy_aliases


def canonical_capability_keys() -> frozenset[str]:
    return frozenset(CAPABILITY_BY_KEY)


__all__ = [
    "CAPABILITIES",
    "CapabilityDefinition",
    "CapabilityExposure",
    "CapabilityKind",
    "IdempotencyPolicy",
    "RevisionPolicy",
    "canonical_capability_keys",
    "capability_definition",
    "capability_is_known",
    "grant_satisfies",
]
