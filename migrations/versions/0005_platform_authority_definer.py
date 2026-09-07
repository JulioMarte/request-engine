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


def upgrade() -> None:
    op.execute(
        "CREATE ROLE request_engine_platform_definer WITH "
        "NOSUPERUSER INHERIT NOCREATEROLE NOCREATEDB NOLOGIN "
        "NOREPLICATION BYPASSRLS CONNECTION LIMIT -1"
    )
    op.execute("GRANT USAGE ON SCHEMA request_engine TO request_engine_platform_definer")
    op.execute(
        "GRANT SELECT (id, principal_kind, active, authority_revision, principal_plane) "
        "ON request_engine.principals TO request_engine_platform_definer"
    )
    op.execute(
        "GRANT SELECT (principal_id, principal_plane, authority_plane, status, "
        "capability_key, delegable) ON request_engine.principal_authority_grants "
        "TO request_engine_platform_definer"
    )

    # PostgreSQL requires the prospective function owner to have CREATE on the
    # containing schema. Grant it only for the ownership transfer and revoke it
    # immediately; runtime execution needs no CREATE authority on request_platform.
    op.execute(
        "GRANT USAGE, CREATE ON SCHEMA request_platform "
        "TO request_engine_platform_definer"
    )
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        "OWNER TO request_engine_platform_definer"
    )
    op.execute("REVOKE CREATE ON SCHEMA request_platform FROM request_engine_platform_definer")
    op.execute(
        "REVOKE ALL ON FUNCTION request_platform.read_principal_authority(uuid) FROM PUBLIC"
    )


def downgrade() -> None:
    op.execute(
        "GRANT CREATE ON SCHEMA request_platform TO request_engine_schema_owner"
    )
    op.execute(
        "ALTER FUNCTION request_platform.read_principal_authority(uuid) "
        "OWNER TO request_engine_schema_owner"
    )
    op.execute(
        "REVOKE CREATE ON SCHEMA request_platform FROM request_engine_schema_owner"
    )
    op.execute("DROP OWNED BY request_engine_platform_definer")
    op.execute("DROP ROLE request_engine_platform_definer")
