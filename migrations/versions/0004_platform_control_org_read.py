"""Grant the platform control runtime the organization read projection.

Revision ID: 0004_platform_control_org_read
Revises: 0003_platform_org_directory
Create Date: 2026-09-30
"""

from alembic import op

revision: str = "0004_platform_control_org_read"
down_revision: str | None = "0003_platform_org_directory"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "GRANT EXECUTE ON FUNCTION "
        "request_platform.read_platform_organizations(uuid, uuid, integer) "
        "TO request_platform_control"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "request_platform.read_platform_organizations(uuid, uuid, integer) "
        "FROM request_platform_control"
    )
