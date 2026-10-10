"""Tenant-local staff display labels with independent revision and narrow writes."""

from alembic import op

revision: str = "0011_staff_member_profiles"
down_revision: str | None = "0010_invitation_topology_gate"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE request_engine.staff_memberships
            ADD CONSTRAINT staff_memberships_org_id_unique UNIQUE(organization_id,id);
        CREATE TABLE request_engine.staff_member_profiles (
            organization_id uuid NOT NULL,
            membership_id uuid NOT NULL,
            display_name text,
            revision bigint NOT NULL CHECK(revision > 0),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_by_principal_id uuid NOT NULL,
            provenance_reference text NOT NULL
                CHECK(length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            PRIMARY KEY(organization_id,membership_id),
            FOREIGN KEY(organization_id,membership_id)
                REFERENCES request_engine.staff_memberships(organization_id,id),
            FOREIGN KEY(organization_id,updated_by_principal_id)
                REFERENCES request_engine.principals(organization_id,id),
            CHECK(display_name IS NULL OR (display_name = btrim(display_name)
                AND length(display_name) BETWEEN 1 AND 200
                AND display_name !~ '[[:cntrl:]]'))
        );
        ALTER TABLE request_engine.staff_member_profiles OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.staff_member_profiles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.staff_member_profiles FORCE ROW LEVEL SECURITY;
        CREATE POLICY staff_profile_tenant ON request_engine.staff_member_profiles
            USING(organization_id=request_engine.current_organization_id())
            WITH CHECK(organization_id=request_engine.current_organization_id());
        REVOKE ALL ON request_engine.staff_member_profiles FROM PUBLIC,request_engine_app;
        GRANT SELECT(organization_id,membership_id,display_name,revision)
            ON request_engine.staff_member_profiles TO request_engine_app;

        CREATE FUNCTION request_cmd.lock_staff_member_profile(p_membership uuid)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_status text;
        BEGIN
            PERFORM request_engine.lock_tenant_staff_root();
            PERFORM request_engine.assert_staff_manager('staff.manage_membership');
            SELECT status INTO v_status FROM request_engine.staff_memberships
                WHERE organization_id=request_engine.current_organization_id()
                  AND id=p_membership FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Staff member not found'
                USING ERRCODE='P0002'; END IF;
            IF v_status='revoked' THEN RAISE EXCEPTION 'Revoked staff profile is immutable'
                USING ERRCODE='55000'; END IF;
        END $$;
        ALTER FUNCTION request_cmd.lock_staff_member_profile(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.lock_staff_member_profile(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.lock_staff_member_profile(uuid) TO request_engine_app;

        CREATE FUNCTION request_cmd.write_staff_member_profile(
            p_membership uuid,p_expected bigint,p_name text,p_provenance text)
        RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO pg_catalog,request_engine,pg_temp AS $$
        DECLARE v_revision bigint; v_org uuid:=request_engine.current_organization_id();
        BEGIN
            PERFORM request_cmd.lock_staff_member_profile(p_membership);
            IF p_expected IS NULL OR p_expected<0 OR p_provenance IS NULL
                OR length(btrim(p_provenance)) NOT BETWEEN 1 AND 500
                OR (p_name IS NOT NULL AND (p_name<>btrim(p_name)
                    OR length(p_name) NOT BETWEEN 1 AND 200 OR p_name ~ '[[:cntrl:]]')) THEN
                RAISE EXCEPTION 'Invalid profile input' USING ERRCODE='22023'; END IF;
            SELECT revision INTO v_revision FROM request_engine.staff_member_profiles
                WHERE organization_id=v_org AND membership_id=p_membership FOR UPDATE;
            IF COALESCE(v_revision,0)<>p_expected THEN
                RAISE EXCEPTION 'Staff profile revision is stale' USING ERRCODE='40001'; END IF;
            INSERT INTO request_engine.staff_member_profiles(
                organization_id,membership_id,display_name,revision,updated_by_principal_id,provenance_reference)
                VALUES(v_org,p_membership,p_name,p_expected+1,
                    current_setting('request_engine.authenticated_principal_id')::uuid,btrim(p_provenance))
                ON CONFLICT(organization_id,membership_id) DO UPDATE SET
                    display_name=EXCLUDED.display_name,revision=EXCLUDED.revision,
                    updated_at=clock_timestamp(),updated_by_principal_id=EXCLUDED.updated_by_principal_id,
                    provenance_reference=EXCLUDED.provenance_reference;
            RETURN p_expected+1;
        END $$;
        ALTER FUNCTION request_cmd.write_staff_member_profile(uuid,bigint,text,text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_cmd.write_staff_member_profile(uuid,bigint,text,text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_cmd.write_staff_member_profile(uuid,bigint,text,text)
            TO request_engine_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION request_cmd.write_staff_member_profile(uuid,bigint,text,text);
        DROP FUNCTION request_cmd.lock_staff_member_profile(uuid);
        DROP TABLE request_engine.staff_member_profiles;
        ALTER TABLE request_engine.staff_memberships
            DROP CONSTRAINT staff_memberships_org_id_unique;
    """)
