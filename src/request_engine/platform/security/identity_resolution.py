from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from request_engine.platform.security.authentication import AuthenticatedSubject
from request_engine.platform.security.context import ActorContext, PrincipalKind
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.principal_authority import (
    PlatformPrincipalAuthorityReader,
    PrincipalAuthorityReader,
    PrincipalAuthoritySnapshot,
)


class IdentityResolutionError(RuntimeError):
    """Base class for typed authentication-to-Principal resolution failures."""


class IdentityNotBound(IdentityResolutionError):
    pass


class IdentityBindingPending(IdentityResolutionError):
    pass


class IdentityBindingSuspended(IdentityResolutionError):
    pass


class IdentityBindingRevoked(IdentityResolutionError):
    pass


class TenantContextRequired(IdentityResolutionError):
    pass


class TenantContextAmbiguous(IdentityResolutionError):
    pass


class PrincipalProvisioningRequired(IdentityResolutionError):
    pass


class IdentityBindingPlane(StrEnum):
    TENANT = "tenant"
    PLATFORM = "platform"


class IdentityBindingStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class IdentityBindingSnapshot:
    binding_id: UUID
    identity_authority_id: UUID
    subject_id: str
    principal_id: UUID
    principal_plane: IdentityBindingPlane
    organization_id: UUID | None
    status: IdentityBindingStatus
    revision: int

    def __post_init__(self) -> None:
        if self.revision <= 0:
            raise ValueError("identity binding revision must be positive")
        if self.principal_plane is IdentityBindingPlane.TENANT and self.organization_id is None:
            raise ValueError("tenant binding requires organization_id")
        if self.principal_plane is IdentityBindingPlane.PLATFORM and self.organization_id is not None:
            raise ValueError("platform binding cannot carry organization_id")


class IdentityBindingReader(Protocol):
    """Plane-scoped reads; implementations must not enumerate cross-tenant bindings."""

    async def read_tenant_subject_bindings(
        self,
        *,
        identity_authority_id: UUID,
        subject_id: str,
        organization_id: UUID,
    ) -> tuple[IdentityBindingSnapshot, ...]: ...

    async def read_platform_subject_bindings(
        self, *, identity_authority_id: UUID, subject_id: str
    ) -> tuple[IdentityBindingSnapshot, ...]: ...


class IdentityPrincipalResolver:
    """Resolve a provider-neutral subject to current RE-owned authority.

    Tenant selection happens before binding lookup so PostgreSQL RLS remains a
    trust boundary rather than a post-query filter. Principal ids and
    capabilities are never accepted as inputs.
    """

    def __init__(
        self,
        *,
        binding_reader: IdentityBindingReader,
        tenant_authority_reader: PrincipalAuthorityReader,
        platform_authority_reader: PlatformPrincipalAuthorityReader,
    ) -> None:
        self._binding_reader = binding_reader
        self._tenant_authority_reader = tenant_authority_reader
        self._platform_authority_reader = platform_authority_reader

    async def resolve_tenant_actor(
        self,
        *,
        subject: AuthenticatedSubject,
        organization_id: UUID | None,
        authentication_method: str,
        credential_id: str | None = None,
        technical_principal_id: UUID | None = None,
        interaction_id: str | None = None,
    ) -> ActorContext:
        if organization_id is None:
            raise TenantContextRequired("tenant routes require explicit tenant context")
        authority_id = _authority_id(subject)
        bindings = await self._binding_reader.read_tenant_subject_bindings(
            identity_authority_id=authority_id,
            subject_id=subject.subject_id,
            organization_id=organization_id,
        )
        binding = _select_binding(bindings)
        authority = await self._tenant_authority_reader.read_tenant_principal_authority(
            organization_id=organization_id,
            principal_id=binding.principal_id,
        )
        if authority is None:
            raise PrincipalProvisioningRequired("bound tenant Principal is not currently usable")
        return ActorContext(
            organization_id=organization_id,
            principal_id=binding.principal_id,
            capabilities=authority.capabilities,
            principal_kind=_principal_kind(authority),
            authentication_method=authentication_method,
            credential_id=credential_id,
            technical_principal_id=technical_principal_id,
            authority_revision=authority.authority_revision,
            interaction_id=interaction_id,
        )

    async def resolve_platform_actor(
        self,
        *,
        subject: AuthenticatedSubject,
        authentication_method: str,
        credential_id: str | None = None,
        technical_principal_id: UUID | None = None,
        interaction_id: str | None = None,
    ) -> PlatformActorContext:
        authority_id = _authority_id(subject)
        bindings = await self._binding_reader.read_platform_subject_bindings(
            identity_authority_id=authority_id,
            subject_id=subject.subject_id,
        )
        binding = _select_binding(bindings)
        authority = await self._platform_authority_reader.read_platform_principal_authority(
            principal_id=binding.principal_id
        )
        if authority is None:
            raise PrincipalProvisioningRequired("bound platform Principal is not currently usable")
        return PlatformActorContext(
            principal_id=binding.principal_id,
            capabilities=authority.capabilities,
            authority_revision=authority.authority_revision,
            principal_kind=_principal_kind(authority),
            authentication_method=authentication_method,
            credential_id=credential_id,
            technical_principal_id=technical_principal_id,
            interaction_id=interaction_id,
        )


def _authority_id(subject: AuthenticatedSubject) -> UUID:
    try:
        return UUID(subject.authority_id)
    except ValueError as exc:
        raise IdentityNotBound("authentication authority is not RE-addressable") from exc


def _select_binding(bindings: tuple[IdentityBindingSnapshot, ...]) -> IdentityBindingSnapshot:
    active = tuple(binding for binding in bindings if binding.status is IdentityBindingStatus.ACTIVE)
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        raise TenantContextAmbiguous("multiple active bindings match the selected trust plane")
    if any(binding.status is IdentityBindingStatus.SUSPENDED for binding in bindings):
        raise IdentityBindingSuspended("identity binding is suspended")
    if any(binding.status is IdentityBindingStatus.PENDING for binding in bindings):
        raise IdentityBindingPending("identity binding is pending activation")
    if any(binding.status is IdentityBindingStatus.REVOKED for binding in bindings):
        raise IdentityBindingRevoked("identity binding is revoked")
    raise IdentityNotBound("authenticated subject has no matching RE identity binding")


def _principal_kind(authority: PrincipalAuthoritySnapshot) -> PrincipalKind:
    try:
        return PrincipalKind(authority.principal_kind)
    except ValueError as exc:
        raise PrincipalProvisioningRequired("Principal kind cannot be safely materialized") from exc
