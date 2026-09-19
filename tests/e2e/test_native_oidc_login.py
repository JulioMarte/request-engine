"""Optional OIDC arm E2E: federated HUMAN bearers reach RE authority only via bindings.

The OIDC arm is optional at composition. This suite proves both sides:

1. with the arm composed, a verified OIDC JWT for a bound HUMAN subject acts as
   that Principal through the same IdentityBinding + capability path as native
   sessions, and every failure (expired, unbound, wrong tenant, unfederated
   issuer) fails closed;
2. without the arm, the same deployment rejects a JWT-shaped bearer exactly as
   before (401 authentication_required), so zero-IdP behavior is unchanged.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import (
    build_native_auth_runtime,
    build_oidc_subject_resolver,
)
from request_engine.platform.db.oidc_authority_reader import PostgresOidcAuthorityReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_human_auth import NativeIdentityEnrollment
from request_engine.platform.security.oidc_auth import HttpxJwksFetcher, rsa_jwk

from .native_provisioning_support import (
    PgConnection,
    grant_controller_delegable_operational_authority,
    login,
    provision_tenant_root,
    tenant_headers,
    uuid_row,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.adversarial,
]

_SIGNING_KEY = b"native-oidc-e2e-appointment-signing-key-v1"
_OIDC_ISSUER = "https://idp.example.test"
_OIDC_AUDIENCE = "request-engine"
_OIDC_JWKS_URI = "https://idp.example.test/.well-known/jwks.json"
_OIDC_KID = "oidc-e2e-key-1"
_BOUND_SUBJECT = "user-123"
_OTHER_ISSUER = "https://idp-b.example.test"
_OTHER_JWKS_URI = "https://idp-b.example.test/.well-known/jwks.json"
_OTHER_KID = "oidc-e2e-key-2"
_OTHER_SUBJECT = "user-456"


def _generate_signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _mint_access_token(
    private_key: rsa.RSAPrivateKey,
    *,
    subject: str = _BOUND_SUBJECT,
    issuer: str = _OIDC_ISSUER,
    audience: str = _OIDC_AUDIENCE,
    kid: str = _OIDC_KID,
    expires_at: datetime | None = None,
    email: str | None = None,
) -> str:
    now = datetime.now(UTC)
    expiry = expires_at if expires_at is not None else now + timedelta(minutes=10)
    return str(
        jwt.encode(
            {
                "iss": issuer,
                "aud": audience,
                "sub": subject,
                "exp": int(expiry.timestamp()),
                "iat": int(now.timestamp()),
                "email": email if email is not None else f"{subject}@example.test",
                "client_id": "clinic-web",
                "jti": str(uuid4()),
            },
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ),
            algorithm="RS256",
            headers={"kid": kid, "typ": "at+jwt"},
        )
    )


def _oidc_authority(
    conn: PgConnection,
    *,
    issuer: str = _OIDC_ISSUER,
    jwks_uri: str = _OIDC_JWKS_URI,
    audience: str = _OIDC_AUDIENCE,
) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment, status, configuration_ref
        ) VALUES ('oidc', %s, 'active', %s) RETURNING id
        """,
        (issuer, json.dumps({"jwks_uri": jwks_uri, "audience": audience})),
    )


def _bind_oidc_subject(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    identity_authority_id: UUID,
    subject_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.identity_bindings (
            organization_id, principal_id, principal_plane,
            identity_authority_id, subject_id, status
        ) VALUES (%s, %s, 'tenant', %s, %s, 'active')
        """,
        (organization_id, principal_id, identity_authority_id, subject_id),
    )


def _jwks_fetcher(documents: dict[str, dict[str, Any]]) -> HttpxJwksFetcher:
    def handler(request: httpx.Request) -> httpx.Response:
        document = documents.get(str(request.url))
        if document is None:
            return httpx.Response(404)
        return httpx.Response(200, json=document)

    return HttpxJwksFetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _native_authority(conn: PgConnection) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"native-oidc-e2e-{uuid4().hex}",),
    )


async def _enroll_root(
    session_factory: SessionFactory,
    native_authority_id: UUID,
) -> tuple[NativeIdentityEnrollment, str]:
    enrollment_runtime = build_native_auth_runtime(session_factory)
    password = "oidc-e2e-root-password-1"
    identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=f"oidc-root-{uuid4().hex}@example.test",
        password=password,
    )
    return identity, password


@pytest.mark.asyncio
async def test_oidc_bearer_acts_through_identity_binding_and_optional_arm_stays_optional(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    signing_key = _generate_signing_key()
    jwks_document = {"keys": [rsa_jwk(signing_key.public_key().public_numbers(), kid=_OIDC_KID)]}

    # Tenant one: the tenant whose controller is federated through OIDC.
    org1_native_authority = _native_authority(e2e_admin_conn)
    root_identity, root_password = await _enroll_root(e2e_session_factory, org1_native_authority)
    organization_id, controller_principal_id = provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=org1_native_authority,
        native_identity_id=root_identity.native_identity_id,
    )

    # Tenant two: a second tenant the federated subject is NOT bound to.
    org2_native_authority = _native_authority(e2e_admin_conn)
    org2_root_identity, _ = await _enroll_root(e2e_session_factory, org2_native_authority)
    other_organization_id, _ = provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=org2_native_authority,
        native_identity_id=org2_root_identity.native_identity_id,
    )

    oidc_authority_id = _oidc_authority(e2e_admin_conn)
    grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        capability_key="parties.lookup",
    )
    grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        capability_key="parties.register",
    )

    # The OIDC authority read boundary must expose the seeded authority to the
    # runtime role through the composed resolver helper.
    configs = await PostgresOidcAuthorityReader(e2e_session_factory).read_active_authorities()
    assert UUID(str(oidc_authority_id)) in {config.authority_id for config in configs}

    fetcher = _jwks_fetcher({_OIDC_JWKS_URI: jwks_document})
    oidc_resolver = await build_oidc_subject_resolver(e2e_session_factory, jwks_fetcher=fetcher)

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=org1_native_authority,
        appointment_option_signing_key=_SIGNING_KEY,
        oidc_subject_resolver=oidc_resolver,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        native_token = await login(
            client, login_handle=root_identity.login_handle, password=root_password
        )
        # Native business facts exist BEFORE federation; the API creates them.
        patient_name = f"OIDC migration patient {uuid4().hex}"
        registered = await client.post(
            "/v1/parties",
            headers=tenant_headers(
                token=native_token,
                organization_id=organization_id,
                idempotency_key=f"native-oidc-party-{uuid4().hex}",
            ),
            json={"party_kind": "person", "display_name": patient_name, "contact_points": []},
        )
        assert registered.status_code == 201, registered.text
        patient_id = UUID(registered.json()["party_id"])
        original_authority = _authority_facts(e2e_admin_conn, organization_id)
        original_audit = e2e_admin_conn.execute(
            """SELECT to_jsonb(a) FROM request_engine.audit_records a
                 WHERE organization_id = %s AND aggregate_id = %s
                   AND command_name = 'parties.register' ORDER BY id""",
            (organization_id, patient_id),
        ).fetchall()
        assert len(original_audit) == 1
        assert original_audit[0][0]["actor_principal_id"] == str(controller_principal_id)

        # Matching a native login email must not manufacture a binding.
        same_email = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=_mint_access_token(signing_key, email=root_identity.login_handle),
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": patient_name},
        )
        assert same_email.status_code == 403, same_email.text
        assert same_email.json()["error"]["code"] == "identity_not_bound"
        assert e2e_admin_conn.execute(
            """SELECT count(*) FROM request_engine.identity_bindings
                 WHERE identity_authority_id = %s""",
            (oidc_authority_id,),
        ).fetchone() == (0,)

        # Explicit trusted link is a precondition, never email auto-linking.
        # This tests auth/data portability, not an administrative linking API.
        _bind_oidc_subject(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=controller_principal_id,
            identity_authority_id=oidc_authority_id,
            subject_id=_BOUND_SUBJECT,
        )
        valid_token = _mint_access_token(signing_key)

        native_patient = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=native_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        federated_patient = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=valid_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        assert native_patient.status_code == federated_patient.status_code == 200
        assert native_patient.json() == federated_patient.json()
        assert str(patient_id) in {item["party_id"] for item in federated_patient.json()}

        # Disable the old authentication route; the same existing session is denied,
        # while OIDC continues to reach the original business data and authority.
        e2e_admin_conn.execute(
            """UPDATE request_engine.identity_bindings
                  SET status = 'suspended', revision = revision + 1
                WHERE identity_authority_id = %s AND principal_id = %s""",
            (org1_native_authority, controller_principal_id),
        )
        suspended_native = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=native_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        assert suspended_native.status_code == 403, suspended_native.text
        assert suspended_native.json()["error"]["code"] == "identity_binding_suspended"

        bound_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=valid_token, organization_id=organization_id),
            params={"mode": "name", "value": "nobody"},
        )
        assert bound_lookup.status_code == 200, bound_lookup.text
        assert "error" not in bound_lookup.json()
        assert _authority_facts(e2e_admin_conn, organization_id) == original_authority

        # Restore native fallback before disabling the external authority.
        e2e_admin_conn.execute(
            """UPDATE request_engine.identity_bindings
                  SET status = 'active', revision = revision + 1
                WHERE identity_authority_id = %s AND principal_id = %s""",
            (org1_native_authority, controller_principal_id),
        )

        expired = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=_mint_access_token(
                    signing_key, expires_at=datetime.now(UTC) - timedelta(minutes=5)
                ),
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert expired.status_code == 401, expired.text
        assert expired.json()["error"]["code"] == "credential_invalid"

        unbound = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=_mint_access_token(signing_key, subject="user-999"),
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert unbound.status_code == 403, unbound.text
        assert unbound.json()["error"]["code"] == "identity_not_bound"

        wrong_tenant = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=valid_token, organization_id=other_organization_id),
            params={"mode": "name", "value": "nobody"},
        )
        assert wrong_tenant.status_code == 403, wrong_tenant.text
        assert wrong_tenant.json()["error"]["code"] == "identity_not_bound"

        unfederated_issuer = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=_mint_access_token(signing_key, issuer="https://unfederated.example.test"),
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert unfederated_issuer.status_code == 401, unfederated_issuer.text
        assert unfederated_issuer.json()["error"]["code"] == "credential_invalid"

        # The app and JWKS cache stay alive while trusted configuration is disabled.
        e2e_admin_conn.execute(
            """UPDATE request_engine.identity_authorities
                  SET status = 'disabled', revision = revision + 1 WHERE id = %s""",
            (oidc_authority_id,),
        )
        disabled_authority = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=valid_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        assert disabled_authority.status_code == 401, disabled_authority.text
        e2e_admin_conn.execute(
            """UPDATE request_engine.identity_authorities
                  SET status = 'active', revision = revision + 1 WHERE id = %s""",
            (oidc_authority_id,),
        )
        reenabled = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=valid_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        assert reenabled.status_code == 200, reenabled.text

        # Revocation is a durable prerequisite change; replaying the exact
        # previously accepted token must not recreate its binding or authority.
        e2e_admin_conn.execute(
            """UPDATE request_engine.identity_bindings SET status = 'revoked',
                      revision = revision + 1, revoked_at = clock_timestamp()
                WHERE identity_authority_id = %s AND principal_id = %s""",
            (oidc_authority_id, controller_principal_id),
        )
        revoked_binding = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=valid_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        assert revoked_binding.status_code == 403, revoked_binding.text
        assert revoked_binding.json()["error"]["code"] == "identity_binding_revoked"
        assert e2e_admin_conn.execute(
            """SELECT status FROM request_engine.identity_bindings
                 WHERE identity_authority_id = %s AND principal_id = %s""",
            (oidc_authority_id, controller_principal_id),
        ).fetchall() == [("revoked",)]

    await oidc_resolver.aclose()
    await fetcher.aclose()

    # Optionality proof: the same deployment composed WITHOUT the OIDC arm
    # rejects a JWT-shaped bearer exactly as before this slice existed.
    plain_app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=org1_native_authority,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(
        transport=ASGITransport(app=plain_app), base_url="http://test"
    ) as client:
        native_root_token = await login(
            client, login_handle=root_identity.login_handle, password=root_password
        )
        native_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=native_root_token, organization_id=organization_id),
            params={"mode": "name", "value": "nobody"},
        )
        assert native_lookup.status_code == 200, native_lookup.text
        recovered_patient = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(token=native_root_token, organization_id=organization_id),
            params={"mode": "name", "value": patient_name},
        )
        assert recovered_patient.status_code == 200, recovered_patient.text
        assert recovered_patient.json() == native_patient.json()
        assert _authority_facts(e2e_admin_conn, organization_id) == original_authority
        assert (
            e2e_admin_conn.execute(
                """SELECT to_jsonb(a) FROM request_engine.audit_records a
                 WHERE organization_id = %s AND aggregate_id = %s
                   AND command_name = 'parties.register' ORDER BY id""",
                (organization_id, patient_id),
            ).fetchall()
            == original_audit
        )

        rejected = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=_mint_access_token(signing_key), organization_id=organization_id
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert rejected.status_code == 401, rejected.text
        assert rejected.json()["error"]["code"] == "authentication_required"


async def _register_party(client: AsyncClient, *, token: str, organization_id: UUID) -> UUID:
    name = f"IdP portability patient {uuid4().hex}"
    response = await client.post(
        "/v1/parties",
        headers=tenant_headers(
            token=token,
            organization_id=organization_id,
            idempotency_key=f"idp-portability-{uuid4().hex}",
        ),
        json={"party_kind": "person", "display_name": name, "contact_points": []},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["party_id"])


def _register_actor(conn: PgConnection, *, organization_id: UUID, party_id: UUID) -> Any:
    row = conn.execute(
        """
        SELECT actor_principal_id FROM request_engine.audit_records
         WHERE organization_id = %s AND aggregate_id = %s
           AND command_name = 'parties.register'
         ORDER BY id
        """,
        (organization_id, party_id),
    ).fetchone()
    assert row is not None
    return row[0]


def _tenant_identity_facts(
    conn: PgConnection, organization_id: UUID
) -> tuple[list[Any], list[Any]]:
    """Independent admin oracle: the durable Principal and grant set of one tenant."""
    principals = conn.execute(
        """
        SELECT id, authority_revision FROM request_engine.principals
         WHERE organization_id = %s ORDER BY id
        """,
        (organization_id,),
    ).fetchall()
    grants = conn.execute(
        """
        SELECT id, principal_id, authority_plane, capability_key, delegable, status,
               revision, provenance_kind, provenance_reference
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s ORDER BY id
        """,
        (organization_id,),
    ).fetchall()
    return list(principals), list(grants)


@pytest.mark.invariant
@pytest.mark.asyncio
async def test_switching_identity_provider_keeps_the_same_principal_and_grants(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    """F-02: an external IdP is an authentication route, never an identity authority.

    A native tenant controller binds a subject from provider A and later a
    different subject from provider B. Both federated tokens must resolve to the
    SAME Principal with the SAME standing grants, and retiring provider A must
    neither reconstruct the Principal nor recompute its authority. The only
    faked boundary is the external provider JWKS; tokens are real RS256 and the
    database is real PostgreSQL.
    """
    key_a = _generate_signing_key()
    key_b = _generate_signing_key()
    fetcher = _jwks_fetcher(
        {
            _OIDC_JWKS_URI: {"keys": [rsa_jwk(key_a.public_key().public_numbers(), kid=_OIDC_KID)]},
            _OTHER_JWKS_URI: {
                "keys": [rsa_jwk(key_b.public_key().public_numbers(), kid=_OTHER_KID)]
            },
        }
    )

    native_authority = _native_authority(e2e_admin_conn)
    root_identity, root_password = await _enroll_root(e2e_session_factory, native_authority)
    organization_id, controller_principal_id = provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=native_authority,
        native_identity_id=root_identity.native_identity_id,
    )
    grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        capability_key="parties.register",
    )
    grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        capability_key="parties.lookup",
    )
    authority_a = _oidc_authority(e2e_admin_conn)
    authority_b = _oidc_authority(e2e_admin_conn, issuer=_OTHER_ISSUER, jwks_uri=_OTHER_JWKS_URI)
    before_principals, before_grants = _tenant_identity_facts(e2e_admin_conn, organization_id)

    oidc_resolver = await build_oidc_subject_resolver(e2e_session_factory, jwks_fetcher=fetcher)
    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=native_authority,
        appointment_option_signing_key=_SIGNING_KEY,
        oidc_subject_resolver=oidc_resolver,
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Provider A becomes a second authentication route for the controller.
            _bind_oidc_subject(
                e2e_admin_conn,
                organization_id=organization_id,
                principal_id=controller_principal_id,
                identity_authority_id=authority_a,
                subject_id=_BOUND_SUBJECT,
            )
            token_a = _mint_access_token(
                key_a, subject=_BOUND_SUBJECT, issuer=_OIDC_ISSUER, kid=_OIDC_KID
            )
            party_a = await _register_party(client, token=token_a, organization_id=organization_id)
            assert (
                _register_actor(e2e_admin_conn, organization_id=organization_id, party_id=party_a)
                == controller_principal_id
            )

            # IdP change: another issuer and subject, still the same Principal.
            _bind_oidc_subject(
                e2e_admin_conn,
                organization_id=organization_id,
                principal_id=controller_principal_id,
                identity_authority_id=authority_b,
                subject_id=_OTHER_SUBJECT,
            )
            token_b = _mint_access_token(
                key_b, subject=_OTHER_SUBJECT, issuer=_OTHER_ISSUER, kid=_OTHER_KID
            )
            party_b = await _register_party(client, token=token_b, organization_id=organization_id)
            assert (
                _register_actor(e2e_admin_conn, organization_id=organization_id, party_id=party_b)
                == controller_principal_id
            )

            # Retiring the previous provider leaves the new route and authority intact.
            e2e_admin_conn.execute(
                """UPDATE request_engine.identity_authorities
                      SET status = 'disabled', revision = revision + 1 WHERE id = %s""",
                (authority_a,),
            )
            retired = await client.get(
                "/v1/parties/lookup",
                headers=tenant_headers(token=token_a, organization_id=organization_id),
                params={"mode": "name", "value": "nobody"},
            )
            assert retired.status_code == 401, retired.text
            surviving = await client.get(
                "/v1/parties/lookup",
                headers=tenant_headers(token=token_b, organization_id=organization_id),
                params={"mode": "name", "value": "nobody"},
            )
            assert surviving.status_code == 200, surviving.text

        after_principals, after_grants = _tenant_identity_facts(e2e_admin_conn, organization_id)
        assert {row[0] for row in after_principals} == {row[0] for row in before_principals}
        before_revision = {row[0]: row[1] for row in before_principals}
        for principal_id, revision in ((row[0], row[1]) for row in after_principals):
            assert revision >= before_revision[principal_id]
        assert after_grants == before_grants

        # Zero-IdP operation: the same deployment without the OIDC arm keeps the
        # native path working for the same Principal.
        plain_app = create_native_app(
            session_factory=e2e_session_factory,
            native_identity_authority_id=native_authority,
            appointment_option_signing_key=_SIGNING_KEY,
        )
        async with AsyncClient(
            transport=ASGITransport(app=plain_app), base_url="http://test"
        ) as client:
            native_token = await login(
                client, login_handle=root_identity.login_handle, password=root_password
            )
            native_party = await _register_party(
                client, token=native_token, organization_id=organization_id
            )
            assert (
                _register_actor(
                    e2e_admin_conn, organization_id=organization_id, party_id=native_party
                )
                == controller_principal_id
            )
    finally:
        await oidc_resolver.aclose()
        await fetcher.aclose()


def _authority_facts(conn: PgConnection, organization_id: UUID) -> list[Any]:
    """Identity methods may change; security actors and their authority must survive."""
    return conn.execute(
        """
        -- Binding changes invalidate authority snapshots and touch updated_at;
        -- neither represents replacement of the Principal or its authority.
        SELECT 'principals', to_jsonb(p) - 'authority_revision' - 'updated_at'
          FROM request_engine.principals p WHERE organization_id = %s
        UNION ALL
        SELECT 'grants', to_jsonb(g)
          FROM request_engine.principal_authority_grants g WHERE organization_id = %s
        UNION ALL
        SELECT 'memberships', to_jsonb(m)
          FROM request_engine.staff_memberships m WHERE organization_id = %s
        UNION ALL
        SELECT 'representations', to_jsonb(r)
          FROM request_engine.representations r WHERE organization_id = %s
        ORDER BY 1, 2
        """,
        (organization_id,) * 4,
    ).fetchall()
