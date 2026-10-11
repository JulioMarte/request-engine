"""Enable the private control group to invoke the new administrative command."""

from alembic import op

revision: str = "0016_native_identity_acl"
down_revision: str | None = "0015_native_identity_provision"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "GRANT SELECT(created_at,enrolled_at,consumed_at,revoked_at) "
        "ON request_engine.platform_owner_invitations TO request_platform_control_definer"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION request_platform.provision_native_identity("
        "uuid,uuid,text,uuid,text,text,text) TO request_platform_control"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT(created_at,enrolled_at,consumed_at,revoked_at) "
        "ON request_engine.platform_owner_invitations FROM request_platform_control_definer"
    )
    op.execute(
        "REVOKE EXECUTE ON FUNCTION request_platform.provision_native_identity("
        "uuid,uuid,text,uuid,text,text,text) FROM request_platform_control"
    )
