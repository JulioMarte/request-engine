"""Revalidate current controller-policy authority before returning receipts."""

from alembic import op

revision: str = "0028_ctrl_policy_replay_auth"
down_revision: str | None = "0027_controller_policy_adoption"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION request_cmd.lock_controller_policy_upgrade_authority()
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, pg_temp AS $$
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            RETURN request_engine.assert_staff_manager('controller_policy_upgrade');
        END;
        $$;
        ALTER FUNCTION request_cmd.lock_controller_policy_upgrade_authority()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.lock_controller_policy_upgrade_authority()
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.lock_controller_policy_upgrade_authority()
            TO request_engine_app;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION request_cmd.lock_controller_policy_upgrade_authority()")
