"""HTTP trust-boundary resolution for OIDC bearer tokens.

Routing between multiple configured OIDC authorities uses an explicitly
UNVERIFIED decode of the ``iss`` claim only, because the token itself does not
name the authority. The issuer is used solely to select one configured
authority; every claim that matters is then fully re-verified under that
authority's signing keys, audience and issuer configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

import jwt
from fastapi import Request

from request_engine.platform.security.native_http import bearer_token
from request_engine.platform.security.oidc_auth import (
    MAX_TOKEN_LENGTH,
    HttpxJwksFetcher,
    JwksFetcher,
    OidcAuthenticationRequired,
    OidcAuthorityConfig,
    OidcTokenAuthenticator,
)
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject

_OIDC_AUTHENTICATION_METHOD = "oidc_token"


class OidcAuthorityReader(Protocol):
    async def read_active_authorities(self) -> tuple[OidcAuthorityConfig, ...]: ...


class OidcHttpSubjectResolver:
    """Resolve identity using current trusted configuration, without RE authority.

    Production composition supplies ``authority_reader``; construction performs
    no I/O. Its short read transaction ends before any provider network call.
    Configuration is read again after verification to reject changes during I/O.
    The mapping form exists for immutable, deployment-owned configurations only.
    Injected fetchers are caller-owned. Close this resolver at application shutdown
    to release its default fetcher; ``aclose`` is idempotent.
    """

    def __init__(
        self,
        authenticators: Mapping[UUID, OidcTokenAuthenticator] | None = None,
        *,
        authority_reader: OidcAuthorityReader | None = None,
        jwks_fetcher: JwksFetcher | None = None,
    ) -> None:
        if authority_reader is not None and authenticators is not None:
            raise ValueError("choose live or immutable OIDC authority configuration")
        self._authority_reader = authority_reader
        self._owned_fetcher = (
            HttpxJwksFetcher() if authority_reader is not None and jwks_fetcher is None else None
        )
        self._fetcher = jwks_fetcher if jwks_fetcher is not None else self._owned_fetcher
        self._closed = False
        issuers: dict[str, OidcTokenAuthenticator] = {}
        for authenticator in (authenticators or {}).values():
            issuer = authenticator.config.issuer
            if issuer in issuers:
                raise ValueError(f"multiple OIDC authorities claim issuer {issuer!r}")
            issuers[issuer] = authenticator
        self._authenticators_by_issuer = issuers

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        if self._closed:
            raise OidcAuthenticationRequired("the OIDC resolver is closed")
        raw_token = bearer_token(request)
        issuer = self._unverified_issuer(raw_token)
        if self._authority_reader is None:
            authenticator = self._authenticators_by_issuer.get(issuer)
            if authenticator is None:
                raise OidcAuthenticationRequired("the bearer token issuer is not federated")
        else:
            config = await self._current_config(issuer)
            if self._fetcher is None:
                raise OidcAuthenticationRequired("the OIDC key fetcher is unavailable")
            authenticator = OidcTokenAuthenticator(config, self._fetcher)
        subject = await authenticator.authenticate(raw_token)
        if self._authority_reader is not None and (
            await self._current_config(issuer) != authenticator.config
        ):
            raise OidcAuthenticationRequired("the OIDC authority changed during authentication")
        return AuthenticatedHttpSubject(
            subject=subject,
            authentication_method=_OIDC_AUTHENTICATION_METHOD,
            credential_id=None,
        )

    async def _current_config(self, issuer: str) -> OidcAuthorityConfig:
        if self._authority_reader is None:
            raise OidcAuthenticationRequired("the OIDC authority reader is unavailable")
        try:
            configs = await self._authority_reader.read_active_authorities()
        except Exception as exc:
            raise OidcAuthenticationRequired("the OIDC authorities could not be read") from exc
        matches = [config for config in configs if config.issuer == issuer]
        if len(matches) != 1:
            raise OidcAuthenticationRequired("the bearer issuer is inactive or ambiguous")
        return matches[0]

    async def aclose(self) -> None:
        self._closed = True
        if self._owned_fetcher is not None:
            await self._owned_fetcher.aclose()

    @staticmethod
    def _unverified_issuer(raw_token: str) -> str:
        if len(raw_token) > MAX_TOKEN_LENGTH:
            raise OidcAuthenticationRequired("the bearer token is too large")
        try:
            unverified = jwt.decode(raw_token, options={"verify_signature": False})
        except (jwt.PyJWTError, ValueError, TypeError, RecursionError) as exc:
            raise OidcAuthenticationRequired("the bearer token is not a decodable JWT") from exc
        issuer = unverified.get("iss")
        if not isinstance(issuer, str) or not issuer.strip():
            raise OidcAuthenticationRequired("the bearer token has no issuer")
        return issuer


__all__ = ["OidcHttpSubjectResolver"]
