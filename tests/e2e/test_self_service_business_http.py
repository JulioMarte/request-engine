"""Owner invitation -> self-enrollment -> wizard business creation over real HTTP (ADR 0021).

Protected guarantee: INV-SELF-SERVICE-ACCOUNT-001. Plausible defects: the platform
admin still needs to choose the owner's password, the shared code is stored or
replayed, the public enrollment accepts tenant selectors, the new owner lacks root
control in the created tenant, or the issuing platform Principal gains tenant
authority. Only installation prerequisites are written with SQL; every business
fact is created through the supported control-plane and runtime APIs.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from fido2.utils import websafe_decode
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from software_webauthn_authenticator import SoftwareAuthenticator

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.platform_control_app import create_platform_control_app
from request_engine.platform.db.session import SessionFactory

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security, pytest.mark.invariant]
ROOT_PASSWORD = "root platform proof password"
OWNER_PASSWORD = "owner chosen proof password"


async def _claimed_root_session(client: AsyncClient) -> tuple[UUID, str]:
    issued = await client.post("/v1/setup/sessions")
    assert issued.status_code == 201, issued.text
    setup = {"Authorization": f"Setup {issued.json()['token']}"}
    prepared = await client.post(
        "/v1/setup/native-identity",
        headers=setup,
        json={"login_handle": "root@example.test", "password": ROOT_PASSWORD},
    )
    assert prepared.status_code == 204, prepared.text
    options = (await client.post("/v1/setup/webauthn/registration-options", headers=setup)).json()[
        "public_key"
    ]
    authenticator = SoftwareAuthenticator(rp_id=options["rp"]["id"], origin="https://localhost")
    credential = authenticator.registration_credential(
        challenge=websafe_decode(options["challenge"]), public_key=options, user_verified=True
    )
    registered = await client.post(
        "/v1/setup/webauthn/registrations", headers=setup, json={"credential": credential}
    )
    assert registered.status_code == 204, registered.text
    assert (await client.post("/v1/setup/recovery-codes", headers=setup)).status_code == 201
    claimed = await client.post(
        "/v1/setup:finalize",
        headers={**setup, "Idempotency-Key": "self-service-claim"},
        json={"claim_provenance": "e2e:self-service"},
    )
    assert claimed.status_code == 201, claimed.text
    login = await client.post(
        "/auth/native/sessions",
        json={"login_handle": "root@example.test", "password": ROOT_PASSWORD},
    )
    assert login.status_code == 201, login.text
    return UUID(claimed.json()["owner_principal_id"]), login.json()["access_token"]


@pytest.mark.asyncio
async def test_invited_owner_enrolls_and_creates_the_business_they_control(
    e2e_admin_conn: Connection[Any],
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id,kind,issuer_or_environment) "
        "VALUES(%s,'native',%s)",
        (authority_id, f"native-self-service-{authority_id}"),
    )
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id,built_in_native_authority_id,built_in_workload_authority_id) VALUES(%s,%s,%s)",
        (uuid4(), authority_id, uuid4()),
    )
    control = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
        webauthn_decoy_key=b"s" * 32,
    )
    runtime = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"self-service-business-proof-signing-key-32b",
    )
    async with (
        AsyncClient(transport=ASGITransport(app=control), base_url="https://control.test") as cp,
        AsyncClient(transport=ASGITransport(app=runtime), base_url="https://api.test") as api,
    ):
        root_id, root_token = await _claimed_root_session(cp)
        admin = {"Authorization": f"Bearer {root_token}"}
        body = {
            "delivery": "shared_code",
            "max_organizations": 1,
            "provenance_reference": "sales:whatsapp:+18095550101",
        }
        endpoint = "/v1/platform/account-invitations"
        assert (await cp.post(endpoint, json=body)).status_code == 401
        created = await cp.post(endpoint, headers={**admin, "Idempotency-Key": "inv-1"}, json=body)
        assert created.status_code == 201, created.text
        assert created.headers["Cache-Control"] == "no-store"
        invitation = created.json()
        token = invitation["invitation_token"]
        assert invitation["token_available"] is True and len(token) >= 40
        replay = await cp.post(endpoint, headers={**admin, "Idempotency-Key": "inv-1"}, json=body)
        assert replay.status_code == 201 and replay.json()["invitation_token"] is None
        assert replay.json()["invitation_id"] == invitation["invitation_id"]
        email = await cp.post(
            endpoint,
            headers={**admin, "Idempotency-Key": "inv-email"},
            json={**body, "delivery": "email", "email": "dueno@example.test"},
        )
        assert email.status_code == 503, email.text
        assert email.json()["error"]["code"] == "account_invitation_delivery_unavailable"
        listed = await cp.get(endpoint, headers=admin)
        assert listed.status_code == 200, listed.text
        assert [item["status"] for item in listed.json()["items"]] == ["pending"]

        enroll_body = {
            "invitation_token": token,
            "login_handle": "Dueno@Clinica.Example",
            "password": OWNER_PASSWORD,
        }
        assert (
            await api.post(
                "/v1/account-invitations:enroll",
                headers={"X-RE-Organization-ID": str(uuid4())},
                json=enroll_body,
            )
        ).status_code == 400
        weak = await api.post(
            "/v1/account-invitations:enroll", json={**enroll_body, "password": "short"}
        )
        assert weak.status_code == 422 and weak.json()["error"]["code"] == (
            "account_password_invalid"
        )
        enrolled = await api.post("/v1/account-invitations:enroll", json=enroll_body)
        assert enrolled.status_code == 201, enrolled.text
        assert enrolled.headers["Cache-Control"] == "no-store"
        assert enrolled.json()["login_handle"] == "dueno@clinica.example"
        assert enrolled.json()["organization_creation"]["remaining"] == 1
        reused = await api.post(
            "/v1/account-invitations:enroll",
            json={**enroll_body, "login_handle": "otro@example.test"},
        )
        assert reused.status_code == 422
        assert reused.json()["error"]["code"] == "account_invitation_invalid"

        login = await api.post(
            "/auth/native/sessions",
            json={"login_handle": "dueno@clinica.example", "password": OWNER_PASSWORD},
        )
        assert login.status_code == 201, login.text
        owner = {"Authorization": f"Bearer {login.json()['access_token']}"}
        account = await api.get("/v1/me/account", headers=owner)
        assert account.status_code == 200, account.text
        assert account.json()["organization_creation"]["max_organizations"] == 1
        assert (await api.get("/v1/me/organizations", headers=owner)).json()["items"] == []

        wizard = {"display_name": "Clínica Sonrisa", "currency": "DOP"}
        missing_key = await api.post("/v1/me/organizations", headers=owner, json=wizard)
        assert missing_key.status_code == 422
        create_headers = {**owner, "Idempotency-Key": "wizard-step-1"}
        business = await api.post("/v1/me/organizations", headers=create_headers, json=wizard)
        assert business.status_code == 201, business.text
        organization = business.json()
        assert organization["default_timezone"] == "America/Santo_Domingo"
        assert organization["default_locale"] == "es-DO"
        assert organization["initial_controller_policy"] == "tenant-controller-v10"
        assert organization["organization_creation"]["remaining"] == 0
        again = await api.post("/v1/me/organizations", headers=create_headers, json=wizard)
        assert again.status_code == 201 and again.json() == organization
        second = await api.post(
            "/v1/me/organizations",
            headers={**owner, "Idempotency-Key": "wizard-second"},
            json={"display_name": "Segunda"},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "account_organization_limit_reached"

        organization_id = organization["organization_id"]
        mine = (await api.get("/v1/me/organizations", headers=owner)).json()["items"]
        assert [item["organization_id"] for item in mine] == [organization_id]
        tenant = {**owner, "X-RE-Organization-ID": organization_id}
        authority = await api.get("/v1/me/authority", headers=tenant)
        assert authority.status_code == 200, authority.text
        assert authority.json()["principal_id"] == organization["controller_principal_id"]
        capabilities = set(authority.json()["capabilities"])
        assert {"staff.invite", "appointments.annotate"} <= capabilities
        assert not any(key.startswith("platform.") for key in capabilities)
        staff = await api.get("/v1/staff/members", headers=tenant)
        assert staff.status_code == 200, staff.text

        # The platform root token is not a tenant principal anywhere.
        foreign = await api.get(
            "/v1/me/authority", headers={**admin, "X-RE-Organization-ID": organization_id}
        )
        assert foreign.status_code in {401, 403}
        operation = runtime.openapi()["paths"]["/v1/me/organizations"]["post"]
        assert operation["operationId"] == "self_organization_create"
        assert operation["x-request-engine-entitlement"] == "account.organization.create"

    assert e2e_admin_conn.execute(
        "SELECT provisioned_by_principal_id "
        "FROM request_engine.organization_root_provisioning_facts"
    ).fetchall() == [(root_id,)]
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND organization_id IS NOT NULL",
        (root_id,),
    ).fetchone() == (0,)
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.native_credentials c "
        "JOIN request_engine.native_identities i ON i.id=c.native_identity_id "
        "WHERE i.login_handle='dueno@clinica.example'"
    ).fetchone() == (1,)
