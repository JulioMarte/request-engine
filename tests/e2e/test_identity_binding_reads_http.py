"""End-to-end HTTP proof for the tenant identity-binding read projection.

Protects the current guarantee that ``GET /v1/identity-bindings`` and
``GET /v1/identity-bindings/{binding_id}`` require an explicit current
``identity.binding.read`` grant, are tenant-opaque, never expose ``subject_id``,
carry ``Cache-Control: no-store``, reject invalid filters and are mutation-free.
"""

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
_SIGNING_KEY = b"native-identity-binding-e2e-signing-key-v1"
_READ_CAPABILITY = "identity.binding.read"
_VIEW_FIELDS = {
    "binding_id",
    "principal_id",
    "identity_authority_id",
    "status",
    "revision",
    "created_at",
}


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
        (f"native-identity-binding-e2e-{uuid4().hex}",),
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
        (f"native-binding-platform-{uuid4().hex}",),
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
        (provisioner_id, f"native-binding-root:{uuid4().hex}"),
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
                f"native-binding-{organization_id.hex}",
                "Native Identity Binding E2E",
                organization_party_id,
                controller_principal_id,
                identity_authority_id,
                native_identity_id,
                f"native-binding-root:{uuid4().hex}",
            ),
        ).fetchone()
        assert row is not None
    finally:
        conn.execute("RESET ROLE")
    return organization_id, controller_principal_id


def _controller_binding_id(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
) -> UUID:
    return _uuid_row(
        conn,
        """
        SELECT id FROM request_engine.identity_bindings
         WHERE organization_id = %s AND principal_plane = 'tenant' AND principal_id = %s
        """,
        (organization_id, principal_id),
    )


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


def _grant_read_capability(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            %s, %s, 'tenant', 'tenant_control', %s, false, %s,
            'authority_management', %s
        )
        """,
        (
            organization_id,
            principal_id,
            _READ_CAPABILITY,
            principal_id,
            f"identity-binding-read:{uuid4().hex}",
        ),
    )


def _mutation_fingerprint(conn: PgConnection, organization_id: UUID) -> tuple[object, ...]:
    return (
        conn.execute(
            "SELECT count(*) FROM request_engine.identity_bindings WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
        conn.execute(
            "SELECT count(*) FROM request_engine.principal_authority_grants "
            "WHERE organization_id=%s",
            (organization_id,),
        ).fetchone(),
    )


@pytest.mark.asyncio
async def test_identity_binding_read_projection_over_http(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    authority_id = _create_native_authority(e2e_admin_conn)
    enrollment_runtime = build_native_auth_runtime(e2e_session_factory)
    root_password = "identity-binding-root-e2e-1"
    root_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"binding-root-{uuid4().hex}@example.test",
        password=root_password,
    )
    foreign_identity = await enrollment_runtime.service.enroll_password_identity(
        identity_authority_id=authority_id,
        login_handle=f"binding-foreign-{uuid4().hex}@example.test",
        password="identity-binding-foreign-e2e-2",
    )
    organization_id, controller_principal_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=root_identity.native_identity_id,
    )
    foreign_organization_id, foreign_controller_id = _provision_tenant_root(
        e2e_admin_conn,
        identity_authority_id=authority_id,
        native_identity_id=foreign_identity.native_identity_id,
    )
    controller_binding_id = _controller_binding_id(
        e2e_admin_conn,
        organization_id=organization_id,
        principal_id=controller_principal_id,
    )
    foreign_binding_id = _controller_binding_id(
        e2e_admin_conn,
        organization_id=foreign_organization_id,
        principal_id=foreign_controller_id,
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
        headers = _tenant_headers(token=root_token, organization_id=organization_id)

        denied = await client.get("/v1/identity-bindings", headers=headers)
        assert denied.status_code == 403, denied.text

        _grant_read_capability(
            e2e_admin_conn,
            organization_id=organization_id,
            principal_id=controller_principal_id,
        )

        before = _mutation_fingerprint(e2e_admin_conn, organization_id)
        listing = await client.get("/v1/identity-bindings", headers=headers)
        assert listing.status_code == 200, listing.text
        assert listing.headers["cache-control"] == "no-store"
        body = listing.json()
        assert set(body) == {"items", "next_cursor"}
        assert body["next_cursor"] is None
        assert len(body["items"]) >= 1
        listed_ids = {UUID(item["binding_id"]) for item in body["items"]}
        assert controller_binding_id in listed_ids
        assert foreign_binding_id not in listed_ids
        for item in body["items"]:
            assert set(item) == _VIEW_FIELDS
            assert "subject_id" not in item
            assert item["revision"] >= 1
            assert item["status"] in {"pending", "active", "suspended", "revoked"}

        detail = await client.get(f"/v1/identity-bindings/{controller_binding_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert detail.headers["cache-control"] == "no-store"
        assert UUID(detail.json()["binding_id"]) == controller_binding_id

        absent = await client.get(f"/v1/identity-bindings/{uuid4()}", headers=headers)
        foreign = await client.get(f"/v1/identity-bindings/{foreign_binding_id}", headers=headers)
        assert absent.status_code == foreign.status_code == 404
        assert absent.json() == foreign.json()

        invalid_status = await client.get(
            "/v1/identity-bindings", headers=headers, params={"status": "not-a-status"}
        )
        assert invalid_status.status_code == 422, invalid_status.text
        invalid_limit = await client.get(
            "/v1/identity-bindings", headers=headers, params={"limit": 101}
        )
        assert invalid_limit.status_code == 422, invalid_limit.text

        after = _mutation_fingerprint(e2e_admin_conn, organization_id)
        assert after == before
