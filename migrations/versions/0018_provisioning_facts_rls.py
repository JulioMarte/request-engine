"""Apply tenant-bound RLS to provisioning provenance facts.

Revision ID: 0018_provisioning_facts_rls
Revises: 0017_native_root_provenance
Create Date: 2026-09-08

Provisioning provenance is written through the Platform control definer, but
both tables carry organization_id and therefore remain subject to the same
catalog-level tenant isolation invariant as every other tenant-scoped relation.
ACL denial remains in place; RLS is defense in depth rather than a new runtime
surface.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018_provisioning_facts_rls"
down_revision: str | Sequence[str] | None = "0017_native_root_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "organization_provisioning_facts",
    "organization_root_provisioning_facts",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE request_engine.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE request_engine.{table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation
                ON request_engine.{table}
                USING (
                    organization_id = request_engine.current_organization_id()
                )
                WITH CHECK (
                    organization_id = request_engine.current_organization_id()
                )
            """
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY {table}_tenant_isolation ON request_engine.{table}")
        op.execute(f"ALTER TABLE request_engine.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE request_engine.{table} DISABLE ROW LEVEL SECURITY")
