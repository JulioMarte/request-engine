"""Append the explicit resource-authority inspection grant to the controller policy.

Block E3 of ``docs/architecture/auth-production-completion-plan.md``. Appends an
immutable ``tenant-controller-v5`` catalog row (v4 plus the operational
``authority.inspect_resource`` query grant). No table, function or backfill is
added; existing roots and revoked grants are neither upgraded nor restored.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0055_authority_inspect_policy"
down_revision: str | Sequence[str] | None = "0054_onboarding_identity_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("""
        INSERT INTO request_engine.initial_controller_policies (policy_key, revision, grants)
        SELECT 'tenant-controller-v5', 5, grants ||
            '[{"capability_key": "authority.inspect_resource",
               "authority_plane": "operational", "delegable": true}]'::jsonb
          FROM request_engine.initial_controller_policies WHERE policy_key='tenant-controller-v4'
    """)


def downgrade() -> None:
    raise RuntimeError("Initial controller policy provenance is append-only; roll forward")
