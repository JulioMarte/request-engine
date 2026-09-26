from __future__ import annotations

from request_engine.modules.platform_configuration.application.oidc import (
    OidcConfigurationValidator,
    OidcProviderConfiguration,
    OidcValidationResult,
    OidcValidationStatus,
)
from request_engine.platform.security.oidc_auth import (
    HttpxJwksFetcher,
    JwksFetcher,
    OidcAuthenticationRequired,
    validate_jwks_document,
)


class HttpxOidcConfigurationValidator(OidcConfigurationValidator):
    """Validate the configured JWKS endpoint without holding database locks.

    The fetcher supplies the same TLS, redirect, response-size and JSON bounds
    used by runtime authentication. The document is then checked with the same
    RS256 key acceptance rules as token verification.
    """

    def __init__(self, fetcher: JwksFetcher | None = None) -> None:
        self._owns_fetcher = fetcher is None
        self._fetcher = fetcher if fetcher is not None else HttpxJwksFetcher()

    async def validate(
        self,
        configuration: OidcProviderConfiguration,
    ) -> OidcValidationResult:
        try:
            document = await self._fetcher.fetch(configuration.jwks_uri)
        except OidcAuthenticationRequired:
            return OidcValidationResult(
                OidcValidationStatus.UNAVAILABLE,
                "oidc_jwks_unavailable",
            )
        finally:
            if self._owns_fetcher and isinstance(self._fetcher, HttpxJwksFetcher):
                await self._fetcher.aclose()

        try:
            validate_jwks_document(document)
        except OidcAuthenticationRequired:
            return OidcValidationResult(
                OidcValidationStatus.INVALID,
                "oidc_jwks_incompatible",
            )
        return OidcValidationResult(
            OidcValidationStatus.VALID,
            "oidc_jwks_valid",
        )
