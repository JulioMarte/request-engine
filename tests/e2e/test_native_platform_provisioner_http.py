from datetime import UTC, datetime, timedelta
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

from .agent_policy_support import provision_agent_policy
from .booking_world_support import book_appointment, build_bookable_world, find_slots
from .native_provisioning_support import workload_authority

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.security, pytest.mark.invariant]


@pytest.mark.asyncio
async def test_claimed_owner_provisions_native_human_and_tenant_without_sql_binding(
    e2e_admin_conn: Connection[Any],
    e2e_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_control_session_factory: SessionFactory,
) -> None:
    # Installation prerequisites only: no owner, binding or authority grant is
    # manufactured. The supported first-run HTTP ceremony creates those facts.
    authority_id = uuid4()
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.identity_authorities(id,kind,issuer_or_environment) "
        "VALUES(%s,'native',%s)",
        (authority_id, f"native-provisioner-http-{authority_id}"),
    )
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.platform_instance "
        "(id,built_in_native_authority_id,built_in_workload_authority_id) VALUES(%s,%s,%s)",
        (uuid4(), authority_id, uuid4()),
    )
    app = create_platform_control_app(
        auth_session_factory=e2e_session_factory,
        platform_read_session_factory=platform_read_session_factory,
        platform_write_session_factory=platform_control_session_factory,
        native_authority_id=authority_id,
        webauthn_decoy_key=b"p" * 32,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as client:
        issued = await client.post("/v1/setup/sessions")
        assert issued.status_code == 201, issued.text
        setup_headers = {"Authorization": f"Setup {issued.json()['token']}"}
        prepared = await client.post(
            "/v1/setup/native-identity",
            headers=setup_headers,
            json={
                "login_handle": "root@example.test",
                "password": "root platform proof password",
            },
        )
        assert prepared.status_code == 204, prepared.text
        registration = await client.post(
            "/v1/setup/webauthn/registration-options", headers=setup_headers
        )
        assert registration.status_code == 200, registration.text
        options = registration.json()["public_key"]
        authenticator = SoftwareAuthenticator(rp_id=options["rp"]["id"], origin="https://localhost")
        credential = authenticator.registration_credential(
            challenge=websafe_decode(options["challenge"]),
            public_key=options,
            user_verified=True,
        )
        registered = await client.post(
            "/v1/setup/webauthn/registrations",
            headers=setup_headers,
            json={"credential": credential},
        )
        assert registered.status_code == 204, registered.text
        recovery = await client.post("/v1/setup/recovery-codes", headers=setup_headers)
        assert recovery.status_code == 201, recovery.text
        claimed = await client.post(
            "/v1/setup:finalize",
            headers={**setup_headers, "Idempotency-Key": "native-provisioner-claim"},
            json={"claim_provenance": "e2e:native-provisioner"},
        )
        assert claimed.status_code == 201, claimed.text
        root_id = UUID(claimed.json()["owner_principal_id"])
        authentication = await client.post(
            "/auth/native/webauthn/authentication-options",
            json={"login_handle": "root@example.test"},
        )
        assert authentication.status_code == 200, authentication.text
        assertion = authenticator.authentication_credential(
            challenge=websafe_decode(authentication.json()["public_key"]["challenge"]),
            user_verified=True,
        )
        login = await client.post(
            "/auth/native/webauthn/sessions",
            json={"login_handle": "root@example.test", "credential": assertion},
        )
        assert login.status_code == 201, login.text
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "Idempotency-Key": "create-provisioner-1",
        }
        enrollment = await client.post(
            "/v1/platform/native-identities",
            headers={
                "Authorization": f"Bearer {login.json()['access_token']}",
                "Idempotency-Key": "native-provisioner-identity",
            },
            json={
                "login_handle": "provisioner@example.test",
                "password": "new provisioner proof password",
            },
        )
        assert enrollment.status_code == 201, enrollment.text
        # Password and passkey bearer evidence both carry a session ID, not an
        # authenticator UUID. A real password-session replay must use the same
        # current owner operation without restoring or recreating identity state.
        password_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "root@example.test",
                "password": "root platform proof password",
            },
        )
        assert password_login.status_code == 201, password_login.text
        enrollment_replay = await client.post(
            "/v1/platform/native-identities",
            headers={
                "Authorization": f"Bearer {password_login.json()['access_token']}",
                "Idempotency-Key": "native-provisioner-identity",
            },
            json={
                "login_handle": "provisioner@example.test",
                "password": "new provisioner proof password",
            },
        )
        assert enrollment_replay.status_code == 201, enrollment_replay.text
        assert enrollment_replay.json() == enrollment.json()
        body = {
            "native_identity_id": enrollment.json()["native_identity_id"],
            "provenance_reference": "deployment:provisioner-http",
        }
        endpoint = "/v1/platform/provisioners"
        assert (await client.post(endpoint, json=body)).status_code == 401
        created = await client.post(endpoint, headers=headers, json=body)
        assert created.status_code == 201, created.text
        assert created.headers["Cache-Control"] == "no-store"
        assert set(created.json()) == {"principal_id", "binding_id"}
        replay = await client.post(endpoint, headers=headers, json=body)
        assert replay.status_code == 201 and replay.json() == created.json()
        conflict = await client.post(
            endpoint, headers=headers, json={**body, "provenance_reference": "different-intent"}
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "platform_provisioning_conflict"
        assert (
            await client.post(endpoint, headers=headers, json={**body, "capabilities": ["*"]})
        ).status_code == 422
        assert (
            await client.post(endpoint, headers={**headers, "X-RE-Organization-ID": ""}, json=body)
        ).status_code == 400

        provisioner_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "provisioner@example.test",
                "password": "new provisioner proof password",
            },
        )
        assert provisioner_login.status_code == 201
        denied = await client.post(
            endpoint,
            json=body,
            headers={
                "Authorization": f"Bearer {provisioner_login.json()['access_token']}",
                "Idempotency-Key": "cannot-chain-provisioners",
            },
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "platform_provisioning_forbidden"
        controller = await client.post(
            "/v1/platform/native-identities",
            headers={
                "Authorization": f"Bearer {login.json()['access_token']}",
                "Idempotency-Key": "native-controller-identity",
            },
            json={
                "login_handle": "controller@example.test",
                "password": "controller proof password",
            },
        )
        assert controller.status_code == 201
        organization_body = {
            "organization_key": "native-http-clinic",
            "display_name": "Native HTTP Clinic",
            "controller_native_identity_id": controller.json()["native_identity_id"],
            "provenance_reference": "deployment:clinic-http",
        }
        provisioner_headers = {
            "Authorization": f"Bearer {provisioner_login.json()['access_token']}",
            "Idempotency-Key": "create-clinic-1",
        }
        organization_endpoint = "/v1/platform/organizations"
        organization = await client.post(
            organization_endpoint, headers=provisioner_headers, json=organization_body
        )
        assert organization.status_code == 201, organization.text
        assert organization.headers["Cache-Control"] == "no-store"
        repeated = await client.post(
            organization_endpoint, headers=provisioner_headers, json=organization_body
        )
        assert repeated.status_code == 201 and repeated.json() == organization.json()
        for field, changed in (
            ("organization_key", "different-clinic"),
            ("display_name", "Different Clinic"),
            ("controller_native_identity_id", str(uuid4())),
            ("provenance_reference", "different-intent"),
        ):
            conflicting = await client.post(
                organization_endpoint,
                headers=provisioner_headers,
                json={**organization_body, field: changed},
            )
            assert conflicting.status_code == 409, conflicting.text
            assert conflicting.json()["error"]["code"] == "platform_provisioning_conflict"
        invalid = await client.post(
            organization_endpoint,
            headers={**provisioner_headers, "Idempotency-Key": "missing-controller"},
            json={**organization_body, "controller_native_identity_id": str(uuid4())},
        )
        assert invalid.status_code == 422
        controller_login = await client.post(
            "/auth/native/sessions",
            json={
                "login_handle": "controller@example.test",
                "password": "controller proof password",
            },
        )
        assert controller_login.status_code == 201
        assert (
            await client.post(
                organization_endpoint,
                headers={
                    "Authorization": f"Bearer {controller_login.json()['access_token']}",
                    "Idempotency-Key": "tenant-cannot-provision",
                },
                json=organization_body,
            )
        ).status_code == 403
        operation = (await client.get("/openapi.json")).json()["paths"][endpoint]["post"]
        assert operation["operationId"] == "platform_native_provisioner_create"
        assert operation["x-request-engine-owner"] == "tenancy"
        assert operation["x-request-engine-idempotency"] == "required"
        assert "/v1/appointments" not in app.openapi()["paths"]
    provisioner_id = UUID(created.json()["principal_id"])
    assert e2e_admin_conn.execute(
        "SELECT principal_id, subject_id, status FROM request_engine.identity_bindings WHERE id=%s",
        (UUID(created.json()["binding_id"]),),
    ).fetchone() == (provisioner_id, body["native_identity_id"], "active")
    assert e2e_admin_conn.execute(
        "SELECT capability_key, delegable, granted_by_principal_id "
        "FROM request_engine.principal_authority_grants WHERE principal_id=%s",
        (provisioner_id,),
    ).fetchall() == [("organization.provision", False, root_id)]
    assert e2e_admin_conn.execute("SELECT count(*) FROM request_engine.principals").fetchone() == (
        3,
    )
    assert e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.organizations"
    ).fetchone() == (1,)
    organization_id = UUID(organization.json()["organization_id"])
    controller_id = UUID(organization.json()["controller_principal_id"])
    assert e2e_admin_conn.execute(
        "SELECT organization_id, principal_id, status FROM request_engine.identity_bindings "
        "WHERE id=%s",
        (UUID(organization.json()["controller_binding_id"]),),
    ).fetchone() == (organization_id, controller_id, "active")
    assert e2e_admin_conn.execute(
        "SELECT provisioned_by_principal_id "
        "FROM request_engine.organization_root_provisioning_facts "
        "WHERE organization_id=%s",
        (organization_id,),
    ).fetchone() == (provisioner_id,)
    tenant_app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=b"native-platform-organization-proof-key",
    )
    async with AsyncClient(
        transport=ASGITransport(app=tenant_app), base_url="https://tenant.test"
    ) as tenant_client:
        tenant_headers = {
            "Authorization": f"Bearer {controller_login.json()['access_token']}",
            "X-RE-Organization-ID": str(organization_id),
        }
        self_authority = await tenant_client.get("/v1/me/authority", headers=tenant_headers)
        assert self_authority.status_code == 200, self_authority.text
        assert self_authority.headers["cache-control"] == "no-store"
        assert self_authority.json()["principal_id"] == str(controller_id)
        assert self_authority.json()["requires_owner_validation"] is True
        assert {item["scope_key"] for item in self_authority.json()["representations"]} == {
            "operations.manage_profile",
            "operations.manage_terms",
            "operations.manage_supply",
            "operations.manage_discovery",
        }
        assert self_authority.json()["next_after"] is None
        injected = await tenant_client.get(
            "/v1/me/authority",
            headers=tenant_headers,
            params={"principal_id": str(provisioner_id)},
        )
        assert injected.status_code == 422
        staff = await tenant_client.get("/v1/staff/members", headers=tenant_headers)
        assert staff.status_code == 200, staff.text
        denied_staff = await tenant_client.get(
            "/v1/staff/members",
            headers={
                **tenant_headers,
                "Authorization": f"Bearer {provisioner_login.json()['access_token']}",
            },
        )
        assert denied_staff.status_code == 403
        assert "/v1/platform/organizations" not in tenant_app.openapi()["paths"]
        # No manually inserted controller grants: the committed initial policy
        # must be sufficient for the actual configuration and booking APIs.
        token = controller_login.json()["access_token"]
        world = await build_bookable_world(
            tenant_client, tenant_client, token=token, organization_id=organization_id
        )
        patient = await tenant_client.post(
            "/v1/parties",
            headers={**tenant_headers, "Idempotency-Key": "initial-controller-patient"},
            json={"party_kind": "person", "display_name": "Initial Policy Patient"},
        )
        assert patient.status_code == 201, patient.text
        patient_id = UUID(patient.json()["party_id"])
        slots = await find_slots(
            tenant_client,
            token=token,
            organization_id=organization_id,
            offering_version_id=world.offering_version_id,
            location_id=world.location_id,
        )
        assert slots
        appointment_id = await book_appointment(
            tenant_client,
            token=token,
            organization_id=organization_id,
            option_id=str(slots[0]["option_id"]),
            subject_party_id=patient_id,
        )
        assert e2e_admin_conn.execute(
            "SELECT organization_id, subject_party_id FROM request_engine.reservations WHERE id=%s",
            (appointment_id,),
        ).fetchone() == (organization_id, patient_id)
        # Installation configuration only; do not seed the integration, its
        # grants, or the controller permissions this journey is proving.
        workload_authority_id = workload_authority(e2e_admin_conn)
        integration = await tenant_client.post(
            "/v1/integrations",
            headers={**tenant_headers, "Idempotency-Key": "initial-controller-integration"},
            json={
                "identity_authority_id": str(workload_authority_id),
                "credential_expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "provenance_reference": "initial-controller-integration",
            },
        )
        assert integration.status_code == 201, integration.text
        integration_id = integration.json()["principal_id"]
        assigned = await tenant_client.put(
            f"/v1/integrations/{integration_id}/authority",
            headers={**tenant_headers, "Idempotency-Key": "initial-controller-assignment"},
            json={
                "expected_authority_revision": integration.json()["authority_revision"],
                "desired_capabilities": ["parties.lookup"],
                "provenance_reference": "initial-controller-assignment",
            },
        )
        assert assigned.status_code == 200, assigned.text
        activated = await tenant_client.put(
            f"/v1/integrations/{integration_id}/status",
            headers={**tenant_headers, "Idempotency-Key": "initial-controller-activation"},
            json={
                "expected_revision": assigned.json()["authority_revision"],
                "target_status": "active",
                "provenance_reference": "initial-controller-activation",
            },
        )
        assert activated.status_code == 200, activated.text
        workload_headers = {
            **tenant_headers,
            "Authorization": f"Bearer {integration.json()['workload_token']}",
        }
        lookup = await tenant_client.get(
            "/v1/parties/lookup",
            headers=workload_headers,
            params={"mode": "name", "value": "Initial Policy Patient"},
        )
        assert lookup.status_code == 200, lookup.text
        assert str(patient_id) in lookup.text
        # A sponsor's initial grants must not be inherited by its workload.
        forbidden = await tenant_client.get("/v1/staff/members", headers=workload_headers)
        assert forbidden.status_code == 403, forbidden.text
        agent_body = {
            "identity_authority_id": str(workload_authority_id),
            "display_name": "Initial Policy Booking Agent",
            "purpose": "Book patient appointments",
            "sponsor_principal_id": str(controller_id),
            "operating_mode": "autonomous",
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "provenance_reference": "initial-controller-agent",
        }
        agent_headers = {**tenant_headers, "Idempotency-Key": "initial-controller-agent"}
        agent = await tenant_client.post("/v1/agents", headers=agent_headers, json=agent_body)
        assert agent.status_code == 201, agent.text
        assert agent.headers["Cache-Control"] == "no-store"
        agent_id = UUID(agent.json()["principal_id"])
        authority_revision = agent.json()["authority_revision"]
        agent_path = f"/v1/agents/{agent_id}"
        pending_agent = await tenant_client.get(agent_path, headers=tenant_headers)
        assert pending_agent.status_code == 200, pending_agent.text
        assert pending_agent.headers["Cache-Control"] == "no-store"
        assert pending_agent.json()["status"] == "pending"
        assert pending_agent.json()["standing_capabilities"] == []
        assert pending_agent.json()["authority_revision"] == authority_revision
        assert "workload_token" not in pending_agent.json()
        page = await tenant_client.get("/v1/agents?limit=1", headers=tenant_headers)
        assert page.status_code == 200, page.text
        assert page.json() == {"items": [pending_agent.json()], "next_after": str(agent_id)}
        tail = await tenant_client.get(
            f"/v1/agents?after={agent_id}&limit=1", headers=tenant_headers
        )
        assert tail.status_code == 200 and tail.json() == {"items": [], "next_after": None}
        missing = await tenant_client.get(f"/v1/agents/{uuid4()}", headers=tenant_headers)
        assert missing.status_code == 404
        invalid_page = await tenant_client.get("/v1/agents?limit=101", headers=tenant_headers)
        assert invalid_page.status_code == 422
        assert (await tenant_client.get("/v1/agents", headers=workload_headers)).status_code == 403
        assert isinstance(authority_revision, int) and authority_revision > 0
        assert e2e_admin_conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent_id,)
        ).fetchone() == (authority_revision,)
        agent_capabilities = [
            "appointments.find_slots",
            "appointments.book",
            "appointments.subject_override",
        ]
        agent_assigned = await tenant_client.put(
            f"/v1/agents/{agent_id}/authority",
            headers={**tenant_headers, "Idempotency-Key": "initial-controller-agent-authority"},
            json={
                "expected_authority_revision": authority_revision,
                "desired_capabilities": agent_capabilities,
                "provenance_reference": "initial-controller-agent-authority",
            },
        )
        assert agent_assigned.status_code == 200, agent_assigned.text
        await provision_agent_policy(
            tenant_client,
            controller_headers=tenant_headers,
            agent_principal_id=agent_id,
            allowed_capabilities=agent_capabilities,
            risk_ceiling="external_commitment",
        )
        agent_activated = await tenant_client.put(
            f"/v1/agents/{agent_id}/status",
            headers={**tenant_headers, "Idempotency-Key": "initial-controller-agent-activation"},
            json={
                "expected_revision": agent.json()["profile_revision"],
                "target_status": "active",
                "provenance_reference": "initial-controller-agent-activation",
            },
        )
        assert agent_activated.status_code == 200, agent_activated.text
        current_agent = await tenant_client.get(agent_path, headers=tenant_headers)
        assert current_agent.status_code == 200, current_agent.text
        current = current_agent.json()
        assert current["status"] == "active"
        assert current["profile_revision"] == agent_activated.json()["profile_revision"]
        assert current["standing_capabilities"] == sorted(agent_capabilities)
        assert e2e_admin_conn.execute(
            "SELECT authority_revision FROM request_engine.principals WHERE id=%s", (agent_id,)
        ).fetchone() == (current["authority_revision"],)
        assert current["authority_revision"] > authority_revision
        agent_replay = await tenant_client.post(
            "/v1/agents", headers=agent_headers, json=agent_body
        )
        assert agent_replay.status_code == 201, agent_replay.text
        assert agent_replay.headers["Cache-Control"] == "no-store"
        assert agent_replay.json() == {**agent.json(), "workload_token": None}
        assert e2e_admin_conn.execute(
            "SELECT authority_revision > %s FROM request_engine.principals WHERE id=%s",
            (authority_revision, agent_id),
        ).fetchone() == (True,)
        agent_token = agent.json()["workload_token"]
        agent_slots = await find_slots(
            tenant_client,
            token=agent_token,
            organization_id=organization_id,
            offering_version_id=world.offering_version_id,
            location_id=world.location_id,
        )
        assert agent_slots
        agent_booking = await book_appointment(
            tenant_client,
            token=agent_token,
            organization_id=organization_id,
            option_id=str(agent_slots[0]["option_id"]),
            subject_party_id=patient_id,
        )
        assert e2e_admin_conn.execute(
            "SELECT organization_id, subject_party_id FROM request_engine.reservations WHERE id=%s",
            (agent_booking,),
        ).fetchone() == (organization_id, patient_id)
        # Compatibility input: reproduce the old persisted response shape,
        # after real provisioning, without changing any agent authority/facts.
        changed_cache = e2e_admin_conn.execute(
            "UPDATE request_engine.idempotency_records "
            "SET result_data=result_data-'authority_revision' "
            "WHERE organization_id=%s AND principal_id=%s AND capability='agent.provision' "
            "AND idempotency_key='initial-controller-agent'",
            (organization_id, controller_id),
        ).rowcount
        assert changed_cache == 1
        legacy_replay = await tenant_client.post(
            "/v1/agents", headers=agent_headers, json=agent_body
        )
        assert legacy_replay.status_code == 201, legacy_replay.text
        assert legacy_replay.json() == {
            **agent.json(),
            "workload_token": None,
            "authority_revision": None,
        }
        assert e2e_admin_conn.execute(
            "SELECT count(*) FROM request_engine.agent_profiles WHERE organization_id=%s",
            (organization_id,),
        ).fetchone() == (1,)
    assert e2e_admin_conn.execute(
        "SELECT initial_controller_policy_key "
        "FROM request_engine.organization_root_provisioning_facts WHERE organization_id=%s",
        (organization_id,),
    ).fetchone() == ("tenant-controller-v6",)
    # A replay must not undo a later explicit revocation.
    e2e_admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants SET status='revoked', "
        "revision=revision+1, revoked_at=clock_timestamp(), revoked_by_principal_id=%s "
        "WHERE principal_id=%s AND capability_key='appointments.book'",
        (controller_id, controller_id),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://control.test"
    ) as replay_client:
        after_revocation = await replay_client.post(
            organization_endpoint, headers=provisioner_headers, json=organization_body
        )
        assert after_revocation.status_code == 201, after_revocation.text
        assert after_revocation.json() == organization.json()
    assert e2e_admin_conn.execute(
        "SELECT status FROM request_engine.principal_authority_grants "
        "WHERE principal_id=%s AND capability_key='appointments.book'",
        (controller_id,),
    ).fetchall() == [("revoked",)]
