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
    suffix = uuid4().hex
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (f"identity-{suffix}", f"Identity {suffix}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _tenant_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s) RETURNING id
        """,
        (organization_id, f"legacy-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _platform_principal(conn: PgConnection) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"platform-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _authority(conn: PgConnection) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.identity_authorities (kind, issuer_or_environment)
        VALUES ('native', %s) RETURNING id
        """,
        (f"native-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _bind(
    conn: PgConnection,
    *,
    principal_id: UUID,
    authority_id: UUID,
    subject_id: str,
    organization_id: UUID | None,
    plane: str,
    status: str = "active",
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.identity_bindings (
            organization_id, principal_id, principal_plane,
            identity_authority_id, subject_id, status
        ) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """,
        (organization_id, principal_id, plane, authority_id, subject_id, status),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def test_same_authenticated_subject_can_bind_once_per_tenant_scope(
    admin_conn: PgConnection,
) -> None:
    authority_id = _authority(admin_conn)
    first_org = _organization(admin_conn)
    second_org = _organization(admin_conn)
    first_principal = _tenant_principal(admin_conn, first_org)
    second_principal = _tenant_principal(admin_conn, second_org)
    subject_id = f"subject-{uuid4().hex}"

    first_binding = _bind(
        admin_conn,
        principal_id=first_principal,
        authority_id=authority_id,
        subject_id=subject_id,
        organization_id=first_org,
        plane="tenant",
    )
    _bind(
        admin_conn,
        principal_id=second_principal,
        authority_id=authority_id,
        subject_id=subject_id,
        organization_id=second_org,
        plane="tenant",
    )

    with pytest.raises(Error) as duplicate_live_binding:
        _bind(
            admin_conn,
            principal_id=_tenant_principal(admin_conn, first_org),
            authority_id=authority_id,
            subject_id=subject_id,
            organization_id=first_org,
            plane="tenant",
            status="suspended",
        )
    assert duplicate_live_binding.value.sqlstate == "23505"

    admin_conn.execute(
        """
        UPDATE request_engine.identity_bindings
           SET status = 'revoked', revision = revision + 1, revoked_at = clock_timestamp()
         WHERE id = %s
        """,
        (first_binding,),
    )
    _bind(
        admin_conn,
        principal_id=_tenant_principal(admin_conn, first_org),
        authority_id=authority_id,
        subject_id=subject_id,
        organization_id=first_org,
        plane="tenant",
    )


def test_identity_binding_scope_must_match_principal_plane(
    admin_conn: PgConnection,
) -> None:
    authority_id = _authority(admin_conn)
    organization_id = _organization(admin_conn)
    tenant_principal = _tenant_principal(admin_conn, organization_id)
    platform_principal = _platform_principal(admin_conn)

    with pytest.raises(Error) as tenant_as_platform:
        _bind(
            admin_conn,
            principal_id=tenant_principal,
            authority_id=authority_id,
            subject_id=f"subject-{uuid4().hex}",
            organization_id=None,
            plane="platform",
        )
    assert tenant_as_platform.value.sqlstate == "23514"

    with pytest.raises(Error) as platform_as_tenant:
        _bind(
            admin_conn,
            principal_id=platform_principal,
            authority_id=authority_id,
            subject_id=f"subject-{uuid4().hex}",
            organization_id=organization_id,
            plane="tenant",
        )
    assert platform_as_tenant.value.sqlstate == "23514"


def test_binding_state_changes_invalidate_principal_authority_but_last_seen_does_not(
    admin_conn: PgConnection,
) -> None:
    authority_id = _authority(admin_conn)
    organization_id = _organization(admin_conn)
    principal_id = _tenant_principal(admin_conn, organization_id)
    binding_id = _bind(
        admin_conn,
        principal_id=principal_id,
        authority_id=authority_id,
        subject_id=f"subject-{uuid4().hex}",
        organization_id=organization_id,
        plane="tenant",
    )

    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (2,)

    admin_conn.execute(
        "UPDATE request_engine.identity_bindings SET last_seen_at = clock_timestamp() WHERE id = %s",
        (binding_id,),
    )
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (2,)

    admin_conn.execute(
        """
        UPDATE request_engine.identity_bindings
           SET status = 'suspended', revision = revision + 1
         WHERE id = %s
        """,
        (binding_id,),
    )
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (3,)

    admin_conn.execute(
        """
        UPDATE request_engine.identity_bindings
           SET status = 'active', revision = revision + 1
         WHERE id = %s
        """,
        (binding_id,),
    )
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (4,)


def test_tenant_runtime_sees_only_binding_rows_for_selected_tenant(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    authority_id = _authority(admin_conn)
    tenant_org = _organization(admin_conn)
    foreign_org = _organization(admin_conn)
    tenant_binding = _bind(
        admin_conn,
        principal_id=_tenant_principal(admin_conn, tenant_org),
        authority_id=authority_id,
        subject_id=f"tenant-{uuid4().hex}",
        organization_id=tenant_org,
        plane="tenant",
    )
    foreign_binding = _bind(
        admin_conn,
        principal_id=_tenant_principal(admin_conn, foreign_org),
        authority_id=authority_id,
        subject_id=f"foreign-{uuid4().hex}",
        organization_id=foreign_org,
        plane="tenant",
    )
    platform_binding = _bind(
        admin_conn,
        principal_id=_platform_principal(admin_conn),
        authority_id=authority_id,
        subject_id=f"platform-{uuid4().hex}",
        organization_id=None,
        plane="platform",
    )

    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(tenant_org),),
        )
        visible = app_conn.execute(
            "SELECT id FROM request_engine.identity_bindings ORDER BY id"
        ).fetchall()
        assert visible == [(tenant_binding,)]
        assert foreign_binding not in {row[0] for row in visible}
        assert platform_binding not in {row[0] for row in visible}
    finally:
        app_conn.close()
