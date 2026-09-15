"""Append explicit self-inspection authority for newly provisioned controllers."""

from collections.abc import Sequence

from alembic import op

revision: str = "0038_self_authority_policy"
down_revision: str | Sequence[str] | None = "0037_agent_inspection_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies (policy_key, revision, grants)
        SELECT 'tenant-controller-v3', 3, grants ||
            '[{"capability_key": "authority.read_self",
               "authority_plane": "operational", "delegable": true}]'::jsonb
          FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v2'
    """)


def downgrade() -> None:
    raise RuntimeError("Initial controller policy provenance is append-only; roll forward")
