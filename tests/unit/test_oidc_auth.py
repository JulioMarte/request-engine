import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Request

from request_engine.platform.security.authentication import (
    AuthenticatedSubject,
    AuthenticatedSubjectClass,
)
from request_engine.platform.security.http import AuthenticationRequired
from request_engine.platform.security.oidc_auth import (
    HttpxJwksFetcher,
    OidcAuthenticationRequired,
    OidcAuthorityConfig,
    OidcTokenAuthenticator,
    rsa_jwk,
)
from request_engine.platform.security.subject_http import AuthenticatedHttpSubject
from request_engine.platform.security.workload_auth import (
    WorkloadAuthorityStatus,
    WorkloadCredentialAuthenticator,
    WorkloadCredentialSnapshot,
    WorkloadCredentialStatus,
    WorkloadIdentityStatus,
    WorkloadKind,
)
from request_engine.platform.security.workload_http import DispatchedBearerSubjectResolver

pytestmark = pytest.mark.unit

_ISSUER = "https://idp.example.test"
_AUDIENCE = "request-engine"
KID = "test-key-1"
JWKS_URI = "https://idp.example.test/.well-known/jwks.json"


class StaticJwksFetcher:
    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = document
        self.calls = 0

    async def fetch(self, jwks_uri: str) -> Mapping[str, Any]:
        self.calls += 1
        return self.document


class FailingJwksFetcher:
    async def fetch(self, jwks_uri: str) -> Mapping[str, Any]:
        raise RuntimeError("identity provider unreachable")


def generate_signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def private_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def authority_config() -> OidcAuthorityConfig:
    return OidcAuthorityConfig(
        authority_id=uuid4(),
        issuer=_ISSUER,
        jwks_uri=JWKS_URI,
        audience=_AUDIENCE,
    )


def test_oidc_authority_rejects_non_https_endpoints() -> None:
    with pytest.raises(ValueError, match="absolute HTTPS"):
        OidcAuthorityConfig(
            authority_id=uuid4(),
            issuer="http://idp.example.test",
            jwks_uri=JWKS_URI,
            audience=_AUDIENCE,
        )


def make_authenticator(
    *,
    key: rsa.RSAPrivateKey | None = None,
    jwks: Mapping[str, Any] | None = None,
) -> tuple[OidcTokenAuthenticator, rsa.RSAPrivateKey, StaticJwksFetcher]:
    private_key = key if key is not None else generate_signing_key()
    document = (
        jwks
        if jwks is not None
        else {"keys": [rsa_jwk(private_key.public_key().public_numbers(), kid=KID)]}
    )
    fetcher = StaticJwksFetcher(document)
    return OidcTokenAuthenticator(authority_config(), fetcher), private_key, fetcher


def mint_access_token(
    private_key: rsa.RSAPrivateKey,
    *,
    algorithm: str = "RS256",
    kid: str | None = KID,
    claims: dict[str, Any] | None = None,
) -> str:
    now = int(datetime.now(UTC).timestamp())
    payload: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": "user-123",
        "exp": now + 300,
        "iat": now,
        "client_id": "clinic-web",
        "jti": str(uuid4()),
    }
    if claims:
        payload.update(claims)
    headers: dict[str, Any] = {"typ": "at+jwt"}
    if kid is not None:
        headers["kid"] = kid
    return jwt.encode(payload, private_pem(private_key), algorithm=algorithm, headers=headers)


def bearer_request(bearer: str) -> Request:
    return Request(
        scope={
            "type": "http",
            "method": "GET",
            "path": "/v1/parties/lookup",
            "query_string": b"",
            "headers": [(b"authorization", f"Bearer {bearer}".encode("ascii"))],
        }
    )


@pytest.mark.asyncio
async def test_valid_token_authenticates_federated_human() -> None:
    authenticator, private_key, _ = make_authenticator()

    subject = await authenticator.authenticate(mint_access_token(private_key))

    assert subject.subject_id == "user-123"
    assert subject.subject_class is AuthenticatedSubjectClass.HUMAN
    assert subject.metadata["authentication_authority_kind"] == "oidc"


@pytest.mark.asyncio
async def test_email_claim_is_carried_as_optional_metadata() -> None:
    authenticator, private_key, _ = make_authenticator()

    with_email = await authenticator.authenticate(
        mint_access_token(private_key, claims={"email": "user@example.test"})
    )
    without_email = await authenticator.authenticate(mint_access_token(private_key))

    assert with_email.metadata["email"] == "user@example.test"
    assert "email" not in without_email.metadata


@pytest.mark.asyncio
async def test_wrong_audience_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(
            mint_access_token(private_key, claims={"aud": "another-relying-party"})
        )


@pytest.mark.asyncio
async def test_wrong_issuer_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(
            mint_access_token(private_key, claims={"iss": "https://evil.example.test"})
        )


@pytest.mark.asyncio
async def test_expired_token_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(
            mint_access_token(
                private_key, claims={"exp": int(datetime.now(UTC).timestamp()) - 3600}
            )
        )


@pytest.mark.asyncio
async def test_future_nbf_token_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(
            mint_access_token(
                private_key,
                claims={"nbf": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
            )
        )


@pytest.mark.asyncio
async def test_missing_expiry_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()
    token = jwt.encode(
        {"iss": _ISSUER, "aud": _AUDIENCE, "sub": "user-123"},
        private_pem(private_key),
        algorithm="RS256",
        headers={"kid": KID},
    )

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(token)


@pytest.mark.asyncio
async def test_missing_issued_at_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()
    token = jwt.encode(
        {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": "user-123",
            "exp": int(datetime.now(UTC).timestamp()) + 300,
        },
        private_pem(private_key),
        algorithm="RS256",
        headers={"kid": KID},
    )

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(token)


@pytest.mark.asyncio
async def test_future_issued_at_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(
            mint_access_token(
                private_key,
                claims={"iat": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())},
            )
        )


@pytest.mark.asyncio
async def test_missing_subject_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"iss": _ISSUER, "aud": _AUDIENCE, "exp": now + 300},
        private_pem(private_key),
        algorithm="RS256",
        headers={"kid": KID},
    )

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(token)


@pytest.mark.asyncio
async def test_hs256_algorithm_confusion_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()
    now = int(datetime.now(UTC).timestamp())
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    token = jwt.encode(
        {"iss": _ISSUER, "aud": _AUDIENCE, "sub": "user-123", "exp": now + 300},
        public_key_bytes,
        algorithm="HS256",
        headers={"kid": KID},
    )

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(token)


@pytest.mark.asyncio
async def test_alg_none_token_fails_closed() -> None:
    authenticator, _, _ = make_authenticator()
    now = int(datetime.now(UTC).timestamp())
    token = jwt.encode(
        {"iss": _ISSUER, "aud": _AUDIENCE, "sub": "user-123", "exp": now + 300},
        key="",
        algorithm="none",
    )

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(token)


@pytest.mark.asyncio
async def test_unknown_kid_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(private_key, kid="rotated-away-key"))


@pytest.mark.asyncio
async def test_missing_kid_fails_closed() -> None:
    authenticator, private_key, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(private_key, kid=None))


@pytest.mark.asyncio
async def test_jwks_fetcher_failure_fails_closed() -> None:
    private_key = generate_signing_key()
    authenticator = OidcTokenAuthenticator(authority_config(), FailingJwksFetcher())

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(private_key))


@pytest.mark.asyncio
async def test_non_jwt_bearer_fails_closed() -> None:
    authenticator, _, _ = make_authenticator()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate("only-two-segments.here")


@pytest.mark.asyncio
async def test_wrong_signing_key_fails_closed() -> None:
    authenticator, _, _ = make_authenticator()
    attacker_key = generate_signing_key()

    with pytest.raises(OidcAuthenticationRequired):
        await authenticator.authenticate(mint_access_token(attacker_key))


@pytest.mark.asyncio
async def test_authenticator_delegates_jwks_retrieval_to_fetcher() -> None:
    authenticator, private_key, fetcher = make_authenticator()

    await authenticator.authenticate(mint_access_token(private_key))
    await authenticator.authenticate(mint_access_token(private_key))

    assert fetcher.calls == 2


@pytest.mark.asyncio
async def test_httpx_fetcher_uses_http_and_caches_per_instance() -> None:
    jwks_document: dict[str, Any] = {
        "keys": [rsa_jwk(generate_signing_key().public_key().public_numbers(), kid=KID)]
    }
    requests_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(str(request.url))
        return httpx.Response(200, json=jwks_document)

    fetcher = HttpxJwksFetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        await fetcher.fetch(JWKS_URI)
        await fetcher.fetch(JWKS_URI)
    finally:
        await fetcher.aclose()

    assert requests_seen == [JWKS_URI]


class RecordingNativeResolver:
    def __init__(self) -> None:
        self.calls: list[Request] = []

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        self.calls.append(request)
        return _fake_http_subject("native_session")


class RecordingOidcResolver:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[Request] = []
        self._error = error

    async def resolve_subject(self, request: Request) -> AuthenticatedHttpSubject:
        self.calls.append(request)
        if self._error is not None:
            raise self._error
        return _fake_http_subject("oidc_token")


class StaticWorkloadReader:
    def __init__(self, snapshot: WorkloadCredentialSnapshot) -> None:
        self.snapshot = snapshot

    async def read_workload_credential(
        self, *, credential_id: UUID
    ) -> WorkloadCredentialSnapshot | None:
        if credential_id != self.snapshot.credential_id:
            return None
        return self.snapshot


def _workload_snapshot(*, secret: str) -> WorkloadCredentialSnapshot:
    return WorkloadCredentialSnapshot(
        credential_id=uuid4(),
        workload_identity_id=uuid4(),
        identity_authority_id=uuid4(),
        workload_kind=WorkloadKind.AGENT,
        token_digest=hashlib.sha256(secret.encode("utf-8")).digest(),
        credential_status=WorkloadCredentialStatus.ACTIVE,
        identity_status=WorkloadIdentityStatus.ACTIVE,
        authority_status=WorkloadAuthorityStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _fake_http_subject(method: str) -> AuthenticatedHttpSubject:
    return AuthenticatedHttpSubject(
        subject=AuthenticatedSubject(
            authority_id=str(uuid4()),
            subject_id="subject-1",
            subject_class=AuthenticatedSubjectClass.HUMAN,
        ),
        authentication_method=method,
    )


def _dispatch_resolver(
    *,
    native: RecordingNativeResolver,
    oidc: RecordingOidcResolver | None,
    workload_secret: str = "workload-secret",
) -> tuple[DispatchedBearerSubjectResolver, WorkloadCredentialSnapshot]:
    snapshot = _workload_snapshot(secret=workload_secret)
    reader = StaticWorkloadReader(snapshot)
    resolver = DispatchedBearerSubjectResolver(
        native_subject_resolver=native,
        workload_authenticator=WorkloadCredentialAuthenticator(reader),
        workload_credential_reader=reader,
        oidc_subject_resolver=oidc,
    )
    return resolver, snapshot


@pytest.mark.asyncio
async def test_jwt_shaped_token_dispatches_to_oidc_without_native_fallthrough() -> None:
    native = RecordingNativeResolver()
    oidc = RecordingOidcResolver()
    resolver, _snapshot = _dispatch_resolver(native=native, oidc=oidc)

    resolved = await resolver.resolve_subject(bearer_request("header.payload.signature"))

    assert resolved.authentication_method == "oidc_token"
    assert len(oidc.calls) == 1
    assert native.calls == []


@pytest.mark.asyncio
async def test_oidc_failure_does_not_fall_through_to_native() -> None:
    native = RecordingNativeResolver()
    oidc = RecordingOidcResolver(error=OidcAuthenticationRequired("invalid"))
    resolver, _snapshot = _dispatch_resolver(native=native, oidc=oidc)

    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(bearer_request("header.payload.signature"))

    assert native.calls == []


@pytest.mark.asyncio
async def test_jwt_shaped_token_without_oidc_arm_fails_closed() -> None:
    native = RecordingNativeResolver()
    resolver, _snapshot = _dispatch_resolver(native=native, oidc=None)

    with pytest.raises(AuthenticationRequired):
        await resolver.resolve_subject(bearer_request("header.payload.signature"))

    assert native.calls == []


@pytest.mark.asyncio
async def test_single_dot_unknown_token_id_still_takes_native_path() -> None:
    native = RecordingNativeResolver()
    oidc = RecordingOidcResolver()
    resolver, _snapshot = _dispatch_resolver(native=native, oidc=oidc)

    await resolver.resolve_subject(bearer_request(f"{uuid4()}.native-secret"))

    assert len(native.calls) == 1
    assert oidc.calls == []


@pytest.mark.asyncio
async def test_workload_shaped_token_still_dispatches_to_workload_path() -> None:
    secret = "workload-secret"
    native = RecordingNativeResolver()
    oidc = RecordingOidcResolver()
    resolver, snapshot = _dispatch_resolver(native=native, oidc=oidc, workload_secret=secret)
    token = f"{snapshot.credential_id}.{secret}"

    resolved = await resolver.resolve_subject(bearer_request(token))

    assert resolved.authentication_method == "workload_credential"
    assert native.calls == []
    assert oidc.calls == []


@pytest.mark.asyncio
async def test_two_dot_token_is_never_parsed_as_workload_credential() -> None:
    native = RecordingNativeResolver()
    oidc = RecordingOidcResolver(error=OidcAuthenticationRequired("invalid"))
    resolver, _snapshot = _dispatch_resolver(native=native, oidc=oidc)

    with pytest.raises(OidcAuthenticationRequired):
        await resolver.resolve_subject(bearer_request("not-a-uuid.mid.secret"))

    assert native.calls == []
    assert len(oidc.calls) == 1
