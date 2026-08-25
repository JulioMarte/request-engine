from dataclasses import dataclass
from enum import StrEnum


class CapabilityExposure(StrEnum):
    PUBLIC = "public"
    OPERATOR = "operator"
    INTERNAL = "internal"


class CapabilityKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"


class IdempotencyPolicy(StrEnum):
    NONE = "none"
    REQUIRED = "required"


class RevisionPolicy(StrEnum):
    NONE = "none"
    REQUIRED = "required"
    SERVER_SELECTED = "server_selected"


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    key: str
    exposure: CapabilityExposure
    description: str
    kind: CapabilityKind
    idempotency: IdempotencyPolicy
    revision: RevisionPolicy
    schema_version: int = 1
    party_scope: str | None = None
    override_capability: str | None = None
    legacy_aliases: frozenset[str] = frozenset()
    runtime_available: bool = True

    @property
    def discoverable(self) -> bool:
        return self.exposure is not CapabilityExposure.INTERNAL


def query_capability(
    key: str,
    exposure: CapabilityExposure,
    description: str,
    *,
    party_scope: str | None = None,
    override_capability: str | None = None,
    legacy_aliases: frozenset[str] = frozenset(),
    runtime_available: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        exposure=exposure,
        description=description,
        kind=CapabilityKind.QUERY,
        idempotency=IdempotencyPolicy.NONE,
        revision=RevisionPolicy.NONE,
        party_scope=party_scope,
        override_capability=override_capability,
        legacy_aliases=legacy_aliases,
        runtime_available=runtime_available,
    )


def command_capability(
    key: str,
    exposure: CapabilityExposure,
    description: str,
    *,
    revision: RevisionPolicy = RevisionPolicy.NONE,
    party_scope: str | None = None,
    override_capability: str | None = None,
    legacy_aliases: frozenset[str] = frozenset(),
    runtime_available: bool = True,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        exposure=exposure,
        description=description,
        kind=CapabilityKind.COMMAND,
        idempotency=IdempotencyPolicy.REQUIRED,
        revision=revision,
        party_scope=party_scope,
        override_capability=override_capability,
        legacy_aliases=legacy_aliases,
        runtime_available=runtime_available,
    )
