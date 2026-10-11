"""Separate the audited retention extension role from accepted baseline roles."""

from alembic import op

revision: str = "0020_retention_recorder_role"
down_revision: str | None = "0019_native_provision_reachable"
branch_labels: str | None = None
depends_on: str | None = None

ROLE_INVENTORY_SQL = """
DO $audit$
DECLARE recorder record; expected_function oid;
BEGIN
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname LIKE 'request_retention_%'
        AND rolname<>'request_retention_recorder') THEN
        RAISE EXCEPTION 'Retention recorder namespace contains an unaudited group';
    END IF;
    expected_function := 'request_cmd.record_temporary_proof_retention('
        'uuid,text,text,bigint,timestamptz,timestamptz,timestamptz)'::regprocedure;
    FOR recorder IN SELECT * FROM pg_authid WHERE rolname IN (
        'request_retention_recorder','request_engine_retention_recorder') LOOP
        IF recorder.rolcanlogin OR recorder.rolsuper OR recorder.rolbypassrls
           OR recorder.rolcreatedb OR recorder.rolcreaterole OR recorder.rolreplication
           OR NOT recorder.rolinherit OR recorder.rolconnlimit<>-1
           OR recorder.rolvaliduntil IS NOT NULL OR recorder.rolpassword IS NOT NULL THEN
            RAISE EXCEPTION 'Retention recorder group attributes are unsafe';
        END IF;
        IF EXISTS(SELECT 1 FROM pg_db_role_setting WHERE setrole=recorder.oid)
           OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=recorder.oid)
           OR EXISTS(SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass
                AND refobjid=recorder.oid AND deptype='o') THEN
            RAISE EXCEPTION 'Retention recorder group settings/authority/ownership are unsafe';
        END IF;
        IF EXISTS(
            SELECT 1 FROM pg_auth_members m JOIN pg_authid member ON member.oid=m.member
            WHERE m.roleid=recorder.oid AND (m.admin_option OR NOT member.rolcanlogin
                OR member.rolsuper OR member.rolbypassrls OR member.rolcreatedb
                OR member.rolcreaterole OR member.rolreplication
                OR EXISTS(SELECT 1 FROM pg_auth_members other
                    WHERE other.member=member.oid AND other.roleid<>recorder.oid))
        ) THEN
            RAISE EXCEPTION 'Retention recorder requires isolated nonprivileged LOGIN members';
        END IF;
        IF EXISTS(
            SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a
            WHERE a.grantee=recorder.oid AND (n.nspname<>'request_cmd'
                OR a.privilege_type<>'USAGE' OR a.is_grantable)
            UNION ALL
            SELECT 1 FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
            WHERE a.grantee=recorder.oid AND (p.oid<>expected_function
                OR a.privilege_type<>'EXECUTE' OR a.is_grantable)
            UNION ALL
            SELECT 1 FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) a
            WHERE a.grantee=recorder.oid
            UNION ALL
            SELECT 1 FROM pg_attribute c CROSS JOIN LATERAL aclexplode(c.attacl) a
            WHERE a.grantee=recorder.oid
            UNION ALL
            SELECT 1 FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a
            WHERE a.grantee=recorder.oid
            UNION ALL
            SELECT 1 FROM pg_type t CROSS JOIN LATERAL aclexplode(t.typacl) a
            WHERE a.grantee=recorder.oid
            UNION ALL
            SELECT 1 FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a
            WHERE a.grantee=recorder.oid
        ) THEN
            RAISE EXCEPTION 'Retention recorder grants exceed the append-only contract';
        END IF;
    END LOOP;
END $audit$;
"""


def upgrade() -> None:
    op.execute("SELECT pg_advisory_xact_lock(731527893422021)")
    op.execute(ROLE_INVENTORY_SQL)
    op.execute("""
    DO $migration$
    DECLARE legacy oid; canonical oid; database_id oid;
    BEGIN
        SELECT oid INTO legacy FROM pg_roles WHERE rolname='request_engine_retention_recorder';
        SELECT oid INTO canonical FROM pg_roles WHERE rolname='request_retention_recorder';
        SELECT oid INTO database_id FROM pg_database WHERE datname=current_database();
        IF canonical IS NULL THEN
            IF legacy IS NULL THEN RAISE EXCEPTION 'Retention recorder group is missing'; END IF;
            -- OID, member credentials and all database-scoped grants stay intact.
            ALTER ROLE request_engine_retention_recorder RENAME TO request_retention_recorder;
        ELSIF legacy IS NOT NULL THEN
            IF EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid=legacy OR member=legacy)
               OR EXISTS(SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass
                    AND refobjid=legacy AND (dbid<>database_id OR deptype<>'a')) THEN
                RAISE EXCEPTION 'Legacy recorder has members or external dependencies; '
                    'coordinate the cluster rollout before retrying';
            END IF;
            -- A second fresh database's 0013 recreated only these two local ACLs.
            GRANT USAGE ON SCHEMA request_cmd TO request_retention_recorder;
            GRANT EXECUTE ON FUNCTION request_cmd.record_temporary_proof_retention(
                uuid,text,text,bigint,timestamptz,timestamptz,timestamptz)
                TO request_retention_recorder;
            REVOKE USAGE ON SCHEMA request_cmd FROM request_engine_retention_recorder;
            REVOKE EXECUTE ON FUNCTION request_cmd.record_temporary_proof_retention(
                uuid,text,text,bigint,timestamptz,timestamptz,timestamptz)
                FROM request_engine_retention_recorder;
            -- No CASCADE: unanticipated dependencies abort/roll back the migration.
            DROP ROLE request_engine_retention_recorder;
        END IF;
    END $migration$;
    """)
    op.execute(ROLE_INVENTORY_SQL)


def downgrade() -> None:
    raise NotImplementedError("Cluster-global role evolution requires coordinated roll-forward")
