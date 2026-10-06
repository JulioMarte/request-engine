"""Legacy policy adoption using real native sessions and both composed HTTP apps."""

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fido2.utils import websafe_decode
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.webauthn import WebAuthnPolicy

PgConnection = Connection[Any]
pytestmark = [pytest.mark.e2e, pytest.mark.postgres, pytest.mark.security, pytest.mark.invariant]
_ORIGIN = "https://localhost"
_PASSWORD = "adoption-native-http-password-1"
_SIGNING_KEY = b"controller-policy-adoption-native-http-signing-key"
_WEBAUTHN = WebAuthnPolicy(
    rp_id="localhost", rp_name="Request Engine", allowed_origins=frozenset({_ORIGIN})
)


def _uuid_row(conn: PgConnection, query: LiteralString, params: tuple[object, ...]) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _authority_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (principal_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def _enroll_password_identity(
    conn: PgConnection, identity_authority_id: UUID, native_identity_id: UUID
) -> UUID:
    return _uuid_row(
        conn,
        "SELECT id FROM request_engine.native_identities WHERE id=%s AND identity_authority_id=%s",
        (native_identity_id, identity_authority_id),
    )


def _provision_legacy_root(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    provisioner_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES('platform','human',%s) RETURNING id",
        (f"adoption-provisioner-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(principal_id,principal_plane,"
        "authority_plane,capability_key,delegable,provenance_kind,provenance_reference) "
        "VALUES(%s,'platform','platform','organization.provision',false,'trust_bootstrap',%s)",
        (provisioner_id, f"adoption-provisioner:{uuid4().hex}"),
    )
    revision = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (provisioner_id,)
    ).fetchone()
    assert revision is not None
    organization_id, party_id, root_id = uuid4(), uuid4(), uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id',%s,false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision',%s,false)",
        (str(revision[0]),),
    )
    with conn.transaction():
        conn.execute("SET ROLE request_platform_control")
        try:
            conn.execute(
                "SELECT request_platform.select_initial_controller_policy(%s)",
                ("tenant-controller-v1",),
            )
            result = conn.execute(
                "SELECT * FROM request_platform.provision_native_organization_root("
                "%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    organization_id,
                    f"adoption-{organization_id.hex}",
                    "Adoption native HTTP",
                    party_id,
                    root_id,
                    identity_authority_id,
                    native_identity_id,
                    f"adoption-root:{uuid4().hex}",
                ),
            ).fetchone()
            assert result is not None
        finally:
            conn.execute("RESET ROLE")
    return organization_id, root_id


def _platform_principal(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
    capabilities: tuple[str, ...],
) -> UUID:
    principal_id = _uuid_row(
        conn,
        "INSERT INTO request_engine.principals(principal_plane,principal_kind,external_subject) "
        "VALUES('platform','human',%s) RETURNING id",
        (f"adoption-operator-{uuid4().hex}",),
    )
    conn.execute(
        "INSERT INTO request_engine.identity_bindings(principal_id,principal_plane,"
        "identity_authority_id,subject_id,status) VALUES(%s,'platform',%s,%s,'active')",
        (principal_id, identity_authority_id, str(native_identity_id)),
    )
    for capability in capabilities:
        conn.execute(
            "INSERT INTO request_engine.principal_authority_grants(principal_id,"
            "principal_plane,authority_plane,capability_key,delegable,provenance_kind,"
            "provenance_reference) VALUES(%s,'platform','platform',%s,false,'trust_bootstrap',%s)",
            (principal_id, capability, f"adoption-native-http:{uuid4().hex}"),
        )
    return principal_id


async def _passkey_login(
    client: AsyncClient, *, login_handle: str, password: str
) -> tuple[str, SoftwareAuthenticator]:
    password_login = await client.post(
        "/auth/native/sessions", json={"login_handle": login_handle, "password": password}
    )
    assert password_login.status_code == 201, password_login.text
    bearer = {"Authorization": f"Bearer {password_login.json()['access_token']}"}
    options_response = await client.post(
        "/auth/native/sessions/current/webauthn/registration-options", headers=bearer
    )
    assert options_response.status_code == 200, options_response.text
    public_key = options_response.json()["public_key"]
    authenticator = SoftwareAuthenticator(rp_id=public_key["rp"]["id"], origin=_ORIGIN)
    registration = await client.post(
        "/auth/native/sessions/current/webauthn/registrations",
        headers=bearer,
        json={
            "credential": authenticator.registration_credential(
                challenge=websafe_decode(public_key["challenge"]), user_verified=True
            )
        },
    )
    assert registration.status_code == 201, registration.text
    auth_options = await client.post(
        "/auth/native/webauthn/authentication-options", json={"login_handle": login_handle}
    )
    assert auth_options.status_code == 200, auth_options.text
    credential = authenticator.authentication_credential(
        challenge=websafe_decode(auth_options.json()["public_key"]["challenge"]),
        user_verified=True,
    )
    login = await client.post(
        "/auth/native/webauthn/sessions",
        json={"login_handle": login_handle, "credential": credential},
    )
    assert login.status_code == 201, login.text
    token = str(login.json()["access_token"])
    evidence = await client.get(
        "/auth/native/sessions/current",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["authentication_assurance"] == "phishing_resistant"
    assert evidence.json()["user_verified"] is True
    return token, authenticator


def _tenant_headers(token: str, organization_id: UUID, key: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


@pytest.mark.asyncio
async def test_adoption_uses_real_native_http_auth_and_platform_control_composition(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    identity_authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id,kind,issuer_or_environment) "
        "VALUES(%s,'native',%s)",
        (identity_authority_id, f"adoption-native-http:{uuid4().hex}"),
    )
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id,built_in_native_authority_id,built_in_workload_authority_id) VALUES(%s,%s,%s)",
        (uuid4(), identity_authority_id, uuid4()),
    )
    enrollment = build_native_auth_runtime(e2e_session_factory)
    root_handle = f"adoption-root-{uuid4().hex}@example.test"
    owner_handle = f"adoption-owner-{uuid4().hex}@example.test"
    weak_owner_handle = f"adoption-weak-owner-{uuid4().hex}@example.test"
    root_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=identity_authority_id,
        login_handle=root_handle,
        password=_PASSWORD,
    )
    owner_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=identity_authority_id,
        login_handle=owner_handle,
        password=_PASSWORD,
    )
    weak_owner_identity = await enrollment.service.enroll_password_identity(
        identity_authority_id=identity_authority_id,
        login_handle=weak_owner_handle,
        password=_PASSWORD,
    )
    # Validate identities were persisted by the real auth enrollment service.
    assert (
        _enroll_password_identity(
            e2e_admin_conn, identity_authority_id, root_identity.native_identity_id
        )
        == root_identity.native_identity_id
    )
    organization_id, root_principal_id = _provision_legacy_root(
        e2e_admin_conn,
        identity_authority_id=identity_authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    owner_principal_id = _platform_principal(
        e2e_admin_conn,
        identity_authority_id=identity_authority_id,
        native_identity_id=owner_identity.native_identity_id,
        capabilities=(
            "platform.organization.adopt_initial_controller_policy",
            "platform.organization.read",
        ),
    )
    weak_owner_id = _platform_principal(
        e2e_admin_conn,
        identity_authority_id=identity_authority_id,
        native_identity_id=weak_owner_identity.native_identity_id,
        capabilities=("platform.owner.provision",),
    )
    same_identity_operator_id = _platform_principal(
        e2e_admin_conn,
        identity_authority_id=identity_authority_id,
        native_identity_id=root_identity.native_identity_id,
        capabilities=("platform.organization.adopt_initial_controller_policy",),
    )
    # These rows are preconditions only; the public endpoint remains responsible
    # for policy consent and application.
    assert owner_principal_id != weak_owner_id != same_identity_operator_id

    control_app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=identity_authority_id,
        webauthn_policy=_WEBAUTHN,
        webauthn_decoy_key=b"a" * 32,
    )
    tenant_app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=identity_authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
        webauthn_policy=_WEBAUTHN,
        webauthn_decoy_key=b"a" * 32,
    )
    async with (
        AsyncClient(
            transport=ASGITransport(app=control_app), base_url="https://control.test"
        ) as control,
        AsyncClient(
            transport=ASGITransport(app=tenant_app), base_url="https://tenant.test"
        ) as tenant,
    ):
        root_token, _ = await _passkey_login(tenant, login_handle=root_handle, password=_PASSWORD)
        owner_token, _ = await _passkey_login(
            control, login_handle=owner_handle, password=_PASSWORD
        )
        weak_owner_token, _ = await _passkey_login(
            control, login_handle=weak_owner_handle, password=_PASSWORD
        )
        same_identity_token, _ = await _passkey_login(
            control, login_handle=root_handle, password=_PASSWORD
        )

        consent = await tenant.post(
            "/v1/controller-policy-adoptions",
            headers=_tenant_headers(root_token, organization_id, f"consent:{uuid4().hex}"),
            json={
                "expected_authority_revision": _authority_revision(
                    e2e_admin_conn, root_principal_id
                ),
                "reason": "Reconcile legacy root permissions to the current policy",
            },
        )
        assert consent.status_code == 201, consent.text
        request_id = UUID(consent.json()["request_id"])
        request_revision = consent.json()["request_revision"]

        weak_apply = await control.post(
            f"/v1/platform/controller-policy-adoptions/{request_id}:apply",
            headers={
                "Authorization": f"Bearer {weak_owner_token}",
                "Idempotency-Key": f"weak-apply:{uuid4().hex}",
            },
            json={"expected_request_revision": request_revision},
        )
        assert weak_apply.status_code == 403, weak_apply.text
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.controller_policy_adoption_facts "
            "WHERE request_id=%s",
            (request_id,),
        ).fetchone() == (0,)

        same_identity_apply = await control.post(
            f"/v1/platform/controller-policy-adoptions/{request_id}:apply",
            headers={
                "Authorization": f"Bearer {same_identity_token}",
                "Idempotency-Key": f"same-identity-apply:{uuid4().hex}",
            },
            json={"expected_request_revision": request_revision},
        )
        assert same_identity_apply.status_code == 403, same_identity_apply.text
        assert same_identity_apply.json()["error"]["code"] == "controller_policy_adoption_forbidden"
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.controller_policy_adoption_facts "
            "WHERE request_id=%s",
            (request_id,),
        ).fetchone() == (0,)

        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        review = await control.get(
            f"/v1/platform/controller-policy-adoptions/{request_id}", headers=owner_headers
        )
        assert review.status_code == 200, review.text
        assert review.json()["reason"] == "Reconcile legacy root permissions to the current policy"
        assert review.json()["proposed_capabilities"]
        assert review.json()["revoked_capabilities"] == []
        assert review.json()["capability_delta_is_non_revoking"] is True
        assert "can_apply" not in review.json()

        same_identity_review = await control.get(
            f"/v1/platform/controller-policy-adoptions/{request_id}",
            headers={"Authorization": f"Bearer {same_identity_token}"},
        )
        assert same_identity_review.status_code == 200, same_identity_review.text
        assert same_identity_review.json()["capability_delta_is_non_revoking"] is True
        assert same_identity_apply.status_code == 403
        assert same_identity_apply.json()["error"]["code"] == "controller_policy_adoption_forbidden"

        review_schema = control_app.openapi()["components"]["schemas"][
            "ControllerPolicyAdoptionReviewView"
        ]["properties"]
        assert "can_apply" not in review_schema
        description = review_schema["capability_delta_is_non_revoking"]["description"]
        assert "not apply eligibility" in description
        applied = await control.post(
            f"/v1/platform/controller-policy-adoptions/{request_id}:apply",
            headers={**owner_headers, "Idempotency-Key": f"valid-apply:{uuid4().hex}"},
            json={"expected_request_revision": request_revision},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["controller_principal_id"] == str(root_principal_id)
        assert applied.json()["platform_approver_principal_id"] == str(owner_principal_id)
        assert applied.json()["target_policy_key"] == "tenant-controller-v6"
