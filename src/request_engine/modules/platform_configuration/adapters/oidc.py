from __future__ import annotations

from request_engine.modules.platform_configuration.application.oidc import (
    OidcConfigurationValidator,
    OidcProviderConfiguration,
    OidcValidationResult,
    OidcValidationStatus,
)
from request_engine.platform.security.oidc_auth import (
    HttpxJwksFetcher,
    OidcAuthenticationRequired,
    validate_jwks_document,
)


class HttpxOidcConfigurationValidator(OidcConfigurationValidator):
    """Validate the configured JWKS endpoint without holding database locks.

    The fetcher supplies the same TLS, redirect, response-size and JSON bounds
    used by runtime authentication.  The document is then checked with the same
    RS256 key acceptance rules as token verification.
    """

    async def validate(
        self,
        configuration: OidcProviderConfiguration,
    ) -> OidcValidationResult:
        fetcher = HttpxJwksFetcher()
        try:
            document = await fetcher.fetch(configuration.jwks_uri)
            validate_jwks_document(document)
        except OidcAuthenticationRequired:
            return OidcValidationResult(
                OidcValidationStatus.UNAVAILABLE,
                "oidc_jwks_unavailable_or_invalid",
            )
        finally:
            await fetcher.aclose()
        return OidcValidationResult(
            OidcValidationStatus.VALID,
            "oidc_jwks_valid",
        )
