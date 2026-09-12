"""Add an immutable controller policy with explicit agent inspection authority."""

from collections.abc import Sequence

from alembic import op

revision: str = "0037_agent_inspection_policy"
down_revision: str | Sequence[str] | None = "0036_initial_controller_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    # v1 is immutable migration data, not the mutable application registry.
    # No root facts or existing grants are updated by this additive catalog insert.
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies (policy_key, revision, grants)
        SELECT 'tenant-controller-v2', 2, grants ||
            '[{"capability_key": "agent.read",
               "authority_plane": "tenant_control", "delegable": true}]'
            ::jsonb
          FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v1'
    """)


def downgrade() -> None:
    raise RuntimeError("Initial controller policy provenance is append-only; roll forward")
