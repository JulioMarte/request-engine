"""Tenant-bound RLS policy on ``account_organization_creations``.

Schema-change checklist (migrations/AGENTS.md):

* Business owner: Tenancy. No operation changes; ``self_organization_create`` keeps
  writing through its SECURITY DEFINER function.
* Guarantees: INV-TENANT-001 (every ``request_engine`` table carrying
  ``organization_id`` has RLS with a tenant-bound policy) and
  INV-SELF-SERVICE-ACCOUNT-001 (unchanged).
* Change class: CONTROLLED additive. ``0006_self_service_accounts`` created the
  table with ENABLE + FORCE RLS and no policy, which already denied every runtime
  role (they hold no table privilege either). The catalog invariant still requires a
  policy bound to ``current_organization_id()`` on a table with ``organization_id``;
  this adds it. No grant, row, function or other policy changes, so runtime
  visibility stays exactly the same (no privilege, so no rows).
* Authoritative objects: one policy on ``request_engine.account_organization_creations``.
* Downgrade: refused (roll forward), like the migration that created the table.
"""

from alembic import op

revision: str = "0007_account_creation_rls"
down_revision: str | None = "0006_self_service_accounts"
branch_labels: str | None = None
depends_on: str | None = None

_POLICY = """
CREATE POLICY account_organization_creations_tenant_policy
    ON request_engine.account_organization_creations
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());
"""


def upgrade() -> None:
    op.execute(_POLICY)


def downgrade() -> None:
    raise RuntimeError("account ownership facts are immutable history; roll forward")
