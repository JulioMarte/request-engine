from dataclasses import dataclass
from enum import StrEnum

from request_engine.platform.security.operation_risk import OperationRiskClass


class CapabilityExposure(StrEnum):
    PUBLIC = "public"
    OPERATOR = "operator"
    INTERNAL = "internal"


class CapabilityKind(StrEnum):
    QUERY = "query"
    COMMAND = "command"


class AuthorityPlane(StrEnum):
    """Independent authorization planes; possession in one never implies another."""

    PLATFORM = "platform"
    TENANT_CONTROL = "tenant_control"
    OPERATIONAL = "operational"


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
    authority_plane: AuthorityPlane = AuthorityPlane.OPERATIONAL
    schema_version: int = 1
    party_scope: str | None = None
    override_capability: str | None = None
    legacy_aliases: frozenset[str] = frozenset()
    runtime_available: bool = True
    risk_class: OperationRiskClass | None = None

    @property
    def discoverable(self) -> bool:
        return self.exposure is not CapabilityExposure.INTERNAL

    @property
    def effective_risk_class(self) -> OperationRiskClass | None:
        if self.risk_class is not None:
            return self.risk_class
        if self.kind is CapabilityKind.QUERY:
            return OperationRiskClass.READ
        return None


def query_capability(
    key: str,
    exposure: CapabilityExposure,
    description: str,
    *,
    authority_plane: AuthorityPlane = AuthorityPlane.OPERATIONAL,
    party_scope: str | None = None,
    override_capability: str | None = None,
    legacy_aliases: frozenset[str] = frozenset(),
    runtime_available: bool = True,
    risk_class: OperationRiskClass | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        exposure=exposure,
        description=description,
        kind=CapabilityKind.QUERY,
        idempotency=IdempotencyPolicy.NONE,
        revision=RevisionPolicy.NONE,
        authority_plane=authority_plane,
        party_scope=party_scope,
        override_capability=override_capability,
        legacy_aliases=legacy_aliases,
        runtime_available=runtime_available,
        risk_class=risk_class,
    )


def command_capability(
    key: str,
    exposure: CapabilityExposure,
    description: str,
    *,
    authority_plane: AuthorityPlane = AuthorityPlane.OPERATIONAL,
    revision: RevisionPolicy = RevisionPolicy.NONE,
    party_scope: str | None = None,
    override_capability: str | None = None,
    legacy_aliases: frozenset[str] = frozenset(),
    runtime_available: bool = True,
    risk_class: OperationRiskClass | None = None,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        exposure=exposure,
        description=description,
        kind=CapabilityKind.COMMAND,
        idempotency=IdempotencyPolicy.REQUIRED,
        revision=revision,
        authority_plane=authority_plane,
        party_scope=party_scope,
        override_capability=override_capability,
        legacy_aliases=legacy_aliases,
        runtime_available=runtime_available,
        risk_class=risk_class,
    )
