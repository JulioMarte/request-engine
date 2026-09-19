import time
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
_SIGNING_KEY = b"native-agent-safety-e2e-appointment-signing-key-v1"


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
        (f"agent-safety-platform-{uuid4().hex}",),
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
        (provisioner_id, f"agent-safety-root:{uuid4().hex}"),
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
                f"agent-safety-{organization_id.hex}",
                "Agent Safety E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"agent-safety-root:{uuid4().hex}",
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
            principal_id,
            capability_key,
            principal_id,
            f"agent-safety-grant:{uuid4().hex}",
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
        (f"agent-safety-workload-{uuid4().hex}",),
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


async def _provision_active_agent(
    client: AsyncClient,
    e2e_admin_conn: PgConnection,
    *,
    controller_token: str,
    organization_id: UUID,
    controller_principal_id: UUID,
    display_name: str,
) -> tuple[UUID, str]:
    provisioned = await client.post(
        "/v1/agents",
        headers=_tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"agent-safety-provision-{uuid4().hex}",
        ),
        json={
            "identity_authority_id": str(_workload_authority(e2e_admin_conn)),
            "display_name": display_name,
            "purpose": "register walk-in patients",
            "sponsor_principal_id": str(controller_principal_id),
            "operating_mode": "autonomous",
            "credential_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "provenance_reference": "agent-safety-e2e-provision",
        },
    )
    assert provisioned.status_code == 201, provisioned.text
    agent_view = provisioned.json()
    agent_principal_id = UUID(agent_view["principal_id"])
    workload_token = cast(str, agent_view["workload_token"])

    activated = await client.put(
        f"/v1/agents/{agent_principal_id}/status",
        headers=_tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"agent-safety-activate-{uuid4().hex}",
        ),
        json={
            "expected_revision": 1,
            "target_status": "active",
            "provenance_reference": "agent-safety-e2e-activate",
        },
    )
    assert activated.status_code == 200, activated.text

    assigned = await client.put(
        f"/v1/agents/{agent_principal_id}/authority",
        headers=_tenant_headers(
            token=controller_token,
            organization_id=organization_id,
            idempotency_key=f"agent-safety-authority-{uuid4().hex}",
        ),
        json={
            "expected_authority_revision": _principal_revision(e2e_admin_conn, agent_principal_id),
            "desired_capabilities": ["parties.register", "parties.lookup"],
            "provenance_reference": "agent-safety-e2e-authority",
        },
    )
    assert assigned.status_code == 200, assigned.text
    return agent_principal_id, workload_token


def _sleep_until_just_after_minute_boundary(seconds_after: int = 5) -> None:
    delay = 60 - datetime.now(UTC).second + seconds_after
    time.sleep(delay)


@pytest.mark.asyncio
async def test_agent_mutation_budget_blocks_the_second_mutation_but_not_reads_or_peers(
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
        (f"agent-safety-e2e-{uuid4().hex}",),
    )
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "agent-safety-e2e-password-1"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"agent-safety-root-{uuid4().hex}@example.test",
        password=root_password,
    )
    organization_id, controller_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    for capability in ("parties.register", "parties.lookup"):
        _grant_delegable(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=controller_principal_id,
            capability_key=capability,
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
            login_handle=root_identity.login_handle,
            password=root_password,
        )
        controller_headers = _tenant_headers(
            token=controller_token,
            organization_id=organization_id,
        )

        agent_principal_id, workload_token = await _provision_active_agent(
            client,
            e2e_admin_conn,
            controller_token=controller_token,
            organization_id=organization_id,
            controller_principal_id=controller_principal_id,
            display_name="Budgeted Registration Agent",
        )
        await provision_agent_policy(
            client,
            controller_headers=controller_headers,
            agent_principal_id=agent_principal_id,
            allowed_capabilities=["parties.register", "parties.lookup"],
            risk_ceiling="low_impact_write",
            max_mutations_per_minute=1,
        )

        peer_principal_id, peer_token = await _provision_active_agent(
            client,
            e2e_admin_conn,
            controller_token=controller_token,
            organization_id=organization_id,
            controller_principal_id=controller_principal_id,
            display_name="Peer Registration Agent",
        )
        peer_policy = await provision_agent_policy(
            client,
            controller_headers=controller_headers,
            agent_principal_id=peer_principal_id,
            allowed_capabilities=["parties.register", "parties.lookup"],
            risk_ceiling="low_impact_write",
            max_mutations_per_minute=30,
        )
        assert peer_policy["max_mutations_per_minute"] == 30

        _sleep_until_just_after_minute_boundary()

        first_name = f"Budget Patient {uuid4().hex[:8]}"
        first = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-safety-first-{uuid4().hex}",
            ),
            json={"display_name": first_name},
        )
        assert first.status_code == 201, first.text

        second = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
                idempotency_key=f"agent-safety-second-{uuid4().hex}",
            ),
            json={"display_name": f"Budget Patient {uuid4().hex[:8]}"},
        )
        assert second.status_code == 429, second.text
        assert second.json()["error"]["code"] == "agent_budget_exceeded"

        exhausted_read = await client.get(
            "/v1/parties/lookup",
            headers=_tenant_headers(
                token=workload_token,
                organization_id=organization_id,
            ),
            params={"mode": "name", "value": first_name},
        )
        assert exhausted_read.status_code == 200, exhausted_read.text
        assert any(entry["display_name"] == first_name for entry in exhausted_read.json())

        peer_registration = await client.post(
            "/v1/parties",
            headers=_tenant_headers(
                token=peer_token,
                organization_id=organization_id,
                idempotency_key=f"agent-safety-peer-{uuid4().hex}",
            ),
            json={"display_name": f"Peer Patient {uuid4().hex[:8]}"},
        )
        assert peer_registration.status_code == 201, peer_registration.text

    window_row = e2e_admin_conn.execute(
        """
        SELECT mutation_count
          FROM request_engine.agent_budget_windows
         WHERE organization_id = %s AND agent_principal_id = %s
        """,
        (organization_id, agent_principal_id),
    ).fetchone()
    assert window_row == (1,)
    peer_window_row = e2e_admin_conn.execute(
        """
        SELECT mutation_count
          FROM request_engine.agent_budget_windows
         WHERE organization_id = %s AND agent_principal_id = %s
        """,
        (organization_id, peer_principal_id),
    ).fetchone()
    assert peer_window_row == (1,)
