"""Restore the platform binding read through its private read-only definer.

Revision ID: 0034_platform_binding_read
Revises: 0033_staff_terminal_revocation
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034_platform_binding_read"
down_revision: str | Sequence[str] | None = "0033_staff_terminal_revocation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "request_platform_definer"
_FUNCTION = "request_auth.read_platform_identity_bindings(uuid, text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # FORCE RLS correctly hides platform rows from the ordinary schema owner.
    # Use the existing NOLOGIN platform-read definer, not a broader app policy.
    op.execute(
        "GRANT SELECT (id, identity_authority_id, subject_id, principal_id, "
        "principal_plane, organization_id, status, revision) "
        f"ON request_engine.identity_bindings TO {_ROLE}"
    )
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_auth TO {_ROLE}")
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO {_ROLE}")
    op.execute(f"ALTER FUNCTION {_FUNCTION} SET search_path TO pg_catalog, request_engine, pg_temp")
    op.execute(f"REVOKE CREATE ON SCHEMA request_auth FROM {_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO request_engine_app")


def downgrade() -> None:
    raise RuntimeError("Platform binding resolution requires a forward migration")
