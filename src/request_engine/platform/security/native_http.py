from __future__ import annotations

from fastapi import Request

from request_engine.platform.security.context import ActorContext
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.identity_resolution import IdentityPrincipalResolver
from request_engine.platform.security.native_auth import parse_opaque_token
from request_engine.platform.security.native_session import (
    NativeSessionAuthenticator,
    NativeSessionEvidence,
)
from request_engine.platform.security.subject_http import (
    AuthenticatedHttpSubject,
    ProviderNeutralHttpActorResolver,
)
from request_engine.platform.security.tenant_http import (
    ORGANIZATION_HEADER,
    TenantContextInvalid,
    tenant_context,
)

AUTHORIZATION_HEADER = "Authorization"
_NATIVE_AUTHENTICATION_METHOD = "native_session"


class NativeSessionHttpSubjectResolver:
    """Authenticate a Native bearer token without materializing RE authority."""

    def __init__(self, authenticator: NativeSessionAuthenticator) -> None:
        self._authenticator = authenticator

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        raw_token = bearer_token(request)
        parsed = parse_opaque_token(raw_token)
        subject = await self._authenticator.authenticate(NativeSessionEvidence(raw_token))
        return AuthenticatedHttpSubject(
            subject=subject,
            authentication_method=_NATIVE_AUTHENTICATION_METHOD,
            credential_id=str(parsed.token_id),
        )


class NativeSessionHttpActorResolver:
    """Resolve Native HTTP evidence through the provider-neutral RE authority path."""

    def __init__(
        self,
        *,
        authenticator: NativeSessionAuthenticator,
        principal_resolver: IdentityPrincipalResolver,
    ) -> None:
        self._delegate = ProviderNeutralHttpActorResolver(
            subject_resolver=NativeSessionHttpSubjectResolver(authenticator),
            principal_resolver=principal_resolver,
        )

    async def resolve_actor(self, request: Request) -> ActorContext:
        return await self._delegate.resolve_actor(request)


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


__all__ = [
    "AUTHORIZATION_HEADER",
    "ORGANIZATION_HEADER",
    "NativeSessionHttpActorResolver",
    "NativeSessionHttpSubjectResolver",
    "TenantContextInvalid",
    "bearer_token",
    "tenant_context",
]
