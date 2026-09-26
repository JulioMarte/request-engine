from __future__ import annotations

from typing import Any, Mapping

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from request_engine.modules.platform_configuration.adapters.oidc import (
    HttpxOidcConfigurationValidator,
)
from request_engine.modules.platform_configuration.application.oidc import (
    OidcProviderConfiguration,
    OidcValidationStatus,
)
from request_engine.platform.security.oidc_auth import (
    OidcAuthenticationRequired,
    rsa_jwk,
)


class _Fetcher:
    def __init__(
        self,
        document: Mapping[str, Any] | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self.document = document
        self.unavailable = unavailable
        self.requested_uri: str | None = None

    async def fetch(self, jwks_uri: str) -> Mapping[str, Any]:
        self.requested_uri = jwks_uri
        if self.unavailable:
            raise OidcAuthenticationRequired("provider unavailable")
        assert self.document is not None
        return self.document


def _configuration() -> OidcProviderConfiguration:
    return OidcProviderConfiguration(
        issuer="https://id.example.test",
        jwks_uri="https://id.example.test/.well-known/jwks.json",
        audience="request-engine",
    )


@pytest.mark.asyncio
async def test_oidc_validator_accepts_runtime_compatible_rs256_key() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    fetcher = _Fetcher(
        {
            "keys": [
                rsa_jwk(
                    key.public_key().public_numbers(),
                    kid="managed-oidc-key",
                )
            ]
        }
    )

    result = await HttpxOidcConfigurationValidator(fetcher).validate(_configuration())

    assert result.status is OidcValidationStatus.VALID
    assert result.detail_code == "oidc_jwks_valid"
    assert fetcher.requested_uri == _configuration().jwks_uri


@pytest.mark.asyncio
async def test_oidc_validator_rejects_reachable_but_runtime_incompatible_jwks() -> None:
    fetcher = _Fetcher({"keys": [{"kty": "EC", "kid": "not-supported"}]})

    result = await HttpxOidcConfigurationValidator(fetcher).validate(_configuration())

    assert result.status is OidcValidationStatus.INVALID
    assert result.detail_code == "oidc_jwks_incompatible"


@pytest.mark.asyncio
async def test_oidc_validator_reports_provider_outage_without_committing_validation() -> None:
    fetcher = _Fetcher(unavailable=True)

    result = await HttpxOidcConfigurationValidator(fetcher).validate(_configuration())

    assert result.status is OidcValidationStatus.UNAVAILABLE
    assert result.detail_code == "oidc_jwks_unavailable"
