"""Revalidate current staff authority before returning completed command receipts."""

from alembic import op

revision: str = "0012_staff_replay_authority"
down_revision: str | None = "0011_staff_member_profiles"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION request_cmd.lock_staff_command_authority(p_capability text)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, pg_temp AS $$
        BEGIN
            IF p_capability IS NULL OR p_capability NOT IN
                ('staff.invite','staff.manage_authority','staff.manage_membership') THEN
                RAISE EXCEPTION 'unsupported staff command capability' USING ERRCODE='22023';
            END IF;
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            RETURN request_engine.assert_staff_manager(p_capability);
        END;
        $$;
        ALTER FUNCTION request_cmd.lock_staff_command_authority(text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.lock_staff_command_authority(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.lock_staff_command_authority(text)
            TO request_engine_app;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION request_cmd.lock_staff_command_authority(text)")
