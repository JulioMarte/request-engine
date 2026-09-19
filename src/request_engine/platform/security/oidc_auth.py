"""Verification-only OIDC bearer authentication for externally federated humans.

The resource-server token profile is RFC 9068 (``typ=at+jwt``), never an
OIDC ID token. The audience is the RE API resource, not a browser client ID.
Machine OIDC clients (client-credentials flows) are out of scope for this arm:
every subject authenticated here is asserted as HUMAN and must still resolve to
an active tenant IdentityBinding before any RE authority exists. This module
proves credential possession only; it never materializes Principal authority.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.utils import base64url_decode

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.http import AuthenticationRequired

_REQUIRED_TOKEN_AGE_CLAIMS = ("exp", "iat", "sub", "iss", "aud", "client_id", "jti")
_ALLOWED_SIGNING_ALGORITHM = "RS256"
_CLOCK_LEEWAY_SECONDS = 30
_DEFAULT_JWKS_TTL_SECONDS = 300.0
MAX_TOKEN_LENGTH = 16384


class OidcAuthenticationRequired(AuthenticationRequired):
    """Raised when an OIDC bearer cannot be verified against its authority."""


@dataclass(frozen=True, slots=True)
class OidcAuthorityConfig:
    """Verification configuration parsed from one active OIDC identity authority."""

    authority_id: UUID
    issuer: str
    jwks_uri: str
    audience: str

    def __post_init__(self) -> None:
        values = (self.issuer, self.jwks_uri, self.audience)
        if any(type(value) is not str or not value.strip() for value in values):
            raise ValueError("OIDC authority issuer, jwks_uri and audience are required")
        if any(value != value.strip() or len(value) > 2048 for value in values):
            raise ValueError("OIDC authority configuration is not canonical or is too long")
        for name, value in (("issuer", self.issuer), ("jwks_uri", self.jwks_uri)):
            validate_https_endpoint(value)
            if name == "issuer" and urlsplit(value).query:
                raise ValueError("OIDC issuer must not contain a query")


def validate_https_endpoint(value: str) -> None:
    """Only trusted configuration supplies endpoints; token URLs are never used."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(character.isspace() or ord(character) < 32 for character in value)
        or "\\" in value
    ):
        raise ValueError(
            "OIDC authority endpoint must be an absolute HTTPS URL without credentials"
        )
    # Accessing port validates malformed/out-of-range ports too.
    if parsed.port == 0:
        raise ValueError("OIDC authority endpoint port is invalid")


class JwksFetcher(Protocol):
    """Deployment port that retrieves a provider JWKS document."""

    async def fetch(self, jwks_uri: str) -> Mapping[str, Any]: ...


class HttpxJwksFetcher:
    """Fetch provider JWKS documents over HTTP with a per-instance TTL cache.

    Maximum staleness is the configured TTL (at most 300 seconds). Unknown
    kids do not trigger forced refreshes: rotate by publishing overlapping
    keys at least one TTL before using them. Failed refreshes never serve stale
    keys. A single-flight cache and short failure cooldown bound provider load.
    Injected clients belong to their caller and are not closed here.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        ttl_seconds: float = _DEFAULT_JWKS_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not math.isfinite(ttl_seconds) or not 0 < ttl_seconds <= 300:
            raise ValueError("JWKS TTL must be finite and between 0 and 300 seconds")
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(trust_env=False)
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._cache: dict[str, tuple[float, Mapping[str, Any] | None]] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def fetch(self, jwks_uri: str) -> Mapping[str, Any]:
        try:
            validate_https_endpoint(jwks_uri)
            async with asyncio.timeout(5), self._lock:
                if self._closed:
                    raise OidcAuthenticationRequired("the OIDC key fetcher is closed")
                now = self._clock()
                cached = self._cache.get(jwks_uri)
                if cached is not None and now < cached[0]:
                    if cached[1] is None:
                        raise OidcAuthenticationRequired("the OIDC key set is unavailable")
                    return cached[1]
                # Endpoint count is bounded even across configuration churn.
                if jwks_uri not in self._cache and len(self._cache) >= 64:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[jwks_uri] = (now + 5, None)
                document = await self._download(jwks_uri)
                self._cache[jwks_uri] = (self._clock() + self._ttl_seconds, document)
                return document
        except OidcAuthenticationRequired:
            raise
        except (httpx.HTTPError, ValueError, TypeError, TimeoutError, RecursionError) as exc:
            raise OidcAuthenticationRequired("the OIDC key set could not be retrieved") from exc

    async def _download(self, jwks_uri: str) -> Mapping[str, Any]:
        async with self._client.stream(
            "GET",
            jwks_uri,
            timeout=5,
            follow_redirects=False,
            headers={
                "Accept": "application/jwk-set+json, application/json",
                "Accept-Encoding": "identity",
            },
        ) as response:
            if (
                response.status_code != 200
                or response.headers.get("content-encoding", "identity") != "identity"
            ):
                raise OidcAuthenticationRequired("the OIDC key set is unavailable")
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 262144:
                    raise OidcAuthenticationRequired("the OIDC key set is too large")
        raw: object = json.loads(body, object_pairs_hook=_unique_json_object)
        if not isinstance(raw, dict):
            raise OidcAuthenticationRequired("the OIDC key set is malformed")
        document = cast(Mapping[str, Any], raw)
        keys = document.get("keys")
        if not isinstance(keys, list) or not 0 < len(cast(list[Any], keys)) <= 64:
            raise OidcAuthenticationRequired("the OIDC key set is malformed")
        return document

    async def aclose(self) -> None:
        self._closed = True
        self._cache.clear()
        if self._owns_client and not self._client.is_closed:
            await self._client.aclose()


class OidcTokenAuthenticator:
    """Verify one OIDC JWT against a single authority and emit identity only.

    The token must be signed with RS256 by a key in the authority's JWKS, and
    its ``exp``/``nbf`` claims are verified with a 30-second leeway for clock
    skew between RE and the identity provider. The ``iss``, ``aud`` and ``sub``
    claims are mandatory. ``kid`` routing is fail-closed: a token without a
    ``kid``, or with a ``kid`` absent from the fetched key set, is rejected
    rather than tried against every key.
    """

    def __init__(self, config: OidcAuthorityConfig, jwks_fetcher: JwksFetcher) -> None:
        self.config = config
        self._jwks_fetcher = jwks_fetcher

    async def authenticate(self, token: str) -> AuthenticatedSubject:
        try:
            if len(token) > MAX_TOKEN_LENGTH:
                raise OidcAuthenticationRequired("the OIDC bearer token is too large")
            header = jwt.get_unverified_header(token)
            if header.get("typ") not in ("at+jwt", "application/at+jwt"):
                raise OidcAuthenticationRequired("an RFC 9068 access token is required")
            if "crit" in header or "b64" in header:
                raise OidcAuthenticationRequired("unsupported OIDC token header extension")
            # Reject ambiguous JSON rather than inheriting a parser's last-wins behavior.
            for segment in token.split(".")[:2]:
                json.loads(base64url_decode(segment), object_pairs_hook=_unique_json_object)
            if header.get("alg") != _ALLOWED_SIGNING_ALGORITHM:
                raise OidcAuthenticationRequired("the OIDC bearer token algorithm is not allowed")
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256:
                raise OidcAuthenticationRequired("the OIDC bearer token has no key identifier")
            jwks = await self._fetch_jwks()
            key = _select_signing_key(jwks, kid)
            claims = jwt.decode(
                token,
                key,
                algorithms=[_ALLOWED_SIGNING_ALGORITHM],
                audience=self.config.audience,
                issuer=self.config.issuer,
                leeway=_CLOCK_LEEWAY_SECONDS,
                options={"require": list(_REQUIRED_TOKEN_AGE_CLAIMS)},
            )
        except OidcAuthenticationRequired:
            raise
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError, RecursionError) as exc:
            raise OidcAuthenticationRequired("the OIDC bearer token is invalid") from exc
        subject_id = claims.get("sub")
        if not isinstance(subject_id, str) or not subject_id.strip():
            raise OidcAuthenticationRequired("the OIDC bearer token has no usable subject")
        _validate_access_claims(claims)
        return AuthenticatedSubject(
            authority_id=str(self.config.authority_id),
            subject_id=subject_id,
            subject_class=AuthenticatedSubjectClass.HUMAN,
            metadata=_subject_metadata(claims),
        )

    async def _fetch_jwks(self) -> Mapping[str, Any]:
        try:
            return await self._jwks_fetcher.fetch(self.config.jwks_uri)
        except OidcAuthenticationRequired:
            raise
        except Exception as exc:
            raise OidcAuthenticationRequired(
                "the OIDC identity provider key set could not be retrieved"
            ) from exc


def _subject_metadata(claims: Mapping[str, Any]) -> dict[str, str]:
    metadata = {"authentication_authority_kind": "oidc"}
    email = claims.get("email")
    if isinstance(email, str) and email.strip():
        metadata["email"] = email
    return metadata


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON member")
        result[name] = value
    return result


def _validate_access_claims(claims: Mapping[str, Any]) -> None:
    for name in ("iat", "exp", "nbf"):
        value = claims.get(name)
        if name == "nbf" and name not in claims:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not -1e12 < value < 1e12
        ):
            raise OidcAuthenticationRequired("the access token has invalid NumericDate claims")
    if claims["iat"] > time.time() + _CLOCK_LEEWAY_SECONDS or claims["exp"] <= claims["iat"]:
        raise OidcAuthenticationRequired("the access token has invalid issuance/expiry order")
    for name in ("client_id", "jti"):
        value = claims.get(name)
        if not isinstance(value, str) or not value.strip():
            raise OidcAuthenticationRequired("the access token profile is incomplete")


def _select_signing_key(jwks: Mapping[str, Any], kid: str) -> RSAPublicKey:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or len(cast(list[Any], keys)) > 64:
        raise OidcAuthenticationRequired("the OIDC identity provider key set is malformed")
    matches = [
        cast(dict[str, Any], entry)
        for entry in cast(list[Any], keys)
        if isinstance(entry, dict) and cast(dict[str, Any], entry).get("kid") == kid
    ]
    if len(matches) != 1:
        raise OidcAuthenticationRequired("the OIDC key identifier is unknown or ambiguous")
    jwk = matches[0]
    if (
        jwk.get("kty") != "RSA"
        or jwk.get("alg", "RS256") != "RS256"
        or jwk.get("use", "sig") != "sig"
        or jwk.get("key_ops", ["verify"]) != ["verify"]
        or any(name in jwk for name in ("d", "p", "q", "dp", "dq", "qi", "oth"))
        or any(not isinstance(jwk.get(name), str) or len(jwk[name]) > 2048 for name in ("n", "e"))
    ):
        raise OidcAuthenticationRequired("the OIDC key is not an RSA verification key")
    try:
        key = jwt.PyJWK(jwk, algorithm="RS256").key
        if not isinstance(key, RSAPublicKey) or not 2048 <= key.key_size <= 8192:
            raise ValueError("RSA key size outside accepted bounds")
        return key
    except (jwt.PyJWTError, ValueError, TypeError, binascii.Error, OverflowError) as exc:
        raise OidcAuthenticationRequired("the OIDC key could not be materialized") from exc


def rsa_jwk(public_numbers: Any, *, kid: str) -> dict[str, str]:
    """Render one RSA public key as a single-entry verification JWK dict."""

    def encode_uint(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": _ALLOWED_SIGNING_ALGORITHM,
        "kid": kid,
        "n": encode_uint(public_numbers.n),
        "e": encode_uint(public_numbers.e),
    }


__all__ = [
    "HttpxJwksFetcher",
    "JwksFetcher",
    "OidcAuthenticationRequired",
    "OidcAuthorityConfig",
    "OidcTokenAuthenticator",
    "rsa_jwk",
]
