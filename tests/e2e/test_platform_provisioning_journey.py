import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.entrypoints.platform_bootstrap_cli import (
    establish_root,
    issue_intent,
)
from request_engine.platform.db.session import SessionFactory

from .agent_policy_support import grant_agent_policy_authority, provision_agent_policy
from .native_provisioning_support import (
    PgConnection,
    bind_platform_identity,
    login,
    principal_revision,
    tenant_headers,
    workload_authority,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"platform-journey-appointment-signing-key-v1"

_ADMIN_HANDLE = os.environ.setdefault("RE_JOURNEY_ADMIN_HANDLE", "journey-admin@example.test")
_ADMIN_PASSWORD = os.environ.setdefault("RE_JOURNEY_ADMIN_PASSWORD", "journey-admin-password-1")
_PROVISIONER_HANDLE = os.environ.setdefault(
    "RE_JOURNEY_PROVISIONER_HANDLE", "journey-provisioner@example.test"
)
_PROVISIONER_PASSWORD = os.environ.setdefault(
    "RE_JOURNEY_PROVISIONER_PASSWORD", "journey-provisioner-password-2"
)
_CONTROLLER_HANDLE = os.environ.setdefault(
    "RE_JOURNEY_CONTROLLER_HANDLE", "journey-controller@example.test"
)
_CONTROLLER_PASSWORD = os.environ.setdefault(
    "RE_JOURNEY_CONTROLLER_PASSWORD", "journey-controller-password-3"
)
_STAFF_HANDLE = os.environ.setdefault("RE_JOURNEY_STAFF_HANDLE", "journey-staff@example.test")
_STAFF_PASSWORD = os.environ.setdefault("RE_JOURNEY_STAFF_PASSWORD", "journey-staff-password-4")


@pytest.mark.asyncio
async def test_platform_bootstrap_provisions_the_full_actor_chain_from_environment(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = (
        f"host={os.environ.get('PGHOST', '127.0.0.1')} "
        f"port={os.environ.get('PGPORT', '5432')} "
        f"dbname={os.environ.get('PGDATABASE', 'request_engine_v3')} "
        f"user={os.environ.get('PGUSER', 'request_engine')} "
        f"password={os.environ.get('PGPASSWORD', 'request_engine')}"
    )
    monkeypatch.setenv("REQUEST_ENGINE_BOOTSTRAP_DSN", dsn)

    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)

    issue_output = issue_intent(
        ttl_minutes=15,
        provenance="platform-journey-bootstrap",
    )
    bootstrap_lines = dict(
        line.split(": ", 1) for line in issue_output.splitlines() if ": " in line
    )
    native_authority_id = UUID(bootstrap_lines["Native authority"])
    bootstrap_token = bootstrap_lines["ONE-TIME BOOTSTRAP TOKEN"]
    admin_principal_id = establish_root(
        login_handle=_ADMIN_HANDLE,
        raw_token=bootstrap_token,
        password=_ADMIN_PASSWORD,
    )

    provisioner_enrollment = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=_PROVISIONER_HANDLE,
        password=_PROVISIONER_PASSWORD,
    )
    controller_enrollment = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=_CONTROLLER_HANDLE,
        password=_CONTROLLER_PASSWORD,
    )
    staff_enrollment = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=native_authority_id,
        login_handle=_STAFF_HANDLE,
        password=_STAFF_PASSWORD,
    )

    provisioner_principal_id = uuid4()
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(admin_principal_id),),
    )
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(e2e_admin_conn, admin_principal_id)),),
    )
    e2e_admin_conn.execute("SET ROLE request_platform_control")
    try:
        created = e2e_admin_conn.execute(
            "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
            (
                provisioner_principal_id,
                f"native:{provisioner_enrollment.native_identity_id}",
                "platform-journey:provisioner",
            ),
        ).fetchone()
        assert created is not None
    finally:
        e2e_admin_conn.execute("RESET ROLE")
    bind_platform_identity(
        e2e_admin_conn,
        principal_id=provisioner_principal_id,
        identity_authority_id=native_authority_id,
        native_identity_id=provisioner_enrollment.native_identity_id,
    )

    organization_id = uuid4()
    organization_party_id = uuid4()
    controller_principal_id = uuid4()
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authenticated_principal_id', %s, false)",
        (str(provisioner_principal_id),),
    )
    e2e_admin_conn.execute(
        "SELECT set_config('request_engine.authority_revision', %s, false)",
        (str(principal_revision(e2e_admin_conn, provisioner_principal_id)),),
    )
    e2e_admin_conn.execute("SET ROLE request_platform_control")
    try:
        with pytest.raises(Exception) as amplification:
            e2e_admin_conn.execute(
                "SELECT request_platform.provision_tenant_provisioner(%s, %s, %s)",
                (
                    uuid4(),
                    f"native:{uuid4()}",
                    "platform-journey:amplification-attempt",
                ),
            )
        assert getattr(amplification.value, "sqlstate", None) == "42501"

        rooted = e2e_admin_conn.execute(
            """
            SELECT * FROM request_platform.provision_native_organization_root(
                %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                organization_id,
                f"platform-journey-{organization_id.hex}",
                "Platform Journey Tenant",
                organization_party_id,
                controller_principal_id,
                native_authority_id,
                controller_enrollment.native_identity_id,
                "platform-journey:tenant-root",
            ),
        ).fetchone()
        assert rooted is not None
    finally:
        e2e_admin_conn.execute("RESET ROLE")

    provisioner_grants = e2e_admin_conn.execute(
        """
        SELECT capability_key, delegable
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND status = 'active'
        """,
        (provisioner_principal_id,),
    ).fetchall()
    assert provisioner_grants == [("organization.provision", False)]

    controller_grants = e2e_admin_conn.execute(
        """
        SELECT count(*)
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND status = 'active' AND authority_plane = 'platform'
        """,
        (controller_principal_id,),
    ).fetchone()
    assert controller_grants is not None and int(controller_grants[0]) == 0

    e2e_admin_conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            %s, %s, 'tenant', 'operational', 'parties.lookup', true, %s,
            'authority_management', %s
        ), (
            %s, %s, 'tenant', 'operational', 'parties.register', true, %s,
            'authority_management', %s
        )
        """,
        (
            organization_id,
            controller_principal_id,
            controller_principal_id,
            f"platform-journey:lookup-grant-{uuid4().hex}",
            organization_id,
            controller_principal_id,
            controller_principal_id,
            f"platform-journey:register-grant-{uuid4().hex}",
        ),
    )
    grant_agent_policy_authority(
        e2e_admin_conn,
        organization_id=organization_id,
        controller_principal_id=controller_principal_id,
    )

    app = create_native_app(
        session_factory=e2e_session_factory,
        native_identity_authority_id=native_authority_id,
        appointment_option_signing_key=_SIGNING_KEY,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        controller_token = await login(
            client,
            login_handle=_CONTROLLER_HANDLE,
            password=_CONTROLLER_PASSWORD,
        )

        invite_key = f"journey-staff-invite-{uuid4().hex}"
        invited = await client.post(
            "/v1/staff/members/native",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=invite_key,
            ),
            json={
                "identity_authority_id": str(native_authority_id),
                "native_identity_id": str(staff_enrollment.native_identity_id),
                "provenance_reference": "platform-journey:staff-invite",
            },
        )
        assert invited.status_code == 201, invited.text
        staff_principal_id = UUID(invited.json()["principal_id"])

        staff_activated = await client.put(
            f"/v1/staff/members/{invited.json()['membership_id']}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"journey-staff-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "platform-journey:staff-activate",
            },
        )
        assert staff_activated.status_code == 200, staff_activated.text

        staff_authority_revision = principal_revision(e2e_admin_conn, staff_principal_id)
        staff_authority = await client.put(
            f"/v1/staff/members/{invited.json()['membership_id']}/authority",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"journey-staff-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": staff_authority_revision,
                "desired_capabilities": ["parties.register", "parties.lookup"],
                "provenance_reference": "platform-journey:staff-authority",
            },
        )
        assert staff_authority.status_code == 200, staff_authority.text

        staff_grants = e2e_admin_conn.execute(
            """
            SELECT capability_key, authority_plane, delegable, granted_by_principal_id
              FROM request_engine.principal_authority_grants
             WHERE principal_id = %s AND status = 'active'
             ORDER BY capability_key
            """,
            (staff_principal_id,),
        ).fetchall()
        assert staff_grants == [
            ("parties.lookup", "operational", False, controller_principal_id),
            ("parties.register", "operational", False, controller_principal_id),
        ]

        # Known operational keys still require a current delegable grant.
        exceeded = await client.put(
            f"/v1/staff/members/{invited.json()['membership_id']}/authority",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"journey-staff-ceiling-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": staff_authority.json()["authority_revision"],
                "desired_capabilities": ["appointments.cancel"],
                "provenance_reference": "platform-journey:staff-ceiling",
            },
        )
        assert exceeded.status_code == 403, exceeded.text
        assert (
            principal_revision(e2e_admin_conn, staff_principal_id)
            == (staff_authority.json()["authority_revision"])
        )

        staff_token = await login(
            client,
            login_handle=_STAFF_HANDLE,
            password=_STAFF_PASSWORD,
        )
        patient_name = f"Journey Patient {uuid4().hex[:8]}"
        registered = await client.post(
            "/v1/parties",
            headers=tenant_headers(
                token=staff_token,
                organization_id=organization_id,
                idempotency_key=f"journey-party-{uuid4().hex}",
            ),
            json={"display_name": patient_name},
        )
        assert registered.status_code == 201, registered.text

        staff_forbidden = await client.post(
            "/v1/staff/members/native",
            headers=tenant_headers(
                token=staff_token,
                organization_id=organization_id,
                idempotency_key=f"journey-staff-escalation-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(native_authority_id),
                "native_identity_id": str(uuid4()),
                "provenance_reference": "platform-journey:staff-escalation",
            },
        )
        assert staff_forbidden.status_code == 403, staff_forbidden.text
        assert staff_forbidden.json()["error"]["code"] == "capability_required"

        suspended = await client.put(
            f"/v1/staff/members/{invited.json()['membership_id']}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"journey-staff-suspend-{uuid4().hex}",
            ),
            json={
                "expected_revision": staff_activated.json()["membership_revision"],
                "target_status": "suspended",
                "provenance_reference": "platform-journey:staff-suspend",
            },
        )
        assert suspended.status_code == 200, suspended.text
        after_suspend = await client.post(
            "/v1/parties",
            headers=tenant_headers(
                token=staff_token,
                organization_id=organization_id,
                idempotency_key=f"journey-staff-suspended-write-{uuid4().hex}",
            ),
            json={"display_name": "Forbidden suspended staff write"},
        )
        assert after_suspend.status_code == 401, after_suspend.text
        assert after_suspend.json()["error"]["code"] == "credential_invalid"
        assert e2e_admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.parties
             WHERE organization_id = %s AND display_name = %s
            """,
            (organization_id, "Forbidden suspended staff write"),
        ).fetchone() == (0,)

        provision_key = f"journey-agent-provision-{uuid4().hex}"
        provision_body = {
            "identity_authority_id": str(workload_authority(e2e_admin_conn)),
            "display_name": "Journey Scheduling Agent",
            "purpose": "look up patients for the front desk",
            "sponsor_principal_id": str(controller_principal_id),
            "operating_mode": "autonomous",
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": "platform-journey:agent-provision",
        }
        provisioned = await client.post(
            "/v1/agents",
            headers=tenant_headers(
                token=controller_token,
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

        activated = await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"journey-agent-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "platform-journey:agent-activate",
            },
        )
        assert activated.status_code == 200, activated.text

        agent_authority_revision = principal_revision(e2e_admin_conn, agent_principal_id)
        assigned = await client.put(
            f"/v1/agents/{agent_principal_id}/authority",
            headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"journey-agent-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": agent_authority_revision,
                "desired_capabilities": ["parties.lookup"],
                "provenance_reference": "platform-journey:agent-authority",
            },
        )
        assert assigned.status_code == 200, assigned.text

        policy = await provision_agent_policy(
            client,
            controller_headers=tenant_headers(
                token=controller_token,
                organization_id=organization_id,
            ),
            agent_principal_id=agent_principal_id,
            allowed_capabilities=["parties.lookup"],
            risk_ceiling="read",
            max_mutations_per_minute=60,
        )
        assert policy["policy_revision"] == 1

        agent_lookup = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": patient_name},
        )
        assert agent_lookup.status_code == 200, agent_lookup.text
        assert any(entry["display_name"] == patient_name for entry in agent_lookup.json())

        agent_write_forbidden = await client.post(
            "/v1/parties",
            headers=tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"journey-agent-write-{uuid4().hex}",
            ),
            json={"display_name": patient_name},
        )
        assert agent_write_forbidden.status_code == 403, agent_write_forbidden.text

        provisioner_token = await login(
            client,
            login_handle=_PROVISIONER_HANDLE,
            password=_PROVISIONER_PASSWORD,
        )
        provisioner_tenant_access = await client.get(
            "/v1/parties/lookup",
            headers=tenant_headers(
                token=provisioner_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": patient_name},
        )
        assert provisioner_tenant_access.status_code == 403, provisioner_tenant_access.text
        assert provisioner_tenant_access.json()["error"]["code"] == "identity_not_bound"

    profile_provenance = e2e_admin_conn.execute(
        """
        SELECT established_by_principal_id, provenance_kind
          FROM request_engine.agent_profiles
         WHERE principal_id = %s
        """,
        (agent_principal_id,),
    ).fetchone()
    assert profile_provenance == (controller_principal_id, "agent_provisioning")
