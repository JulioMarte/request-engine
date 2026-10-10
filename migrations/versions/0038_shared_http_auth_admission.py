"""Add bounded PostgreSQL-backed shared HTTP authentication admission."""

from alembic import op

revision: str = "0038_shared_http_auth_admission"
down_revision: str | None = "0037_webauthn_retention"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.http_auth_admission_state (
            singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
            configured_limit integer CHECK (configured_limit BETWEEN 1 AND 10000),
            attempts timestamptz[] NOT NULL DEFAULT '{}'
                CHECK (cardinality(attempts) <= 10000)
        );
        INSERT INTO request_engine.http_auth_admission_state(singleton) VALUES (true);
        REVOKE ALL ON request_engine.http_auth_admission_state FROM PUBLIC;

        DO $$
        DECLARE
            v_role oid;
            v_database oid;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'request_http_admission_definer'
            ) THEN
                CREATE ROLE request_http_admission_definer NOLOGIN NOSUPERUSER NOCREATEDB
                    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_roles
                 WHERE rolname = 'request_http_admission_definer'
                   AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                        OR rolreplication OR rolbypassrls)
            ) THEN
                RAISE EXCEPTION 'HTTP admission roles have unexpected elevated attributes'
                    USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                SELECT 1 FROM pg_auth_members membership
                JOIN pg_roles role ON role.oid = membership.roleid
                WHERE role.rolname = 'request_http_admission_definer'
            ) OR EXISTS (
                SELECT 1 FROM pg_auth_members membership
                JOIN pg_roles member ON member.oid = membership.member
                WHERE member.rolname = 'request_http_admission_definer'
            ) THEN
                RAISE EXCEPTION 'HTTP admission definer has unexpected role memberships'
                    USING ERRCODE = '55000';
            END IF;
            SELECT oid INTO STRICT v_role
              FROM pg_roles WHERE rolname = 'request_http_admission_definer';
            SELECT oid INTO STRICT v_database
              FROM pg_database WHERE datname = current_database();
            IF EXISTS (
                SELECT 1 FROM pg_shdepend dependency
                 WHERE dependency.refclassid = 'pg_authid'::regclass
                   AND dependency.refobjid = v_role
                   AND dependency.dbid = v_database
                   AND dependency.deptype = 'o'
            ) OR EXISTS (
                SELECT 1 FROM pg_database WHERE oid = v_database AND datdba = v_role
            ) THEN
                RAISE EXCEPTION 'HTTP admission definer owns an unexpected database object'
                    USING ERRCODE = '55000';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM (
                    SELECT nspacl AS acl FROM pg_namespace WHERE nspacl IS NOT NULL
                    UNION ALL SELECT relacl FROM pg_class WHERE relacl IS NOT NULL
                    UNION ALL SELECT attacl FROM pg_attribute WHERE attacl IS NOT NULL
                    UNION ALL SELECT proacl FROM pg_proc WHERE proacl IS NOT NULL
                    UNION ALL SELECT typacl FROM pg_type WHERE typacl IS NOT NULL
                    UNION ALL SELECT lanacl FROM pg_language WHERE lanacl IS NOT NULL
                    UNION ALL SELECT fdwacl FROM pg_foreign_data_wrapper WHERE fdwacl IS NOT NULL
                    UNION ALL SELECT srvacl FROM pg_foreign_server WHERE srvacl IS NOT NULL
                    UNION ALL SELECT spcacl FROM pg_tablespace WHERE spcacl IS NOT NULL
                    UNION ALL SELECT lomacl FROM pg_largeobject_metadata WHERE lomacl IS NOT NULL
                    UNION ALL
                    SELECT datacl FROM pg_database
                     WHERE oid = v_database AND datacl IS NOT NULL
                    UNION ALL SELECT defaclacl FROM pg_default_acl WHERE defaclacl IS NOT NULL
                  ) explicit_acls
                  CROSS JOIN LATERAL aclexplode(explicit_acls.acl) grant_entry
                 WHERE grant_entry.grantee = v_role OR grant_entry.grantor = v_role
            ) THEN
                RAISE EXCEPTION 'HTTP admission definer has unexpected object privileges'
                    USING ERRCODE = '55000';
            END IF;
        END $$;
        GRANT USAGE ON SCHEMA request_engine TO request_http_admission_definer;
        GRANT SELECT (singleton, configured_limit, attempts),
              UPDATE (configured_limit, attempts)
            ON request_engine.http_auth_admission_state TO request_http_admission_definer;

        CREATE FUNCTION request_auth.admit_http_authentication(p_limit integer)
        RETURNS TABLE(allowed boolean, retry_after_seconds integer)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, pg_temp
        AS $$
        DECLARE
            v_now timestamptz;
            v_attempts timestamptz[];
            v_configured_limit integer;
            v_oldest timestamptz;
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 10000 THEN
                RAISE EXCEPTION 'authentication limit must be from 1 through 10000'
                    USING ERRCODE = '22023';
            END IF;
            SELECT attempts, configured_limit INTO v_attempts, v_configured_limit
              FROM request_engine.http_auth_admission_state
             WHERE singleton FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'HTTP admission state row is missing' USING ERRCODE = '55000';
            END IF;
            IF v_configured_limit IS NULL THEN
                UPDATE request_engine.http_auth_admission_state
                   SET configured_limit = p_limit
                 WHERE singleton;
            ELSIF v_configured_limit <> p_limit THEN
                RAISE EXCEPTION 'HTTP admission limit differs from the shared configured limit'
                    USING ERRCODE = '55000';
            END IF;
            v_now := clock_timestamp();
            SELECT COALESCE(array_agg(attempt ORDER BY attempt), '{}')
              INTO v_attempts
              FROM unnest(v_attempts) AS expanded(attempt)
             WHERE attempt > v_now - interval '60 seconds';
            IF cardinality(v_attempts) < p_limit THEN
                UPDATE request_engine.http_auth_admission_state
                   SET attempts = v_attempts || v_now
                 WHERE singleton;
                RETURN QUERY SELECT true, 0;
                RETURN;
            END IF;
            v_oldest := v_attempts[1];
            RETURN QUERY SELECT false,
                GREATEST(
                    1,
                    CEIL(EXTRACT(EPOCH FROM (
                        v_oldest + interval '60 seconds' - v_now
                    )))::integer
                );
        END;
        $$;
        ALTER FUNCTION request_auth.admit_http_authentication(integer)
            OWNER TO request_http_admission_definer;
        REVOKE ALL ON FUNCTION request_auth.admit_http_authentication(integer) FROM PUBLIC;
        REVOKE ALL ON FUNCTION request_auth.admit_http_authentication(integer)
            FROM request_engine_app, request_engine_worker;
        GRANT EXECUTE ON FUNCTION request_auth.admit_http_authentication(integer)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("shared authentication admission is roll-forward only")
