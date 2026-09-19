"""E1 controller-policy upgrade over the real tenant HTTP surface."""

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_native_app
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.security,
    pytest.mark.invariant,
]
_SIGNING_KEY = b"controller-policy-upgrade-e2e-signing-key-v1"
_V1 = "tenant-controller-v1"
_V3 = "tenant-controller-v3"
_V4 = "tenant-controller-v4"


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
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('native', %s)
        RETURNING id
        """,
        (f"controller-policy-e2e-{uuid4().hex}",),
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
        ) VALUES ('platform', 'human', %s)
        RETURNING id
        """,
        (f"controller-policy-platform-{uuid4().hex}",),
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
        (provisioner_id, f"controller-policy-root:{uuid4().hex}"),
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
                f"controller-policy-{organization_id.hex}",
                "Controller Policy E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"controller-policy-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _active_capabilities(
    conn: PgConnection, *, organization_id: UUID, principal_id: UUID
) -> set[str]:
    rows = conn.execute(
        """
        SELECT capability_key
          FROM request_engine.principal_authority_grants
         WHERE organization_id = %s AND principal_id = %s AND status = 'active'
        """,
        (organization_id, principal_id),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _insert_policy_grants(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    policy_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        )
        SELECT %s, %s, 'tenant', g.authority_plane, g.capability_key, true, %s,
               'authority_management', %s
          FROM jsonb_to_recordset(
              (SELECT grants FROM request_engine.initial_controller_policies
                WHERE policy_key = %s)
          ) AS g(capability_key text, authority_plane text, delegable boolean)
        ON CONFLICT (principal_id, capability_key) WHERE status = 'active'
        DO NOTHING
        """,
        (
            organization_id,
            principal_id,
            principal_id,
            f"e1-e2e:{policy_key}:{uuid4().hex}",
            policy_key,
        ),
    )


def _revoke_capability(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability_key: str,
) -> None:
    rowcount = conn.execute(
        """
        UPDATE request_engine.principal_authority_grants
           SET status = 'revoked',
               revision = revision + 1,
               revoked_at = clock_timestamp(),
               revoked_by_principal_id = %s
         WHERE organization_id = %s
           AND principal_id = %s
           AND capability_key = %s
           AND status = 'active'
        """,
        (principal_id, organization_id, principal_id, capability_key),
    ).rowcount
    assert rowcount == 1


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


async def _invite_and_activate(
    client: AsyncClient,
    *,
    root_token: str,
    organization_id: UUID,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> UUID:
    invited = await client.post(
        "/v1/staff/members/native",
        headers=_tenant_headers(
            token=root_token,
            organization_id=organization_id,
            idempotency_key=f"e1-invite-{uuid4().hex}",
        ),
        json={
            "identity_authority_id": str(identity_authority_id),
            "native_identity_id": str(native_identity_id),
            "provenance_reference": "controller-policy-e2e-invite",
        },
    )
    assert invited.status_code == 201, invited.text
    membership_id = UUID(invited.json()["membership_id"])
    principal_id = UUID(invited.json()["principal_id"])
    activated = await client.put(
        f"/v1/staff/members/{membership_id}/status",
        headers=_tenant_headers(
            token=root_token,
            organization_id=organization_id,
            idempotency_key=f"e1-activate-{uuid4().hex}",
        ),
        json={
            "expected_revision": 1,
            "target_status": "active",
            "provenance_reference": "controller-policy-e2e-activate",
        },
    )
    assert activated.status_code == 200, activated.text
    return principal_id


def _upgrade_body(
    *,
    target_principal_id: UUID,
    expected_authority_revision: int,
    target_policy_key: str = _V3,
) -> dict[str, object]:
    return {
        "target_principal_id": str(target_principal_id),
        "source_policy_key": _V1,
        "target_policy_key": target_policy_key,
        "expected_authority_revision": expected_authority_revision,
    }


@pytest.mark.asyncio
async def test_controller_policy_upgrade_http_journey(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "controller-policy-root-password-1"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"root-{uuid4().hex}@example.test",
        password=root_password,
    )
    first_target = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"target-a-{uuid4().hex}@example.test",
        password="controller-policy-target-a-2",
    )
    second_target = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"target-b-{uuid4().hex}@example.test",
        password="controller-policy-target-b-3",
    )
    foreign_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"foreign-{uuid4().hex}@example.test",
        password="controller-policy-foreign-4",
    )
    organization_id, root_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    foreign_organization_id, foreign_root_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=foreign_identity.native_identity_id,
    )
    _insert_policy_grants(
        e2e_admin_conn,
        organization_id=organization_id,
        principal_id=root_principal_id,
        policy_key=_V4,
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
        target_a = await _invite_and_activate(
            client,
            root_token=root_token,
            organization_id=organization_id,
            identity_authority_id=authority_id,
            native_identity_id=first_target.native_identity_id,
        )
        _insert_policy_grants(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=target_a,
            policy_key=_V1,
        )
        before = _active_capabilities(
            e2e_admin_conn, organization_id=organization_id, principal_id=target_a
        )
        key = f"e1-upgrade-{uuid4().hex}"
        body = _upgrade_body(
            target_principal_id=target_a,
            expected_authority_revision=_principal_revision(e2e_admin_conn, target_a),
        )
        upgraded = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=key,
            ),
            json=body,
        )
        assert upgraded.status_code == 200, upgraded.text
        assert upgraded.headers["cache-control"] == "no-store"
        returned_revision = upgraded.json()["authority_revision"]
        assert returned_revision == _principal_revision(e2e_admin_conn, target_a)
        replay = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=key,
            ),
            json=body,
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == upgraded.json()

        after = _active_capabilities(
            e2e_admin_conn, organization_id=organization_id, principal_id=target_a
        )
        assert after == before | {"agent.read", "authority.read_self"}
        provenance = e2e_admin_conn.execute(
            """
            SELECT count(*) FROM request_engine.principal_authority_grants
             WHERE organization_id = %s AND principal_id = %s
               AND provenance_kind = 'controller_policy_upgrade'
               AND provenance_reference = %s
            """,
            (organization_id, target_a, f"policy:{_V3};source:{_V1}"),
        ).fetchone()
        assert provenance == (2,)
        audit = e2e_admin_conn.execute(
            """
            SELECT count(*), bool_and(actor_principal_id = %s),
                   bool_and(aggregate_kind = 'TenantController')
              FROM request_engine.audit_records
             WHERE organization_id = %s
               AND command_name = 'controller_policy_upgrade'
               AND aggregate_id = %s
            """,
            (root_principal_id, organization_id, target_a),
        ).fetchone()
        assert audit == (1, True, True)

        self_upgrade = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"e1-self-{uuid4().hex}",
            ),
            json=_upgrade_body(
                target_principal_id=root_principal_id,
                expected_authority_revision=_principal_revision(e2e_admin_conn, root_principal_id),
                target_policy_key=_V4,
            ),
        )
        assert self_upgrade.status_code == 403, self_upgrade.text

        _revoke_capability(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=root_principal_id,
            capability_key="authority.read_self",
        )
        target_b = await _invite_and_activate(
            client,
            root_token=root_token,
            organization_id=organization_id,
            identity_authority_id=authority_id,
            native_identity_id=second_target.native_identity_id,
        )
        _insert_policy_grants(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=target_b,
            policy_key=_V1,
        )
        target_b_before = _active_capabilities(
            e2e_admin_conn, organization_id=organization_id, principal_id=target_b
        )
        over_ceiling = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"e1-ceiling-{uuid4().hex}",
            ),
            json=_upgrade_body(
                target_principal_id=target_b,
                expected_authority_revision=_principal_revision(e2e_admin_conn, target_b),
            ),
        )
        assert over_ceiling.status_code == 403, over_ceiling.text
        assert (
            _active_capabilities(
                e2e_admin_conn, organization_id=organization_id, principal_id=target_b
            )
            == target_b_before
        )

        unknown_policy = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"e1-unknown-{uuid4().hex}",
            ),
            json=_upgrade_body(
                target_principal_id=target_b,
                expected_authority_revision=_principal_revision(e2e_admin_conn, target_b),
                target_policy_key="tenant-controller-unknown",
            ),
        )
        assert unknown_policy.status_code == 422, unknown_policy.text

        foreign_before = _active_capabilities(
            e2e_admin_conn,
            organization_id=foreign_organization_id,
            principal_id=foreign_root_id,
        )
        foreign = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"e1-foreign-{uuid4().hex}",
            ),
            json=_upgrade_body(
                target_principal_id=foreign_root_id,
                expected_authority_revision=_principal_revision(e2e_admin_conn, foreign_root_id),
            ),
        )
        absent = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(
                token=root_token,
                organization_id=organization_id,
                idempotency_key=f"e1-absent-{uuid4().hex}",
            ),
            json=_upgrade_body(target_principal_id=uuid4(), expected_authority_revision=1),
        )
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()
        assert (
            _active_capabilities(
                e2e_admin_conn,
                organization_id=foreign_organization_id,
                principal_id=foreign_root_id,
            )
            == foreign_before
        )

        missing_key = await client.post(
            "/v1/controller-policy-upgrades",
            headers=_tenant_headers(token=root_token, organization_id=organization_id),
            json=_upgrade_body(
                target_principal_id=target_b,
                expected_authority_revision=_principal_revision(e2e_admin_conn, target_b),
            ),
        )
        assert missing_key.status_code == 422, missing_key.text

        openapi = app.openapi()
        operation = openapi["paths"]["/v1/controller-policy-upgrades"]["post"]
        assert operation["operationId"] == "controller_policy_upgrade"
        assert operation["x-request-engine-capability"] == "controller_policy_upgrade"
        assert operation["x-request-engine-owner"] == "tenancy"
        assert "x-request-engine-tool-name" not in operation
