"""Shared native-auth provisioning world helpers for first-class Principal E2E journeys."""

from __future__ import annotations

from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from httpx import AsyncClient
from psycopg import Connection

PgConnection = Connection[Any]


def uuid_row(
    conn: PgConnection,
    query: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def principal_revision(conn: PgConnection, principal_id: UUID) -> int:
    row = conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone()
    assert row is not None
    return int(row[0])


def bind_platform_identity(
    conn: PgConnection,
    *,
    principal_id: UUID,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.identity_bindings (
            id, principal_id, principal_plane, identity_authority_id,
            subject_id, status
        ) VALUES (%s, %s, 'platform', %s, %s, 'active')
        """,
        (uuid4(), principal_id, identity_authority_id, str(native_identity_id)),
    )


def provision_tenant_root(
    conn: PgConnection,
    *,
    identity_authority_id: UUID,
    native_identity_id: UUID,
) -> tuple[UUID, UUID]:
    provisioner_id = uuid_row(
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
        (str(principal_revision(conn, provisioner_id)),),
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


def grant_controller_delegable_operational_authority(
    conn: PgConnection,
    *,
    organization_id: UUID,
    controller_principal_id: UUID,
    capability_key: str,
) -> None:
    """Seed one active delegable operational-plane grant for the tenant controller."""

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


def workload_authority(conn: PgConnection) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.identity_authorities (
            kind, issuer_or_environment
        ) VALUES ('workload', %s) RETURNING id
        """,
        (f"native-agent-workload-{uuid4().hex}",),
    )


def tenant_headers(
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


async def login(client: AsyncClient, *, login_handle: str, password: str) -> str:
    response = await client.post(
        "/auth/native/sessions",
        json={"login_handle": login_handle, "password": password},
    )
    assert response.status_code == 201, response.text
    return cast(str, response.json()["access_token"])
