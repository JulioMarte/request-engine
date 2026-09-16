"""End-to-end HTTP proof for OIDC as the second identity-link proof.

Protects ``INV-IDENTITY-LINK-SELF-001`` for the federated path: a HUMAN actor
with a current ``identity.link_self`` grant and a fresh reauthentication creates
an intent targeting an active OIDC authority, then confirms it with a verified
RS256 ``at+jwt`` access token. The verified subject becomes a second active
binding for the SAME tenant Principal.

No network is used: the provider JWKS is served through an ``httpx.MockTransport``
and tokens are minted locally. The negative matrix covers wrong audience/issuer,
expiry, ID-token ``typ``, HS256, unknown ``kid``, a token from another authority,
a subject already linked and a deployment without the OIDC verifier.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import (
    build_identity_link_verifier,
    build_native_auth_runtime,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.oidc_auth import HttpxJwksFetcher, rsa_jwk

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

_SIGNING_KEY = b"native-identity-link-oidc-e2e-key-v1"
_LINK_CAPABILITY = "identity.link_self"
_CREATE_PATH = "/v1/me/identity-link-intents"
_OIDC_ISSUER = "https://idp-a.example.test"
_OIDC_AUDIENCE = "request-engine"
_OIDC_JWKS_URI = "https://idp-a.example.test/.well-known/jwks.json"
_OIDC_KID = "oidc-link-key-1"
_OTHER_ISSUER = "https://idp-b.example.test"
_OTHER_KID = "oidc-link-key-2"
_SUBJECT = "federated-user-1"


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_native_authority(conn: PgConnection) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
        VALUES ('native', %s) RETURNING id
        """,
        (f"native-identity-link-oidc-{uuid4().hex}",),
    )


def _create_oidc_authority(
    conn: PgConnection,
    *,
    issuer: str = _OIDC_ISSUER,
    jwks_uri: str = _OIDC_JWKS_URI,
    audience: str = _OIDC_AUDIENCE,
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment, status, configuration_ref
        ) VALUES ('oidc', %s, 'active', %s) RETURNING id
        """,
        (issuer, json.dumps({"jwks_uri": jwks_uri, "audience": audience})),
    )


def _provision_tenant_root(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"identity-link-oidc-platform-{uuid4().hex}",),
    )
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (
            %s, 'platform', 'platform', 'organization.provision', false,
            'trust_bootstrap', %s
        )
        """,
        (provisioner_id, f"identity-link-oidc-root:{uuid4().hex}"),
    )
    revision_row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (provisioner_id,),
    ).fetchone()
    assert revision_row is not None

    organization_id = uuid4()
    organization_party_id = uuid4()
    controller_principal_id = uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(int(revision_row[0])),),
    )
    conn.execute("SET ROLE request_platform_control")
    try:
        row = conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"identity-link-oidc-{organization_id.hex}",
                "Identity Link OIDC E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"identity-link-oidc-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _grant_link(conn: PgConnection, *, organization_id: UUID, principal_id: UUID) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            %s, %s, 'tenant', 'tenant_control', %s, true, %s,
            'authority_management', %s
        )
        """,
        (
            organization_id,
            principal_id,
            _LINK_CAPABILITY,
            principal_id,
            f"identity-link-oidc-grant:{uuid4().hex}",
        ),
    )


def _binding_state(
    conn: PgConnection, *, organization_id: UUID, principal_id: UUID
) -> tuple[UUID, int]:
    row = conn.execute(
        """
        SELECT id, revision FROM request_engine.identity_bindings
         WHERE organization_id = %s AND principal_id = %s
           AND principal_plane = 'tenant' AND status = 'active'
        """,
        (organization_id, principal_id),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0]), int(row[1])


def _tenant_headers(*, token: str, organization_id: UUID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }


async def _login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


def _generate_signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _private_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _mint_access_token(
    private_key: rsa.RSAPrivateKey,
    *,
    subject: str = _SUBJECT,
    issuer: str = _OIDC_ISSUER,
    audience: str = _OIDC_AUDIENCE,
    kid: str = _OIDC_KID,
    token_type: str = "at+jwt",
    algorithm: str = "RS256",
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    expiry = expires_at if expires_at is not None else now + timedelta(minutes=10)
    payload = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "exp": int(expiry.timestamp()),
        "iat": int(now.timestamp()),
        "client_id": "clinic-web",
        "jti": str(uuid4()),
    }
    if algorithm == "HS256":
        return str(
            jwt.encode(
                payload,
                "shared-secret-key-for-hs256-tests-32bytes",
                algorithm="HS256",
                headers={"kid": kid, "typ": token_type},
            )
        )
    return str(
        jwt.encode(
            payload,
            _private_pem(private_key),
            algorithm="RS256",
            headers={"kid": kid, "typ": token_type},
        )
    )


def _jwks_fetcher(documents: dict[str, dict[str, Any]]) -> HttpxJwksFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        document = documents.get(str(request.url))
        if document is None:
            return httpx.Response(404)
        return httpx.Response(200, json=document)

    return HttpxJwksFetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def _enroll_root(
    session_factory: SessionFactory,
    native_authority_id: UUID,
) -> tuple[str, str, UUID]:
    runtime = build_native_auth_runtime(session_factory)
    password = "identity-link-oidc-root-password-1"
    identity = await runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=f"identity-link-oidc-root-{uuid4().hex}@example.test",
        password=password,
    )
    return identity.login_handle, password, identity.native_identity_id


async def _reauth(client: AsyncClient, *, headers: dict[str, str], password: str) -> None:
    response = await client.post(
        "/auth/native/sessions:reauth",
        headers=headers,
        json={"password": password},
    )
    assert response.status_code == 200, response.text


async def _create_intent(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    target_authority_id: UUID,
    idempotency_key: str,
) -> UUID:
    response = await client.post(
        _CREATE_PATH,
        headers={**headers, "Idempotency-Key": idempotency_key},
        json={
            "target_authority_id": str(target_authority_id),
            "provenance_reference": "e2e-oidc-link",
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["intent_id"])


async def _confirm_oidc(
    client: AsyncClient,
    *,
    headers: dict[str, str],
    intent_id: UUID,
    access_token: str,
    expected_revision: int,
    idempotency_key: str,
) -> httpx.Response:
    return await client.post(
        f"{_CREATE_PATH}/{intent_id}:confirm",
        headers={**headers, "Idempotency-Key": idempotency_key},
        json={
            "proof": {"kind": "oidc", "access_token": access_token},
            "expected_actor_binding_revision": expected_revision,
            "provenance_reference": "e2e-oidc-link",
        },
    )


@pytest.mark.asyncio
async def test_oidc_second_proof_links_subject_and_rejects_invalid_proofs(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    signing_key = _generate_signing_key()
    jwks_document = {"keys": [rsa_jwk(signing_key.public_key().public_numbers(), kid=_OIDC_KID)]}
    fetcher = _jwks_fetcher({_OIDC_JWKS_URI: jwks_document})
    verifier = build_identity_link_verifier(e2e_session_factory, jwks_fetcher=fetcher)

    native_authority = _create_native_authority(e2e_admin_conn)
    login_handle, password, native_identity_id = await _enroll_root(
        e2e_session_factory, native_authority
    )
    organization_id, controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=native_authority,
        native_identity_id=native_identity_id,
    )
    oidc_authority = _create_oidc_authority(e2e_admin_conn)
    _grant_link(e2e_admin_conn, organization_id=organization_id, principal_id=controller_id)
    _controller_binding_id, controller_binding_revision = _binding_state(
        e2e_admin_conn, organization_id=organization_id, principal_id=controller_id
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=native_authority,
        appointment_option_signing_key=_SIGNING_KEY,
        identity_link_verifier=verifier,
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            root_token = await _login(client, login_handle=login_handle, password=password)
            headers = _tenant_headers(token=root_token, organization_id=organization_id)
            await _reauth(client, headers=headers, password=password)

            intent_id = await _create_intent(
                client,
                headers=headers,
                target_authority_id=oidc_authority,
                idempotency_key="oidc-link-create-1",
            )
            token = _mint_access_token(signing_key)
            confirmed = await _confirm_oidc(
                client,
                headers=headers,
                intent_id=intent_id,
                access_token=token,
                expected_revision=controller_binding_revision,
                idempotency_key="oidc-link-confirm-1",
            )
            assert confirmed.status_code == 200, confirmed.text
            assert confirmed.headers["cache-control"] == "no-store"
            assert confirmed.json()["principal_id"] == str(controller_id)
            new_binding_id = UUID(confirmed.json()["binding_id"])
            row = e2e_admin_conn.execute(
                "SELECT principal_id, subject_id, identity_authority_id, status "
                "FROM request_engine.identity_bindings WHERE id = %s",
                (new_binding_id,),
            ).fetchone()
            assert row == (controller_id, _SUBJECT, oidc_authority, "active")
            assert e2e_admin_conn.execute(
                "SELECT status FROM request_engine.identity_link_intents WHERE id = %s",
                (intent_id,),
            ).fetchone() == ("consumed",)
            assert token not in confirmed.text

            # A single still-pending intent carries every rejected confirmation:
            # each failure leaves the intent pending, so the subject cannot be
            # taken over and every bad proof is rejected without side effects.
            negative_intent = await _create_intent(
                client,
                headers=headers,
                target_authority_id=oidc_authority,
                idempotency_key="oidc-link-create-negative",
            )

            # The same live subject cannot be taken over by a second intent.
            takeover = await _confirm_oidc(
                client,
                headers=headers,
                intent_id=negative_intent,
                access_token=_mint_access_token(signing_key),
                expected_revision=controller_binding_revision,
                idempotency_key="oidc-link-confirm-takeover",
            )
            assert takeover.status_code == 409, takeover.text

            # Every invalid proof is the same opaque 401 as an invalid login.
            other_key = _generate_signing_key()
            invalid_proofs = {
                "wrong_audience": _mint_access_token(signing_key, audience="other-audience"),
                "wrong_issuer": _mint_access_token(signing_key, issuer=_OTHER_ISSUER),
                "expired": _mint_access_token(
                    signing_key, expires_at=datetime.now(UTC) - timedelta(minutes=5)
                ),
                "id_token_typ": _mint_access_token(signing_key, token_type="JWT"),
                "hs256": _mint_access_token(signing_key, algorithm="HS256"),
                "unknown_kid": _mint_access_token(signing_key, kid="unknown-kid"),
                "foreign_authority": _mint_access_token(
                    other_key, issuer=_OTHER_ISSUER, kid=_OTHER_KID
                ),
            }
            for label, bad_token in invalid_proofs.items():
                rejected = await _confirm_oidc(
                    client,
                    headers=headers,
                    intent_id=negative_intent,
                    access_token=bad_token,
                    expected_revision=controller_binding_revision,
                    idempotency_key=f"oidc-link-confirm-{label}",
                )
                assert rejected.status_code == 401, f"{label}: {rejected.text}"
                assert rejected.json()["error"]["code"] == "credential_invalid", label
                assert bad_token not in rejected.text
                assert e2e_admin_conn.execute(
                    "SELECT status FROM request_engine.identity_link_intents WHERE id = %s",
                    (negative_intent,),
                ).fetchone() == ("pending",)
    finally:
        await verifier.aclose()
        await fetcher.aclose()


@pytest.mark.asyncio
async def test_oidc_proof_without_a_configured_verifier_is_cleanly_rejected(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    native_authority = _create_native_authority(e2e_admin_conn)
    login_handle, password, native_identity_id = await _enroll_root(
        e2e_session_factory, native_authority
    )
    organization_id, controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=native_authority,
        native_identity_id=native_identity_id,
    )
    oidc_authority = _create_oidc_authority(e2e_admin_conn)
    _grant_link(e2e_admin_conn, organization_id=organization_id, principal_id=controller_id)
    _controller_binding_id, controller_binding_revision = _binding_state(
        e2e_admin_conn, organization_id=organization_id, principal_id=controller_id
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=native_authority,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root_token = await _login(client, login_handle=login_handle, password=password)
        headers = _tenant_headers(token=root_token, organization_id=organization_id)
        await _reauth(client, headers=headers, password=password)
        intent_id = await _create_intent(
            client,
            headers=headers,
            target_authority_id=oidc_authority,
            idempotency_key="oidc-link-create-unconfigured",
        )
        rejected = await _confirm_oidc(
            client,
            headers=headers,
            intent_id=intent_id,
            access_token="not-even-a-jwt",
            expected_revision=controller_binding_revision,
            idempotency_key="oidc-link-confirm-unconfigured",
        )
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["error"]["code"] == "identity_link_not_configured"
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.identity_link_intents WHERE id = %s",
            (intent_id,),
        ).fetchone() == ("pending",)
