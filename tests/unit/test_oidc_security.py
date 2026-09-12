"""Credential confusion, provider resource bounds and live trust revocation.

Provider transport/reader doubles exclude external I/O only. These are unit
proofs; persisted binding and authority behavior belongs to the OIDC E2E suite.
"""

import asyncio
import json
from dataclasses import replace
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest
from test_oidc_auth import (
    JWKS_URI,
    KID,
    StaticJwksFetcher,
    authority_config,
    bearer_request,
    generate_signing_key,
    make_authenticator,
    mint_access_token,
    private_pem,
)

from request_engine.platform.db.oidc_authority_reader import parse_oidc_authority
from request_engine.platform.security.oidc_auth import (
    HttpxJwksFetcher,
    OidcAuthenticationRequired,
    OidcAuthorityConfig,
    OidcTokenAuthenticator,
    rsa_jwk,
)
from request_engine.platform.security.oidc_http import OidcHttpSubjectResolver

pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.adversarial]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        " ",
        "http://idp.test",
        "https://u:p@idp.test",
        "https://idp.test/#fragment",
        "https://idp.test:invalid",
        "https://idp.test:99999",
        "https://idp.test\n",
        "https://idp.test\\evil",
    ],
)
def test_malformed_authority_configuration_is_invisible(value: Any) -> None:
    config = authority_config()
    for field in ("issuer_or_environment", "jwks_uri"):
        row = {
            "id": config.authority_id,
            "issuer_or_environment": config.issuer,
            "configuration_ref": json.dumps(
                {
                    "jwks_uri": value if field == "jwks_uri" else config.jwks_uri,
                    "audience": config.audience,
                }
            ),
        }
        if field == "issuer_or_environment":
            row[field] = value
        assert parse_oidc_authority(row) is None


@pytest.mark.parametrize(
    "value",
    [
        "null",
        "[]",
        "42",
        '"string"',
        "{",
        '{"jwks_uri": 3}',
        '{"jwks_uri": "https://idp.test", "audience": []}',
    ],
)
def test_non_object_authority_configuration_is_invisible(value: str) -> None:
    assert (
        parse_oidc_authority(
            {
                "id": uuid4(),
                "issuer_or_environment": authority_config().issuer,
                "configuration_ref": value,
            }
        )
        is None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("exp", float("nan")),
        ("exp", float("inf")),
        ("iat", True),
        ("iat", "1"),
        ("exp", None),
        ("nbf", None),
        ("client_id", ""),
        ("jti", ""),
        ("sub", 2),
        ("aud", ["other"]),
    ],
)
@pytest.mark.asyncio
async def test_malformed_signed_claims_deny_without_server_error(field: str, value: Any) -> None:
    authenticator, key, _ = make_authenticator()
    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(key, claims={field: value}))


@pytest.mark.parametrize(
    "header",
    [
        {"typ": "JWT"},
        {"typ": "id+jwt"},
        {"typ": "at+jwt", "crit": ["unknown"]},
        {"typ": "at+jwt", "b64": False},
    ],
)
@pytest.mark.asyncio
async def test_id_tokens_and_unsupported_critical_headers_are_rejected(
    header: dict[str, Any],
) -> None:
    authenticator, key, fetcher = make_authenticator()
    claims = jwt.decode(mint_access_token(key), options={"verify_signature": False})
    token = jwt.encode(claims, private_pem(key), algorithm="RS256", headers={"kid": KID, **header})
    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(token)
    assert fetcher.calls == 0


@pytest.mark.parametrize(
    "override",
    [
        {"use": "enc"},
        {"alg": "RS512"},
        {"key_ops": ["sign"]},
        {"key_ops": ["verify", "sign"]},
        {"d": "private"},
        {"n": "%%%"},
        {"e": ""},
        {"n": 1},
    ],
)
@pytest.mark.asyncio
async def test_signing_key_purpose_and_material_are_validated(override: dict[str, Any]) -> None:
    key = generate_signing_key()
    jwk = {**rsa_jwk(key.public_key().public_numbers(), kid=KID), **override}
    authenticator = OidcTokenAuthenticator(authority_config(), StaticJwksFetcher({"keys": [jwk]}))
    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(key))


@pytest.mark.asyncio
async def test_ambiguous_key_identifier_rejected_even_when_first_signature_matches() -> None:
    authenticator, key, fetcher = make_authenticator()
    jwk = rsa_jwk(key.public_key().public_numbers(), kid=KID)
    fetcher.document = {"keys": [jwk, jwk]}
    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(key))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://other.test"}),
        httpx.Response(200, content=b"x" * 262145),
        httpx.Response(200, content=b'{"keys": [], "keys": []}'),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"keys": [{}] * 65}),
        httpx.Response(200, content=b"{"),
    ],
)
@pytest.mark.asyncio
async def test_fetcher_bounds_untrusted_responses_and_does_not_follow_redirects(
    response: httpx.Response,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=True
    ) as client:
        fetcher = HttpxJwksFetcher(client)
        for _ in range(2):
            with pytest.raises(OidcAuthenticationRequired):
                await fetcher.fetch(JWKS_URI)
        assert calls == 1  # failure cooldown also prevents request amplification
        await fetcher.aclose()
        assert not client.is_closed


@pytest.mark.asyncio
async def test_rotation_singleflight_expiry_and_outage_never_reuse_stale_keys() -> None:
    old_key = generate_signing_key()
    new_key = generate_signing_key()
    now = [0.0]
    calls = 0
    unavailable = False
    published_key = old_key

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if unavailable:
            raise httpx.ConnectError("unavailable")
        return httpx.Response(
            200, json={"keys": [rsa_jwk(published_key.public_key().public_numbers(), kid=KID)]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = HttpxJwksFetcher(client, ttl_seconds=10, clock=lambda: now[0])
        authenticator = OidcTokenAuthenticator(authority_config(), fetcher)
        await asyncio.gather(
            *(authenticator.authenticate(mint_access_token(old_key)) for _ in range(8))
        )
        assert calls == 1
        published_key = new_key
        for _ in range(3):
            with pytest.raises(OidcAuthenticationRequired):
                await authenticator.authenticate(mint_access_token(new_key, kid="unknown"))
        assert calls == 1
        now[0] = 10
        await authenticator.authenticate(mint_access_token(new_key))
        with pytest.raises(OidcAuthenticationRequired):
            await authenticator.authenticate(mint_access_token(old_key))
        assert calls == 2
        now[0] = 20
        unavailable = True
        with pytest.raises(OidcAuthenticationRequired):
            await authenticator.authenticate(mint_access_token(new_key))
        assert calls == 3


class MutableAuthorityReader:
    def __init__(self, config: OidcAuthorityConfig) -> None:
        self.configs: tuple[OidcAuthorityConfig, ...] = (config,)
        self.calls = 0

    async def read_active_authorities(self) -> tuple[OidcAuthorityConfig, ...]:
        self.calls += 1
        return self.configs


@pytest.mark.asyncio
async def test_live_authority_removal_readdition_and_configuration_change_without_restart() -> None:
    authenticator, key, fetcher = make_authenticator()
    reader = MutableAuthorityReader(authenticator.config)
    resolver = OidcHttpSubjectResolver(authority_reader=reader, jwks_fetcher=fetcher)
    assert reader.calls == 0
    request = bearer_request(mint_access_token(key))
    assert (await resolver.resolve_subject(request)).subject.authority_id == str(
        authenticator.config.authority_id
    )
    reader.configs = ()
    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(request)
    assert fetcher.calls == 1
    reader.configs = (replace(authenticator.config, audience="different-api"),)
    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(request)
    reader.configs = (authenticator.config,)
    await resolver.resolve_subject(request)
    await resolver.aclose()
    await resolver.aclose()
    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(request)


@pytest.mark.asyncio
async def test_revocation_while_awaiting_provider_keys_cannot_authenticate() -> None:
    authenticator, key, _ = make_authenticator()
    reader = MutableAuthorityReader(authenticator.config)

    class RevokingFetcher:
        async def fetch(self, jwks_uri: str) -> dict[str, Any]:
            reader.configs = ()
            return {"keys": [rsa_jwk(key.public_key().public_numbers(), kid=KID)]}

    resolver = OidcHttpSubjectResolver(authority_reader=reader, jwks_fetcher=RevokingFetcher())
    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(bearer_request(mint_access_token(key)))
    assert reader.calls == 2


@pytest.mark.asyncio
async def test_authority_read_failure_is_closed_and_never_falls_back_to_cached_config() -> None:
    class FailingReader:
        async def read_active_authorities(self) -> tuple[OidcAuthorityConfig, ...]:
            raise RuntimeError("database offline")

    _, key, fetcher = make_authenticator()
    resolver = OidcHttpSubjectResolver(authority_reader=FailingReader(), jwks_fetcher=fetcher)
    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(bearer_request(mint_access_token(key)))
    assert fetcher.calls == 0


@pytest.mark.asyncio
async def test_default_fetcher_owns_and_closes_its_client() -> None:
    fetcher = HttpxJwksFetcher()
    await fetcher.aclose()
    await fetcher.aclose()
    with pytest.raises(OidcAuthenticationRequired):
        await fetcher.fetch(JWKS_URI)


@pytest.mark.parametrize("ttl", [0, -1, 301, float("inf"), float("nan")])
def test_unbounded_cache_configuration_is_rejected(ttl: float) -> None:
    with pytest.raises(ValueError):
        HttpxJwksFetcher(ttl_seconds=ttl)
