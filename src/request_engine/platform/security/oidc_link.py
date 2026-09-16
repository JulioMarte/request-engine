"""Second-proof OIDC verification for self-service identity linking.

The target authority is derived from the persisted link intent, never from the
request body. This verifier resolves that authority's live configuration, caches
one authenticator per authority id and returns only the verified subject id.
Every failure is the same opaque ``OidcAuthenticationRequired`` used by the
federated authentication arm, so an invalid second proof is indistinguishable
from an invalid login. Construction performs no I/O; the short authority read
ends before any provider network call.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from request_engine.platform.security.oidc_auth import (
    HttpxJwksFetcher,
    JwksFetcher,
    OidcAuthenticationRequired,
    OidcAuthorityConfig,
    OidcTokenAuthenticator,
)
from request_engine.platform.security.oidc_http import OidcAuthorityReader


class OidcLinkVerifier(Protocol):
    """Verify one external OIDC access token and return its subject id."""

    async def verify(self, authority_id: UUID, access_token: str) -> str: ...


class OidcIdentityLinkVerifier:
    """Compose per-authority OIDC authenticators over live persisted configuration.

    Injected fetchers remain caller-owned. Close this verifier at application
    shutdown to release its default fetcher; ``aclose`` is idempotent.
    """

    def __init__(
        self,
        authority_reader: OidcAuthorityReader,
        *,
        jwks_fetcher: JwksFetcher | None = None,
    ) -> None:
        self._authority_reader = authority_reader
        if jwks_fetcher is not None:
            self._owned_fetcher: HttpxJwksFetcher | None = None
            self._fetcher: JwksFetcher = jwks_fetcher
        else:
            self._owned_fetcher = HttpxJwksFetcher()
            self._fetcher = self._owned_fetcher
        self._authenticators: dict[UUID, tuple[OidcAuthorityConfig, OidcTokenAuthenticator]] = {}
        self._closed = False

    async def verify(self, authority_id: UUID, access_token: str) -> str:
        if self._closed:
            raise OidcAuthenticationRequired("the OIDC link verifier is closed")
        config = await self._current_config(authority_id)
        cached = self._authenticators.get(authority_id)
        if cached is None or cached[0] != config:
            authenticator = OidcTokenAuthenticator(config, self._fetcher)
            self._authenticators[authority_id] = (config, authenticator)
        else:
            authenticator = cached[1]
        subject = await authenticator.authenticate(access_token)
        if await self._current_config(authority_id) != authenticator.config:
            raise OidcAuthenticationRequired("the OIDC link authority changed during verification")
        return subject.subject_id

    async def _current_config(self, authority_id: UUID) -> OidcAuthorityConfig:
        try:
            configs = await self._authority_reader.read_active_authorities()
        except Exception as exc:
            raise OidcAuthenticationRequired("the OIDC authorities could not be read") from exc
        matches = [config for config in configs if config.authority_id == authority_id]
        if len(matches) != 1:
            raise OidcAuthenticationRequired("the link authority is inactive or ambiguous")
        return matches[0]

    async def aclose(self) -> None:
        self._closed = True
        self._authenticators.clear()
        if self._owned_fetcher is not None:
            await self._owned_fetcher.aclose()


__all__ = ["OidcIdentityLinkVerifier", "OidcLinkVerifier"]
