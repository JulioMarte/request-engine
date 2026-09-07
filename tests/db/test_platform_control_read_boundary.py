from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.invariant,
    pytest.mark.adversarial,
    pytest.mark.security,
]


def _organization(conn: PgConnection) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.organizations (organization_key, display_name) "
        "VALUES (%s, 'Platform Boundary Tenant') RETURNING id",
        (f"platform-boundary-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _principal(conn: PgConnection, organization_id: UUID | None) -> UUID:
    if organization_id is None:
        row = conn.execute(
            "INSERT INTO request_engine.principals "
            "(principal_plane, principal_kind, external_subject) "
            "VALUES ('platform', 'human', %s) RETURNING id",
            (f"platform-{uuid4().hex}",),
        ).fetchone()
    else:
        row = conn.execute(
            "INSERT INTO request_engine.principals "
            "(organization_id, principal_kind, external_subject) "
            "VALUES (%s, 'human', %s) RETURNING id",
            (organization_id, f"tenant-{uuid4().hex}"),
        ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _grant(
    conn: PgConnection,
    *,
    principal_id: UUID,
    organization_id: UUID | None,
    principal_plane: str,
    authority_plane: str,
    capability_key: str,
) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, provenance_kind, provenance_reference
        ) VALUES (%s, %s, %s, %s, %s, 'trust_bootstrap', %s)
        """,
        (
            organization_id,
            principal_id,
            principal_plane,
            authority_plane,
            capability_key,
            f"proof:{uuid4().hex}",
        ),
    )


def test_platform_control_role_has_no_direct_table_authority(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    platform_id = _principal(admin_conn, None)
    _grant(
        admin_conn,
        principal_id=platform_id,
        organization_id=None,
        principal_plane="platform",
        authority_plane="platform",
        capability_key="organization.provision",
    )

    row = admin_conn.execute(
        "SELECT rolcanlogin, rolbypassrls FROM pg_roles "
        "WHERE rolname = 'request_engine_platform_control'"
    ).fetchone()
    assert row == (False, False)

    control_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        control_conn.execute("SET ROLE request_engine_platform_control")
        with pytest.raises(Error) as direct_read:
            control_conn.execute(
                "SELECT id FROM request_engine.principals WHERE id = %s",
                (platform_id,),
            )
        assert direct_read.value.sqlstate == "42501"

        assert control_conn.execute(
            "SELECT principal_kind, active, authority_revision, capability_key, delegable "
            "FROM request_platform.read_principal_authority(%s)",
            (platform_id,),
        ).fetchall() == [("human", True, 2, "organization.provision", False)]
    finally:
        control_conn.close()


def test_platform_read_boundary_cannot_cross_into_tenant_authority(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn)
    tenant_id = _principal(admin_conn, organization_id)
    _grant(
        admin_conn,
        principal_id=tenant_id,
        organization_id=organization_id,
        principal_plane="tenant",
        authority_plane="tenant_control",
        capability_key="staff.manage_authority",
    )

    control_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        control_conn.execute("SET ROLE request_engine_platform_control")
        control_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )
        assert (
            control_conn.execute(
                "SELECT * FROM request_platform.read_principal_authority(%s)",
                (tenant_id,),
            ).fetchall()
            == []
        )
    finally:
        control_conn.close()

    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        with pytest.raises(Error) as app_call:
            app_conn.execute(
                "SELECT * FROM request_platform.read_principal_authority(%s)",
                (tenant_id,),
            )
        assert app_call.value.sqlstate == "42501"
    finally:
        app_conn.close()
