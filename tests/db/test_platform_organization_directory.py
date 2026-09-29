"""PostgreSQL proof for the private platform organization directory."""

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection, sql

PgConnection = Connection[Any]
pytestmark = [pytest.mark.postgres, pytest.mark.invariant, pytest.mark.security]


@pytest.fixture
def organization_read_conn(
    admin_conn: PgConnection,
    pg_conninfo: str,
) -> Iterator[PgConnection]:
    role_name = f"re_org_read_{uuid4().hex[:12]}"
    password = uuid4().hex
    admin_conn.execute(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOINHERIT NOBYPASSRLS NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
        ).format(sql.Identifier(role_name), sql.Literal(password))
    )
    admin_conn.execute(
        sql.SQL("GRANT USAGE ON SCHEMA request_platform TO {}").format(sql.Identifier(role_name))
    )
    admin_conn.execute(
        sql.SQL(
            "GRANT EXECUTE ON FUNCTION "
            "request_platform.read_platform_organizations(uuid,uuid,integer) TO {}"
        ).format(sql.Identifier(role_name))
    )
    parts = dict(part.split("=", 1) for part in pg_conninfo.split())
    connection: PgConnection = psycopg.connect(
        f"host={parts['host']} port={parts['port']} dbname={parts['dbname']} "
        f"user={role_name} password={password}"
    )
    try:
        yield connection
    finally:
        connection.close()
        admin_conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
        admin_conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))


def test_directory_is_bounded_and_available_only_through_explicit_execute(
    admin_conn: PgConnection,
    organization_read_conn: PgConnection,
) -> None:
    organization_id = uuid4()
    organization_key = f"org-{organization_id.hex[:12]}"
    admin_conn.execute(
        """
        INSERT INTO request_engine.organizations (id, organization_key, display_name)
        VALUES (%s, %s, 'Directory proof')
        """,
        (organization_id, organization_key),
    )
    try:
        row = organization_read_conn.execute(
            """
            SELECT organization_id, organization_key, display_name
              FROM request_platform.read_platform_organizations(%s, NULL, 1)
            """,
            (organization_id,),
        ).fetchone()
        assert row == (organization_id, organization_key, "Directory proof")

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            organization_read_conn.execute(
                "SELECT display_name FROM request_engine.organizations WHERE id = %s",
                (organization_id,),
            )
        organization_read_conn.rollback()

        with pytest.raises(psycopg.errors.InvalidParameterValue):
            organization_read_conn.execute(
                "SELECT * FROM request_platform.read_platform_organizations(NULL, NULL, 0)"
            )
        organization_read_conn.rollback()
    finally:
        admin_conn.execute(
            "DELETE FROM request_engine.organizations WHERE id = %s", (organization_id,)
        )


def test_platform_owner_v4_contains_the_directory_capability(admin_conn: PgConnection) -> None:
    grants = admin_conn.execute(
        """
        SELECT grants
          FROM request_engine.platform_owner_policies
         WHERE policy_key = 'platform-owner-v4' AND revision = 4
        """
    ).fetchone()
    assert grants is not None
    assert {item["capability_key"] for item in grants[0]} >= {"platform.organization.read"}
    privilege = admin_conn.execute(
        """
        SELECT has_function_privilege(
            'public',
            'request_platform.read_platform_organizations(uuid,uuid,integer)',
            'EXECUTE'
        )
        """
    ).fetchone()
    assert privilege is not None
    assert not privilege[0]


def test_future_platform_owner_adopts_directory_capability(admin_conn: PgConnection) -> None:
    principal_row = admin_conn.execute(
        """
        INSERT INTO request_engine.principals (
            principal_plane, principal_kind, external_subject
        ) VALUES ('platform', 'human', %s) RETURNING id
        """,
        (f"future-owner-{uuid4().hex}",),
    ).fetchone()
    assert principal_row is not None
    principal_id = cast(UUID, principal_row[0])
    admin_conn.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        ) VALUES (%s, 'platform', 'platform', 'platform.owner.manage_lifecycle',
                  true, 'trust_bootstrap', %s)
        """,
        (principal_id, f"future-owner-proof:{uuid4().hex}"),
    )
    adopted = admin_conn.execute(
        """
        SELECT status, delegable
          FROM request_engine.principal_authority_grants
         WHERE principal_id = %s AND capability_key = 'platform.organization.read'
        """,
        (principal_id,),
    ).fetchone()
    assert adopted == ("active", False)
