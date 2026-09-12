from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from fastapi import Request

from request_engine.platform.security.authentication import AuthenticatedSubject
from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.tenant_http import (
    ORGANIZATION_HEADER,
    TenantContextInvalid,
    tenant_context,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedHttpSubject:
    """Credential result that intentionally contains no RE authorization facts."""

    subject: AuthenticatedSubject
    authentication_method: str
    credential_id: str | None = None
    technical_principal_id: UUID | None = None
    interaction_id: str | None = None

    def __post_init__(self) -> None:
        if not self.authentication_method.strip():
            raise ValueError("authentication_method is required")
        if self.credential_id is not None and not self.credential_id.strip():
            raise ValueError("credential_id cannot be blank")
        if self.interaction_id is not None and not self.interaction_id.strip():
            raise ValueError("interaction_id cannot be blank")


class HttpSubjectResolver(Protocol):
    """Deployment/provider port: authenticate an HTTP request, never authorize it."""

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject: ...


class TenantPrincipalMaterializer(Protocol):
    async def resolve_tenant_actor(
        self,
        *,
        subject: AuthenticatedSubject,
        organization_id: UUID | None,
        authentication_method: str,
        credential_id: str | None = None,
        technical_principal_id: UUID | None = None,
        interaction_id: str | None = None,
    ) -> ActorContext: ...


class ProviderNeutralHttpActorResolver:
    """Turn authenticated identity into RE-owned tenant authority.

    The external subject resolver can prove credential possession and attach
    credential/workload attribution only. Tenant selection is read from the
    standard header and Principal/capability materialization is delegated to
    Request Engine's IdentityBinding + authority resolver.
    """

    def __init__(
        self,
        *,
        subject_resolver: HttpSubjectResolver,
        principal_resolver: TenantPrincipalMaterializer,
    ) -> None:
        self._subject_resolver = subject_resolver
        self._principal_resolver = principal_resolver

    async def resolve_actor(self, request: Request) -> ActorContext:
        authenticated = await self._subject_resolver.resolve_subject(request)
        return await self._principal_resolver.resolve_tenant_actor(
            subject=authenticated.subject,
            organization_id=tenant_context(request),
            authentication_method=authenticated.authentication_method,
            credential_id=authenticated.credential_id,
            technical_principal_id=authenticated.technical_principal_id,
            interaction_id=authenticated.interaction_id,
        )


class PlatformPrincipalMaterializer(Protocol):
    async def resolve_platform_actor(
        self,
        *,
        subject: AuthenticatedSubject,
        authentication_method: str,
        credential_id: str | None = None,
        technical_principal_id: UUID | None = None,
        interaction_id: str | None = None,
    ) -> PlatformActorContext: ...


class ProviderNeutralPlatformHttpActorResolver:
    """Authenticate a platform caller without a client-selected authority plane.

    Composition selects this boundary explicitly. Tenant selectors are rejected;
    identity and standing authority still come from the same provider-neutral
    authentication and current RE binding/materialization contracts.
    """

    def __init__(
        self,
        *,
        subject_resolver: HttpSubjectResolver,
        principal_resolver: PlatformPrincipalMaterializer,
    ) -> None:
        self._subject_resolver = subject_resolver
        self._principal_resolver = principal_resolver

    async def resolve_platform_actor(self, request: Request) -> PlatformActorContext:
        if ORGANIZATION_HEADER in request.headers:
            raise TenantContextInvalid("Platform control does not accept a tenant selector")
        authenticated = await self._subject_resolver.resolve_subject(request)
        return await self._principal_resolver.resolve_platform_actor(
            subject=authenticated.subject,
            authentication_method=authenticated.authentication_method,
            credential_id=authenticated.credential_id,
            technical_principal_id=authenticated.technical_principal_id,
            interaction_id=authenticated.interaction_id,
        )
