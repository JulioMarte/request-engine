"""Give tenant-bound sessions a scoped fact policy without granting table access."""

from alembic import op

revision: str = "0033_adopt_fact_tenant_rls"
down_revision: str | None = "0032_adopt_column_acls"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE POLICY controller_policy_adoption_fact_tenant_isolation
            ON request_engine.controller_policy_adoption_facts
            FOR ALL TO request_engine_app
            USING(organization_id=request_engine.current_organization_id())
            WITH CHECK(organization_id=request_engine.current_organization_id());
    """)


def downgrade() -> None:
    raise RuntimeError("Request Engine schema migrations are forward-only")
