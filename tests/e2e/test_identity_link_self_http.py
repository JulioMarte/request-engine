"""End-to-end HTTP proof for self-service dual-proof identity linking.

Protects ``INV-IDENTITY-LINK-SELF-001``: a HUMAN actor with a current
``identity.link_self`` grant and a fresh reauthentication creates a short-TTL
intent and confirms it with the second identity's password, producing a second
active binding for the SAME tenant Principal. The negative matrix covers stale
freshness, wrong proof, idempotency conflict under a different second identity,
foreign intent opacity and the published operation identity.
"""

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.native_auth import issue_opaque_token

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]
_SIGNING_KEY = b"native-identity-link-self-e2e-key-v1"
_LINK_CAPABILITY = "identity.link_self"
_CREATE_PATH = "/v1/me/identity-link-intents"


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
        (f"native-identity-link-self-{uuid4().hex}",),
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
        (f"identity-link-platform-{uuid4().hex}",),
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
        (provisioner_id, f"identity-link-root:{uuid4().hex}"),
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
                f"identity-link-{organization_id.hex}",
                "Identity Link Self E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"identity-link-root:{uuid4().hex}",
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
            f"identity-link-grant:{uuid4().hex}",
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


def _backdated_session_token(conn: PgConnection, *, native_identity_id: UUID) -> str:
    """Insert a genuinely stale native session with a client-known raw token."""

    token = issue_opaque_token()
    conn.execute(
        """
        INSERT INTO request_engine.native_sessions (
            id, native_identity_id, credential_id, token_digest, token_fingerprint,
            session_epoch, created_at, expires_at
        )
        SELECT %s, identity.id, credential.id, %s, %s, identity.session_epoch,
               clock_timestamp() - interval '10 minutes',
               clock_timestamp() + interval '1 hour'
          FROM request_engine.native_identities AS identity
          JOIN request_engine.native_credentials AS credential
            ON credential.native_identity_id = identity.id
           AND credential.kind = 'password' AND credential.status = 'active'
         WHERE identity.id = %s
         LIMIT 1
        """,
        (
            token.token_id,
            token.digest,
            token.fingerprint,
            native_identity_id,
        ),
    )
    return token.raw_token


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


@pytest.mark.asyncio
async def test_self_service_identity_link_over_http(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "identity-link-self-root-password-1"
    second_password = "identity-link-self-second-password-2"
    other_password = "identity-link-self-other-password-3"
    root_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"identity-link-root-{uuid4().hex}@example.test",
        password=root_password,
    )
    second_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"identity-link-second-{uuid4().hex}@example.test",
        password=second_password,
    )
    other_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"identity-link-other-{uuid4().hex}@example.test",
        password=other_password,
    )
    foreign_identity = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"identity-link-foreign-{uuid4().hex}@example.test",
        password="identity-link-self-foreign-password-4",
    )
    organization_id, controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    foreign_organization_id, foreign_controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=foreign_identity.native_identity_id,
    )
    _grant_link(e2e_admin_conn, organization_id=organization_id, principal_id=controller_id)
    _grant_link(
        e2e_admin_conn,
        organization_id=foreign_organization_id,
        principal_id=foreign_controller_id,
    )
    controller_binding_id, controller_binding_revision = _binding_state(
        e2e_admin_conn, organization_id=organization_id, principal_id=controller_id
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root_token = await _login(
            client, login_handle=root_identity.login_handle, password=root_password
        )
        headers = _tenant_headers(token=root_token, organization_id=organization_id)

        # Establish an explicit recent reauthentication of the current identity.
        reauth = await client.post(
            "/auth/native/sessions:reauth",
            headers=headers,
            json={"password": root_password},
        )
        assert reauth.status_code == 200, reauth.text

        # An unauthenticated caller cannot create an intent.
        assert (await client.post(_CREATE_PATH, json={})).status_code == 401

        created = await client.post(
            _CREATE_PATH,
            headers={**headers, "Idempotency-Key": "link-create-1"},
            json={"target_authority_id": str(authority_id), "provenance_reference": "e2e-link"},
        )
        assert created.status_code == 201, created.text
        assert created.headers["cache-control"] == "no-store"
        assert set(created.json()) == {"intent_id", "expires_at", "target_authority_id"}
        assert created.json()["target_authority_id"] == str(authority_id)
        intent_id = UUID(created.json()["intent_id"])

        confirmed = await client.post(
            f"{_CREATE_PATH}/{intent_id}:confirm",
            headers={**headers, "Idempotency-Key": "link-confirm-1"},
            json={
                "proof": {
                    "target_authority_id": str(authority_id),
                    "native_identity_id": str(second_identity.native_identity_id),
                    "login_handle": second_identity.login_handle,
                    "password": second_password,
                },
                "expected_actor_binding_revision": controller_binding_revision,
                "provenance_reference": "e2e-link",
            },
        )
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.headers["cache-control"] == "no-store"
        assert set(confirmed.json()) == {"binding_id", "principal_id", "binding_revision"}
        assert confirmed.json()["principal_id"] == str(controller_id)
        new_binding_id = UUID(confirmed.json()["binding_id"])
        assert new_binding_id != controller_binding_id
        row = e2e_admin_conn.execute(
            "SELECT principal_id, subject_id, status FROM request_engine.identity_bindings "
            "WHERE id = %s",
            (new_binding_id,),
        ).fetchone()
        assert row == (controller_id, str(second_identity.native_identity_id), "active")
        assert e2e_admin_conn.execute(
            "SELECT status FROM request_engine.identity_link_intents WHERE id = %s",
            (intent_id,),
        ).fetchone() == ("consumed",)
        assert e2e_admin_conn.execute(
            "SELECT action FROM request_engine.identity_link_facts "
            "WHERE intent_id = %s ORDER BY created_at, id",
            (intent_id,),
        ).fetchall() == [("intent_created",), ("linked",)]

        # Replaying the exact confirmation returns a receipt without proof.
        replay = await client.post(
            f"{_CREATE_PATH}/{intent_id}:confirm",
            headers={**headers, "Idempotency-Key": "link-confirm-1"},
            json={
                "proof": {
                    "target_authority_id": str(authority_id),
                    "native_identity_id": str(second_identity.native_identity_id),
                    "login_handle": second_identity.login_handle,
                    "password": second_password,
                },
                "expected_actor_binding_revision": controller_binding_revision,
                "provenance_reference": "e2e-link",
            },
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == confirmed.json()
        assert second_password not in replay.text

        # A different second identity under the same idempotency key conflicts.
        different = await client.post(
            f"{_CREATE_PATH}/{intent_id}:confirm",
            headers={**headers, "Idempotency-Key": "link-confirm-1"},
            json={
                "proof": {
                    "target_authority_id": str(authority_id),
                    "native_identity_id": str(other_identity.native_identity_id),
                    "login_handle": other_identity.login_handle,
                    "password": other_password,
                },
                "expected_actor_binding_revision": controller_binding_revision,
                "provenance_reference": "e2e-link",
            },
        )
        assert different.status_code == 409, different.text

        # A wrong password is the same opaque 401 as native authentication.
        bad_intent = await client.post(
            _CREATE_PATH,
            headers={**headers, "Idempotency-Key": "link-create-bad"},
            json={"target_authority_id": str(authority_id), "provenance_reference": "e2e-bad"},
        )
        assert bad_intent.status_code == 201, bad_intent.text
        bad_intent_id = UUID(bad_intent.json()["intent_id"])
        wrong_password = await client.post(
            f"{_CREATE_PATH}/{bad_intent_id}:confirm",
            headers={**headers, "Idempotency-Key": "link-confirm-bad"},
            json={
                "proof": {
                    "target_authority_id": str(authority_id),
                    "native_identity_id": str(second_identity.native_identity_id),
                    "login_handle": second_identity.login_handle,
                    "password": "not the right password at all",
                },
                "expected_actor_binding_revision": controller_binding_revision,
                "provenance_reference": "e2e-bad",
            },
        )
        assert wrong_password.status_code == 401, wrong_password.text
        assert wrong_password.json()["error"]["code"] == "credential_invalid"

        # A foreign tenant's intent is indistinguishable from an absent one.
        foreign_token = await _login(
            client,
            login_handle=foreign_identity.login_handle,
            password="identity-link-self-foreign-password-4",
        )
        foreign_headers = _tenant_headers(
            token=foreign_token, organization_id=foreign_organization_id
        )
        foreign = await client.post(
            f"{_CREATE_PATH}/{bad_intent_id}:confirm",
            headers={**foreign_headers, "Idempotency-Key": "link-confirm-foreign"},
            json={
                "proof": {
                    "target_authority_id": str(authority_id),
                    "native_identity_id": str(second_identity.native_identity_id),
                    "login_handle": second_identity.login_handle,
                    "password": second_password,
                },
                "expected_actor_binding_revision": 1,
                "provenance_reference": "e2e-foreign",
            },
        )
        assert foreign.status_code == 404, foreign.text
        assert foreign.json()["error"]["code"] == "identity_link_not_found"

        # Stale reauthentication freshness closes both operations.
        stale_token = _backdated_session_token(
            e2e_admin_conn, native_identity_id=root_identity.native_identity_id
        )
        stale_headers = _tenant_headers(token=stale_token, organization_id=organization_id)
        stale = await client.post(
            _CREATE_PATH,
            headers={**stale_headers, "Idempotency-Key": "link-create-stale"},
            json={"target_authority_id": str(authority_id), "provenance_reference": "e2e-stale"},
        )
        assert stale.status_code == 403, stale.text
        assert stale.json()["error"]["code"] == "reauthentication_required"
        assert stale.json()["error"]["resolution"] == "reauthenticate"

    schema = app.openapi()
    for path, operation_id in (
        (_CREATE_PATH, "identity_link_intent_create"),
        (f"{_CREATE_PATH}/{{intent_id}}:confirm", "identity_link_intent_confirm"),
    ):
        operation = schema["paths"][path]["post"]
        assert operation["operationId"] == operation_id
        assert operation["x-request-engine-owner"] == "tenancy"
