"""Isolate platform authority reads behind a dedicated definer role.

Revision ID: 0005_platform_auth_definer
Revises: 0004_platform_auth_read
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_platform_auth_definer"
down_revision: str | Sequence[str] | None = "0004_platform_auth_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "request_platform_definer"


def upgrade() -> None:
    # PostgreSQL roles are cluster-global while Alembic revisions are database-local.
    # The accepted 0001 reserves request_engine_* for its exact immutable topology,
    # so this post-baseline role uses a separate namespace and is reusable by another
    # Request Engine database only when its cluster-global elevation matches exactly.
    op.execute(
        f"""
        DO $$
        DECLARE
            v_role_mismatch boolean;
            v_has_membership boolean;
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = '{_ROLE}') THEN
                EXECUTE 'CREATE ROLE {_ROLE} WITH '
                    'NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOLOGIN '
                    'NOREPLICATION BYPASSRLS CONNECTION LIMIT -1';
            ELSE
                SELECT NOT (
                    NOT rolsuper
                    AND rolinherit
                    AND NOT rolcreaterole
                    AND NOT rolcreatedb
                    AND NOT rolcanlogin
                    AND NOT rolreplication
                    AND rolbypassrls
                    AND rolconnlimit = -1
                    AND rolvaliduntil IS NULL
                    AND rolpassword IS NULL
                )
                  INTO v_role_mismatch
                  FROM pg_catalog.pg_authid
                 WHERE rolname = '{_ROLE}';

                SELECT EXISTS (
                    SELECT 1
                      FROM pg_catalog.pg_auth_members AS membership
                      JOIN pg_catalog.pg_roles AS parent
                        ON parent.oid = membership.roleid
                      JOIN pg_catalog.pg_roles AS member
                        ON member.oid = membership.member
                     WHERE parent.rolname = '{_ROLE}'
                        OR member.rolname = '{_ROLE}'
                )
                  INTO v_has_membership;

                IF v_role_mismatch OR v_has_membership THEN
                    RAISE EXCEPTION 'existing {_ROLE} does not match audited topology'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA request_engine TO {_ROLE}")
    op.execute(
        "GRANT SELECT (id, principal_kind, active, authority_revision, principal_plane) "
        f"ON request_engine.principals TO {_ROLE}"
    )
    op.execute(
        "GRANT SELECT (principal_id, principal_plane, authority_plane, status, "
        "capability_key, delegable) ON request_engine.principal_authority_grants "
        f"TO {_ROLE}"
    )

    # PostgreSQL requires the prospective function owner to have CREATE on the
    # containing schema. Grant it only for the ownership transfer and revoke it
    # immediately; runtime execution needs no CREATE authority on request_platform.
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_ROLE}")
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        f"OWNER TO {_ROLE}"
    )
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        "SET search_path TO pg_catalog, request_engine, pg_temp"
    )
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_ROLE}")
    op.execute("REVOKE ALL ON FUNCTION request_platform.read_principal_authority(uuid) FROM PUBLIC")


def downgrade() -> None:
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        "OWNER TO request_engine_schema_owner"
    )
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        "SET search_path TO pg_catalog, request_engine"
    )
    op.execute(
        "REVOKE SELECT (id, principal_kind, active, authority_revision, principal_plane) "
        f"ON request_engine.principals FROM {_ROLE}"
    )
    op.execute(
        "REVOKE SELECT (principal_id, principal_plane, authority_plane, status, "
        "capability_key, delegable) ON request_engine.principal_authority_grants "
        f"FROM {_ROLE}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA request_engine FROM {_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA request_platform FROM {_ROLE}")
    # Do not DROP ROLE here: another database in the same PostgreSQL cluster may
    # already depend on the same verified cluster-global definer identity.
