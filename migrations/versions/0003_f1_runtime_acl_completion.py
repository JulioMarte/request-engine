"""Complete F1 runtime privileges for assignment availability replacement.

Revision ID: 0003_f1_runtime_acl
Revises: 0002_f1_supply
Create Date: 2026-08-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_f1_runtime_acl"
down_revision: str | Sequence[str] | None = "0002_f1_supply"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # set_resource_location_availability replaces the assignment-scoped window
    # set atomically (DELETE old rows, then INSERT the desired set). The app
    # role already has SELECT/INSERT/UPDATE here; grant only the missing verb.
    # FORCE RLS remains authoritative for tenant isolation, and the worker
    # deliberately receives no F1 relation privilege.
    op.execute(
        "GRANT DELETE ON TABLE request_engine.resource_location_availability "
        "TO request_engine_app"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE DELETE ON TABLE request_engine.resource_location_availability "
        "FROM request_engine_app"
    )
