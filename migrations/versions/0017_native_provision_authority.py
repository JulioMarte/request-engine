"""Correct the provisioning primitive's private platform RLS execution owner."""

from alembic import op

revision: str = "0017_native_provision_authority"
down_revision: str | None = "0016_native_identity_acl"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        GRANT SELECT,INSERT ON request_engine.native_identity_provision_receipts
            TO request_platform_control_definer;
        CREATE POLICY native_identity_provision_receipts_control
            ON request_engine.native_identity_provision_receipts
            TO request_platform_control_definer USING(true) WITH CHECK(true);
        GRANT EXECUTE ON FUNCTION request_auth.create_native_identity(uuid,uuid,text,uuid,text)
            TO request_platform_control_definer;
        ALTER FUNCTION request_platform.provision_native_identity(
            uuid,uuid,text,uuid,text,text,text)
            OWNER TO request_platform_control_definer;
    """)


def downgrade() -> None:
    op.execute("""
        ALTER FUNCTION request_platform.provision_native_identity(
            uuid,uuid,text,uuid,text,text,text)
            OWNER TO request_engine_schema_owner;
        REVOKE EXECUTE ON FUNCTION request_auth.create_native_identity(uuid,uuid,text,uuid,text)
            FROM request_platform_control_definer;
        DROP POLICY native_identity_provision_receipts_control
            ON request_engine.native_identity_provision_receipts;
        REVOKE SELECT,INSERT ON request_engine.native_identity_provision_receipts
            FROM request_platform_control_definer;
    """)
