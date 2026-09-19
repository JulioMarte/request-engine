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
_SIGNING_KEY = b"native-delegation-e2e-appointment-signing-key-v1"


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
        (f"native-delegation-platform-{uuid4().hex}",),
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
        (provisioner_id, f"native-delegation-root:{uuid4().hex}"),
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
                f"native-delegation-{organization_id.hex}",
                "Native Delegation E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"native-delegation-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _grant_delegable(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability_key: str,
    authority_plane: str = "operational",
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            %s, %s, 'tenant', %s, %s, true, %s,
            'authority_management', %s
        )
        """,
        (
            organization_id,
            principal_id,
            authority_plane,
            capability_key,
            principal_id,
            f"native-delegation-grant:{uuid4().hex}",
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
        (f"native-delegation-workload-{uuid4().hex}",),
    )


def _tenant_headers(
    *,
    token: str,
    organization_id: UUID,
    idempotency_key: str | None = None,
    delegation_id: UUID | None = None,
) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "X-RE-Organization-ID": str(organization_id),
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if delegation_id is not None:
        headers["X-RE-Delegation-ID"] = str(delegation_id)
    return headers


async def _login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])


@pytest.mark.asyncio
async def test_delegated_agent_authority_is_bounded_intersected_and_revocable(
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
        (f"native-delegation-e2e-{uuid4().hex}",),
    )
    runtime = build_native_auth_runtime(e2e_session_factory)
    controller_password = "delegation-controller-password-1"
    manager_password = "delegation-manager-password-2"
    controller_enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"delegation-root-{uuid4().hex}@example.test",
        password=controller_password,
    )
    manager_enrollment = await runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"delegation-manager-{uuid4().hex}@example.test",
        password=manager_password,
    )
    organization_id, controller_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=controller_enrollment.native_identity_id,
    )
    _grant_delegable(
        e2e_admin_conn,
        organization_id=organization_id,
        principal_id=controller_principal_id,
        capability_key="parties.lookup",
    )
    _grant_delegable(
        e2e_admin_conn,
        organization_id=organization_id,
        principal_id=controller_principal_id,
        capability_key="delegation.create",
        authority_plane="tenant_control",
    )
    _grant_delegable(
        e2e_admin_conn,
        organization_id=organization_id,
        principal_id=controller_principal_id,
        capability_key="delegation.revoke",
        authority_plane="tenant_control",
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
        controller_token = await _login(
            client,
            login_handle=controller_enrollment.login_handle,
            password=controller_password,
        )

        invited = await client.post(
            "/v1/staff/members/native",
            headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-invite-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(authority_id),
                "native_identity_id": str(manager_enrollment.native_identity_id),
                "provenance_reference": "native-delegation-invite",
            },
        )
        assert invited.status_code == 201, invited.text
        membership_id = UUID(invited.json()["membership_id"])
        manager_principal_id = UUID(invited.json()["principal_id"])
        activated = await client.put(
            f"/v1/staff/members/{membership_id}/status",
            headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "native-delegation-activate",
            },
        )
        assert activated.status_code == 200, activated.text

        manager_authority = await client.put(
            f"/v1/staff/members/{membership_id}/authority",
            headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-manager-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": _principal_revision(
                    e2e_admin_conn, manager_principal_id
                ),
                "desired_capabilities": ["delegation.create", "delegation.revoke"],
                "provenance_reference": "native-delegation-manager-authority",
            },
        )
        assert manager_authority.status_code == 200, manager_authority.text
        _grant_delegable(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=manager_principal_id,
            capability_key="parties.register",
        )

        provisioned = await client.post(
            "/v1/agents",
            headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-agent-{uuid4().hex}",
            ),
            json={
                "identity_authority_id": str(_workload_authority(e2e_admin_conn)),
                "display_name": "Delegation Scheduling Agent",
                "purpose": "register patients under delegated authority",
                "sponsor_principal_id": str(controller_principal_id),
                "operating_mode": "autonomous",
                "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "provenance_reference": "native-delegation-agent-provision",
            },
        )
        assert provisioned.status_code == 201, provisioned.text
        agent_view = provisioned.json()
        agent_principal_id = UUID(agent_view["principal_id"])
        workload_token = agent_view["workload_token"]
        await client.put(
            f"/v1/agents/{agent_principal_id}/status",
            headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-agent-activate-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "target_status": "active",
                "provenance_reference": "native-delegation-agent-activate",
            },
        )
        assigned = await client.put(
            f"/v1/agents/{agent_principal_id}/authority",
            headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-agent-authority-{uuid4().hex}",
            ),
            json={
                "expected_authority_revision": _principal_revision(
                    e2e_admin_conn, agent_principal_id
                ),
                "desired_capabilities": ["parties.lookup"],
                "provenance_reference": "native-delegation-agent-authority",
            },
        )
        assert assigned.status_code == 200, assigned.text

        policy = await provision_agent_policy(
            client,
            controller_headers=_tenant_headers(
                token=controller_token,
                organization_id=organization_id,
            ),
            agent_principal_id=agent_principal_id,
            allowed_capabilities=["parties.register", "parties.lookup"],
            risk_ceiling="low_impact_write",
            max_mutations_per_minute=60,
        )
        assert policy["policy_revision"] == 1

        manager_token = await _login(
            client,
            login_handle=manager_enrollment.login_handle,
            password=manager_password,
        )
        delegation_created = await client.post(
            "/v1/delegations",
            headers=_tenant_headers(
                token=manager_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-create-{uuid4().hex}",
            ),
            json={
                "delegate_principal_id": str(agent_principal_id),
                "purpose": "register walk-in patients",
                "allowed_capabilities": ["parties.register"],
                "not_before": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "expires_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
                "provenance_reference": "native-delegation-create",
            },
        )
        assert delegation_created.status_code == 201, delegation_created.text
        delegation_id = UUID(delegation_created.json()["delegation_id"])

        patient_name = f"Delegated Patient {uuid4().hex[:8]}"
        delegated_registration = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"delegated-party-{uuid4().hex}",
                delegation_id=delegation_id,
            ),
            json={"display_name": patient_name},
        )
        assert delegated_registration.status_code == 201, delegated_registration.text

        delegated_lookup = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                delegation_id=delegation_id,
            ),
            params={"mode": "name", "value": patient_name},
        )
        assert delegated_lookup.status_code == 403, delegated_lookup.text
        assert delegated_lookup.json()["error"]["code"] == "capability_required"

        foreign_delegation = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"foreign-delegation-{uuid4().hex}",
                delegation_id=uuid4(),
            ),
            json={"display_name": patient_name},
        )
        assert foreign_delegation.status_code == 403, foreign_delegation.text
        assert foreign_delegation.json()["error"]["code"] == "delegation_invalid"

        expired_delegation = await client.post(
            "/v1/delegations",
            headers=_tenant_headers(
                token=manager_token,
                organization_id=organization_id,
                idempotency_key=f"expired-delegation-{uuid4().hex}",
            ),
            json={
                "delegate_principal_id": str(agent_principal_id),
                "purpose": "already expired delegation",
                "allowed_capabilities": ["parties.register"],
                "not_before": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
                "provenance_reference": "native-delegation-expired",
            },
        )
        assert expired_delegation.status_code == 201, expired_delegation.text
        expired_id = UUID(expired_delegation.json()["delegation_id"])
        expired_attempt = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"expired-attempt-{uuid4().hex}",
                delegation_id=expired_id,
            ),
            json={"display_name": patient_name},
        )
        assert expired_attempt.status_code == 403, expired_attempt.text
        assert expired_attempt.json()["error"]["code"] == "delegation_invalid"

        revoked = await client.post(
            f"/v1/delegations/{delegation_id}/revoke",
            headers=_tenant_headers(
                token=manager_token,
                organization_id=organization_id,
                idempotency_key=f"delegation-revoke-{uuid4().hex}",
            ),
            json={
                "expected_revision": 1,
                "provenance_reference": "native-delegation-revoke",
            },
        )
        assert revoked.status_code == 200, revoked.text

        after_revoke = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"post-revoke-{uuid4().hex}",
                delegation_id=delegation_id,
            ),
            json={"display_name": patient_name},
        )
        assert after_revoke.status_code == 403, after_revoke.text
        assert after_revoke.json()["error"]["code"] == "delegation_invalid"

        standing_lookup = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": patient_name},
        )
        assert standing_lookup.status_code == 200, standing_lookup.text
