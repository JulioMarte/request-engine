from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from request_engine.modules.platform_configuration.application.configuration import (
    PlatformConfigurationProviderInvalid,
)

OIDC_CONFIGURATION_KIND = "identity.oidc"
OIDC_PROVIDER_KIND = "oidc"


@dataclass(frozen=True, slots=True)
class OidcProviderConfiguration:
    """Typed, non-secret configuration for the optional federated HUMAN arm.

    Activation state deliberately lives in the governed configuration revision
    lifecycle rather than being duplicated inside the payload.  No client secret
    is accepted: Request Engine's current OIDC bearer/JWKS flow does not need one.
    """

    issuer: str
    jwks_uri: str
    audience: str


def _https_url(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlatformConfigurationProviderInvalid(f"OIDC {field} must be a non-empty string")
    normalized = value.strip().rstrip("/") if field == "issuer" else value.strip()
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PlatformConfigurationProviderInvalid(
            f"OIDC {field} must be an absolute HTTPS URL without userinfo"
        )
    if parsed.fragment:
        raise PlatformConfigurationProviderInvalid(f"OIDC {field} must not contain a fragment")
    return normalized


def parse_oidc_configuration(
    configuration: dict[str, Any],
    *,
    provider_kind: str,
) -> OidcProviderConfiguration:
    """Validate the exact P7 OIDC administrative payload.

    Unknown fields fail closed.  In particular ``client_secret`` is rejected so
    an operator cannot accidentally place reversible credentials in PostgreSQL.
    """

    if provider_kind != OIDC_PROVIDER_KIND:
        raise PlatformConfigurationProviderInvalid("identity.oidc requires provider_kind=oidc")

    expected = {"issuer", "jwks_uri", "audience"}
    unknown = set(configuration) - expected
    missing = expected - set(configuration)
    if missing:
        raise PlatformConfigurationProviderInvalid(
            f"OIDC configuration is missing required fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise PlatformConfigurationProviderInvalid(
            f"OIDC configuration contains unsupported fields: {', '.join(sorted(unknown))}"
        )

    issuer = _https_url(configuration["issuer"], field="issuer")
    jwks_uri = _https_url(configuration["jwks_uri"], field="jwks_uri")
    audience = configuration["audience"]
    if not isinstance(audience, str) or not audience.strip():
        raise PlatformConfigurationProviderInvalid("OIDC audience must be a non-empty string")
    if len(audience.strip()) > 512:
        raise PlatformConfigurationProviderInvalid("OIDC audience exceeds 512 characters")

    return OidcProviderConfiguration(
        issuer=issuer,
        jwks_uri=jwks_uri,
        audience=audience.strip(),
    )
