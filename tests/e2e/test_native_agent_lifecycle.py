from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

from .agent_policy_support import grant_agent_policy_authority, provision_agent_policy

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"native-agent-e2e-appointment-signing-key-v1"


def _uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


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
        (f"native-agent-platform-{uuid4().hex}",),
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
        (provisioner_id, f"native-agent-root:{uuid4().hex}"),
    )
    organization_id = uuid4()
    organization_party_id = uuid4()
    controller_principal_id = uuid4()
    conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_id),),
    )
    conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(_principal_revision(conn, provisioner_id)),),
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
                f"native-agent-{organization_id.hex}",
                "Native Agent E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"native-agent-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _grant_controller_delegable_operational_authority(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_principal_id: UUID,
    capability_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            %s, %s, 'tenant', 'operational', %s, true, %s,
            'authority_management', %s
        )
        """,
        (
            organization_id,
            controller_principal_id,
            capability_key,
            controller_principal_id,
            f"native-agent-grant:{uuid4().hex}",
        ),
    )


def _workload_authority(conn: PgConnection) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('workload', %s) RETURNING id
        """,
        (f"native-agent-workload-{uuid4().hex}",),
    )


def _tenant_headers(
    *,
    token: str,
    organization_id: UUID,
    idempotency_key: str | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


@pytest.mark.asyncio
async def test_first_class_agent_is_provisioned_executes_work_and_is_revocable(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _uuid_row(
        e2e_admin_conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s) RETURNING id
        """,
        (f"native-agent-e2e-{uuid4().hex}",),
    )
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "root-agent-e2e-password-1"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"root-agent-{uuid4().hex}@example.test",
        password=root_password,
    )
    organization_id, controller_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    workload_authority_id = _workload_authority(e2e_admin_conn)
    for capability in ("parties.register", "parties.lookup"):
        _grant_controller_delegable_operational_authority(
            e2e_admin_conn,
            organization_id=organization_id,
            controller_principal_id=controller_principal_id,
            capability_key=capability,
        )
    _grant_controller_delegable_operational_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
        capability_key="appointments.book",
    )
    grant_agent_policy_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root_token = await _login(
            client,
            login_handle=root_identity.login_handle,
            password=root_password,
        )

        provision_key = f"agent-provision-{uuid4().hex}"
        provision_body = {
            "identity_authority_id": str(workload_authority_id),
            "display_name": "Clinic Scheduling Agent",
            "purpose": "register and look up patients",
            "sponsor_principal_id": str(controller_principal_id),
            "operating_mode": "autonomous",
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": "native-agent-e2e-provision",
        }
        provisioned = await client.post(
            "/v1/agents",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=provision_key,
            ),
            json=provision_body,
        )
        assert provisioned.status_code == 201, provisioned.text
        agent_view = provisioned.json()
        agent_principal_id = UUID(agent_view["principal_id"])
        workload_token = agent_view["workload_token"]
        assert workload_token
        assert agent_view["status"] == "pending"

        replayed = await client.post(
            "/v1/agents",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=provision_key,
            ),
            json=provision_body,
        )
        assert replayed.status_code == 201, replayed.text
        assert replayed.json()["principal_id"] == str(agent_principal_id)
        assert replayed.json()["workload_token"] is None

        pending_lookup = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert pending_lookup.status_code == 403, pending_lookup.text
        assert pending_lookup.json()["error"]["code"] == "identity_binding_pending"

        activated = await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"agent-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "native-agent-e2e-activate",
            },
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["profile_revision"] == 2

        agent_authority_revision = _principal_revision(e2e_admin_conn, agent_principal_id)
        assigned = await client.put(
            f"/v1/agents/{agent_principal_id}/authority",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"agent-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": agent_authority_revision,
                "desired_capabilities": [
                    "parties.register",
                    "parties.lookup",
                    "appointments.book",
                ],
                "provenance_reference": "native-agent-e2e-authority",
            },
        )
        assert assigned.status_code == 200, assigned.text

        agent_display_name = f"Agent Registered Patient {uuid4().hex[:8]}"
        controller_headers = _tenant_headers(
            token=root_token,
            organization_id=organization_id,
        )

        no_policy = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert no_policy.status_code == 403, no_policy.text
        assert no_policy.json()["error"]["code"] == "agent_policy_denied"

        policy = await provision_agent_policy(
            client,
            controller_headers=controller_headers,
            agent_principal_id=agent_principal_id,
            allowed_capabilities=["parties.lookup"],
            risk_ceiling="low_impact_write",
            max_mutations_per_minute=10,
        )
        assert policy["policy_revision"] == 1

        excluded_by_policy = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-excluded-{uuid4().hex}",
            ),
            json={"display_name": agent_display_name},
        )
        assert excluded_by_policy.status_code == 403, excluded_by_policy.text
        assert excluded_by_policy.json()["error"]["code"] == "capability_required"

        still_allowed_read = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": "nobody"},
        )
        assert still_allowed_read.status_code == 200, still_allowed_read.text

        widened = await provision_agent_policy(
            client,
            controller_headers=controller_headers,
            agent_principal_id=agent_principal_id,
            allowed_capabilities=["parties.register", "parties.lookup", "appointments.book"],
            risk_ceiling="low_impact_write",
            max_mutations_per_minute=10,
        )
        assert widened["policy_revision"] == 2

        above_ceiling = await client.post(
            "/v1/appointments",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-booking-{uuid4().hex}",
            ),
            json={"option_id": f"e2e-option-{uuid4().hex}", "subject_party_id": str(uuid4())},
        )
        assert above_ceiling.status_code == 403, above_ceiling.text
        assert above_ceiling.json()["error"]["code"] == "agent_risk_denied"

        authority_change_attempt = await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-self-suspend-{uuid4().hex}",
            ),
            json={
                "expected_revision": 2,
                "target_status": "suspended",
                "provenance_reference": "native-agent-e2e-self-suspend",
            },
        )
        assert authority_change_attempt.status_code == 403, authority_change_attempt.text
        assert authority_change_attempt.json()["error"]["code"] == "agent_risk_denied"
        assert e2e_admin_conn.execute(
            "SELECT revision, status FROM request_engine.agent_profiles WHERE principal_id = %s",
            (agent_principal_id,),
        ).fetchone() == (2, "active")

        unmarked_route = await client.get(
            "/v1/operation-catalog",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
        )
        assert unmarked_route.status_code == 403, unmarked_route.text
        assert unmarked_route.json()["error"]["code"] == "agent_policy_denied"

        registered_by_agent = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-party-{uuid4().hex}",
            ),
            json={"display_name": agent_display_name},
        )
        assert registered_by_agent.status_code == 201, registered_by_agent.text

        looked_up = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": agent_display_name},
        )
        assert looked_up.status_code == 200, looked_up.text
        assert any(entry["display_name"] == agent_display_name for entry in looked_up.json())

        forbidden_staff = await client.post(
            "/v1/staff/members/native",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-staff-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(authority_id),
                "native_identity_id": str(uuid4()),
                "provenance_reference": "native-agent-e2e-staff",
            },
        )
        assert forbidden_staff.status_code == 403, forbidden_staff.text

        forbidden_self_provision = await client.post(
            "/v1/agents",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-self-{uuid4().hex}",
            ),
            json=provision_body,
        )
        assert forbidden_self_provision.status_code == 403, forbidden_self_provision.text
        assert forbidden_self_provision.json()["error"]["code"] == "agent_risk_denied"

        suspended = await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"agent-suspend-{uuid4().hex}",
            ),
            json={
                "expected_revision": 2,
                "target_status": "suspended",
                "provenance_reference": "native-agent-e2e-suspend",
            },
        )
        assert suspended.status_code == 200, suspended.text

        after_suspend = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": agent_display_name},
        )
        assert after_suspend.status_code == 403, after_suspend.text
        assert after_suspend.json()["error"]["code"] == "identity_binding_suspended"
