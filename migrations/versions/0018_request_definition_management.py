"""Revisioned tenant RequestDefinition administration without rewriting versions."""

from alembic import op

revision: str = "0018_request_definition_admin"
down_revision: str | None = "0017_native_provision_authority"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE request_engine.request_definitions
            ADD COLUMN revision bigint NOT NULL DEFAULT 1 CHECK(revision > 0);
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE request_engine.request_definitions DROP COLUMN revision")
