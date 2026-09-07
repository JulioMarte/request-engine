from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, Error

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]


def _organization(conn: PgConnection) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.organizations (organization_key, display_name) "
        "VALUES (%s, 'Authority Tenant') RETURNING id",
        (f"authority-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _principal(conn: PgConnection, organization_id: UUID | None, *, platform: bool = False) -> UUID:
    if platform:
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
    delegable: bool,
    grantor_id: UUID | None,
    provenance_kind: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            organization_id,
            principal_id,
            principal_plane,
            authority_plane,
            capability_key,
            delegable,
            grantor_id,
            provenance_kind,
            f"proof:{uuid4().hex}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def test_platform_and_tenant_authority_planes_are_structurally_separate(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    platform_id = _principal(admin_conn, None, platform=True)
    tenant_id = _principal(admin_conn, organization_id)

    _grant(
        admin_conn,
        principal_id=platform_id,
        organization_id=None,
        principal_plane="platform",
        authority_plane="platform",
        capability_key="organization.provision",
        delegable=True,
        grantor_id=None,
        provenance_kind="trust_bootstrap",
    )
    _grant(
        admin_conn,
        principal_id=tenant_id,
        organization_id=organization_id,
        principal_plane="tenant",
        authority_plane="tenant_control",
        capability_key="staff.manage_authority",
        delegable=False,
        grantor_id=platform_id,
        provenance_kind="provisioning",
    )

    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (platform_id,),
    ).fetchone() == (2,)
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (tenant_id,),
    ).fetchone() == (2,)

    with pytest.raises(Error) as platform_operational:
        _grant(
            admin_conn,
            principal_id=platform_id,
            organization_id=None,
            principal_plane="platform",
            authority_plane="operational",
            capability_key="appointments.book",
            delegable=False,
            grantor_id=platform_id,
            provenance_kind="authority_management",
        )
    assert platform_operational.value.sqlstate == "23514"

    with pytest.raises(Error) as tenant_platform:
        _grant(
            admin_conn,
            principal_id=tenant_id,
            organization_id=organization_id,
            principal_plane="tenant",
            authority_plane="platform",
            capability_key="organization.provision",
            delegable=False,
            grantor_id=platform_id,
            provenance_kind="provisioning",
        )
    assert tenant_platform.value.sqlstate == "23514"


def test_possession_delegability_and_revocation_are_independent_auditable_facts(
    admin_conn: PgConnection,
) -> None:
    organization_id = _organization(admin_conn)
    principal_id = _principal(admin_conn, organization_id)
    grantor_id = _principal(admin_conn, organization_id)
    grant_id = _grant(
        admin_conn,
        principal_id=principal_id,
        organization_id=organization_id,
        principal_plane="tenant",
        authority_plane="operational",
        capability_key="appointments.book",
        delegable=False,
        grantor_id=grantor_id,
        provenance_kind="authority_management",
    )
    assert admin_conn.execute(
        "SELECT delegable, status, revision FROM request_engine.principal_authority_grants "
        "WHERE id = %s",
        (grant_id,),
    ).fetchone() == (False, "active", 1)

    admin_conn.execute(
        "UPDATE request_engine.principal_authority_grants "
        "SET status = 'revoked', revision = 2, revoked_at = clock_timestamp(), "
        "revoked_by_principal_id = %s WHERE id = %s",
        (grantor_id, grant_id),
    )
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (3,)

    with pytest.raises(Error) as mutation:
        admin_conn.execute(
            "UPDATE request_engine.principal_authority_grants SET delegable = true WHERE id = %s",
            (grant_id,),
        )
    assert mutation.value.sqlstate == "55000"
    with pytest.raises(Error) as deletion:
        admin_conn.execute(
            "DELETE FROM request_engine.principal_authority_grants WHERE id = %s",
            (grant_id,),
        )
    assert deletion.value.sqlstate == "55000"

    replacement = _grant(
        admin_conn,
        principal_id=principal_id,
        organization_id=organization_id,
        principal_plane="tenant",
        authority_plane="operational",
        capability_key="appointments.book",
        delegable=True,
        grantor_id=grantor_id,
        provenance_kind="authority_management",
    )
    assert replacement != grant_id


def test_tenant_runtime_reads_only_own_grants_and_cannot_mutate_them(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _organization(admin_conn)
    other_organization_id = _organization(admin_conn)
    tenant_id = _principal(admin_conn, organization_id)
    other_tenant_id = _principal(admin_conn, other_organization_id)
    platform_id = _principal(admin_conn, None, platform=True)
    for principal_id, org_id, plane, capability in (
        (tenant_id, organization_id, "tenant", "appointments.book"),
        (other_tenant_id, other_organization_id, "tenant", "appointments.read"),
        (platform_id, None, "platform", "organization.provision"),
    ):
        _grant(
            admin_conn,
            principal_id=principal_id,
            organization_id=org_id,
            principal_plane=plane,
            authority_plane="platform" if plane == "platform" else "operational",
            capability_key=capability,
            delegable=False,
            grantor_id=None,
            provenance_kind="trust_bootstrap",
        )

    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )
        assert app_conn.execute(
            "SELECT principal_id, capability_key FROM request_engine.principal_authority_grants"
        ).fetchall() == [(tenant_id, "appointments.book")]
        with pytest.raises(Error) as insert_denied:
            app_conn.execute(
                "INSERT INTO request_engine.principal_authority_grants "
                "(organization_id, principal_id, principal_plane, authority_plane, capability_key, "
                "provenance_kind, provenance_reference) "
                "VALUES (%s, %s, 'tenant', 'operational', 'appointments.cancel', "
                "'trust_bootstrap', 'runtime')",
                (organization_id, tenant_id),
            )
        assert insert_denied.value.sqlstate == "42501"
    finally:
        app_conn.close()
