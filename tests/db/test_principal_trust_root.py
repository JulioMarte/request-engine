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


def _create_organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"trust-root-{suffix}", f"Trust Root {suffix}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_tenant_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"tenant-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _create_platform_principal(conn: PgConnection, subject: str | None = None) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s)
        RETURNING id
        """,
        (subject or f"platform-{uuid4().hex}",),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def test_principal_plane_requires_exact_tenant_shape_and_platform_subject_uniqueness(
    admin_conn: PgConnection,
) -> None:
    organization_id = _create_organization(admin_conn)
    tenant_id = _create_tenant_principal(admin_conn, organization_id)
    platform_subject = f"platform-{uuid4().hex}"
    platform_id = _create_platform_principal(admin_conn, platform_subject)

    assert admin_conn.execute(
        "SELECT principal_plane, organization_id, authority_revision "
        "FROM request_engine.principals WHERE id = %s",
        (tenant_id,),
    ).fetchone() == ("tenant", organization_id, 1)
    assert admin_conn.execute(
        "SELECT principal_plane, organization_id, authority_revision "
        "FROM request_engine.principals WHERE id = %s",
        (platform_id,),
    ).fetchone() == ("platform", None, 1)

    with pytest.raises(Error) as tenant_without_org:
        admin_conn.execute(
            """
            INSERT INTO request_engine.principals (
                principal_plane, principal_kind, external_subject
            ) VALUES ('tenant', 'human', %s)
            """,
            (f"invalid-tenant-{uuid4().hex}",),
        )
    assert tenant_without_org.value.sqlstate == "23514"

    with pytest.raises(Error) as platform_with_org:
        admin_conn.execute(
            """
            INSERT INTO request_engine.principals (
                organization_id, principal_plane, principal_kind, external_subject
            ) VALUES (%s, 'platform', 'human', %s)
            """,
            (organization_id, f"invalid-platform-{uuid4().hex}"),
        )
    assert platform_with_org.value.sqlstate == "23514"

    with pytest.raises(Error) as duplicate_platform_subject:
        _create_platform_principal(admin_conn, platform_subject)
    assert duplicate_platform_subject.value.sqlstate == "23505"


def test_tenant_runtime_cannot_observe_create_or_retarget_platform_principals(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> None:
    organization_id = _create_organization(admin_conn)
    tenant_id = _create_tenant_principal(admin_conn, organization_id)
    platform_id = _create_platform_principal(admin_conn)

    app_conn: PgConnection = psycopg.connect(pg_conninfo, autocommit=True)
    try:
        app_conn.execute("SET ROLE request_engine_app")
        app_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(organization_id),),
        )
        assert (
            app_conn.execute(
                "SELECT id FROM request_engine.principals WHERE id = %s",
                (platform_id,),
            ).fetchall()
            == []
        )
        assert app_conn.execute(
            "SELECT id FROM request_engine.principals WHERE id = %s",
            (tenant_id,),
        ).fetchall() == [(tenant_id,)]

        with pytest.raises(Error) as platform_insert:
            app_conn.execute(
                """
                INSERT INTO request_engine.principals (
                    principal_plane, principal_kind, external_subject
                ) VALUES ('platform', 'human', %s)
                """,
                (f"runtime-platform-{uuid4().hex}",),
            )
        assert platform_insert.value.sqlstate == "42501"
    finally:
        app_conn.close()

    with pytest.raises(Error) as retarget:
        admin_conn.execute(
            "UPDATE request_engine.principals "
            "SET principal_plane = 'platform', organization_id = NULL WHERE id = %s",
            (tenant_id,),
        )
    assert retarget.value.sqlstate == "55000"


def test_authority_revision_tracks_principal_and_representation_authority_changes(
    admin_conn: PgConnection,
) -> None:
    organization_id = _create_organization(admin_conn)
    principal_id = _create_tenant_principal(admin_conn, organization_id)
    party_row = admin_conn.execute(
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'organization', 'Trust Root Party')
        RETURNING id
        """,
        (organization_id,),
    ).fetchone()
    assert party_row is not None
    party_id = cast(UUID, party_row[0])

    representation_row = admin_conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_from
        ) VALUES (%s, %s, %s, 'delegated', 'operations.manage_catalog', clock_timestamp())
        RETURNING id
        """,
        (organization_id, principal_id, party_id),
    ).fetchone()
    assert representation_row is not None
    representation_id = cast(UUID, representation_row[0])
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (2,)

    admin_conn.execute(
        "UPDATE request_engine.representations SET status = 'revoked' WHERE id = %s",
        (representation_id,),
    )
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (3,)

    admin_conn.execute(
        "UPDATE request_engine.principals SET active = false WHERE id = %s",
        (principal_id,),
    )
    assert admin_conn.execute(
        "SELECT authority_revision FROM request_engine.principals WHERE id = %s",
        (principal_id,),
    ).fetchone() == (4,)

    with pytest.raises(Error) as revision_jump:
        admin_conn.execute(
            "UPDATE request_engine.principals SET authority_revision = 9 WHERE id = %s",
            (principal_id,),
        )
    assert revision_jump.value.sqlstate == "23514"
