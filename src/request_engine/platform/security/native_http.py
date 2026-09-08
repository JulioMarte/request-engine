from __future__ import annotations

from uuid import UUID

from fastapi import Request

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.identity_resolution import (
    IdentityPrincipalResolver,
    TenantContextRequired,
)
from request_engine.platform.security.native_auth import parse_opaque_token
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)

AUTHORIZATION_HEADER = "Authorization"
ORGANIZATION_HEADER = "X-RE-Organization-ID"
_NATIVE_AUTHENTICATION_METHOD = "native_session"


class TenantContextInvalid(ValueError):
    pass


class NativeSessionHttpActorResolver:
    """Resolve HTTP Bearer evidence to fresh tenant authority on every request.

    The organization header is only a tenant selector. It never contributes
    authority: the selected tenant must still have an ACTIVE IdentityBinding for
    the authenticated subject, and authority is re-read from RE-owned state.
    """

    def __init__(
        self,
        *,
        authenticator: NativeSessionAuthenticator,
        principal_resolver: IdentityPrincipalResolver,
    ) -> None:
        self._authenticator = authenticator
        self._principal_resolver = principal_resolver

    async def resolve_actor(self, request: Request) -> ActorContext:
        raw_token = bearer_token(request)
        organization_id = tenant_context(request)
        parsed = parse_opaque_token(raw_token)
        subject = await self._authenticator.authenticate(NativeSessionEvidence(raw_token))
        return await self._principal_resolver.resolve_tenant_actor(
            subject=subject,
            organization_id=organization_id,
            authentication_method=_NATIVE_AUTHENTICATION_METHOD,
            credential_id=str(parsed.token_id),
        )


def bearer_token(request: Request) -> str:
    value = request.headers.get(AUTHORIZATION_HEADER)
    if value is None:
        raise AuthenticationRequired("Bearer authentication is required")
    scheme, separator, credential = value.partition(" ")
    normalized = credential.strip()
    if separator != " " or scheme.casefold() != "bearer" or not normalized:
        raise AuthenticationRequired("Bearer authentication is required")
    if " " in normalized:
        raise AuthenticationRequired("Bearer credential is malformed")
    return normalized


def tenant_context(request: Request) -> UUID:
    value = request.headers.get(ORGANIZATION_HEADER)
    if value is None or not value.strip():
        raise TenantContextRequired(f"{ORGANIZATION_HEADER} is required")
    try:
        return UUID(value.strip())
    except ValueError as exc:
        raise TenantContextInvalid(f"{ORGANIZATION_HEADER} must be a UUID") from exc
