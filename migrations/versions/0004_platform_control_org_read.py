"""Keep the organization directory private to explicitly provisioned read logins.

Revision ID: 0004_platform_control_org_read
Revises: 0003_platform_org_directory
Create Date: 2026-09-30

Runtime login grants are deployment concerns because the read pool is a distinct
login, not a database group role.  The baseline function already revokes PUBLIC;
this revision remains as the historical chain point without widening the control
role's command surface.
"""

revision: str = "0004_platform_control_org_read"
down_revision: str | None = "0003_platform_org_directory"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
