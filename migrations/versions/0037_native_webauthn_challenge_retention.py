"""Add least-privilege, explicitly invoked WebAuthn challenge retention."""

from alembic import op

revision: str = "0037_webauthn_retention"
down_revision: str | None = "0036_webauthn_deadline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'request_webauthn_retention_definer'
            ) THEN
                CREATE ROLE request_webauthn_retention_definer NOLOGIN NOSUPERUSER
                    NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_roles WHERE rolname = 'request_webauthn_retention'
            ) THEN
                CREATE ROLE request_webauthn_retention NOLOGIN NOSUPERUSER
                    NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_roles
                 WHERE rolname IN (
                    'request_webauthn_retention_definer',
                    'request_webauthn_retention'
                 )
                   AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                        OR rolreplication OR rolbypassrls)
            ) THEN
                RAISE EXCEPTION 'WebAuthn retention roles have unexpected elevated attributes'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM pg_auth_members membership
                  JOIN pg_roles role ON role.oid = membership.roleid
                 WHERE role.rolname = 'request_webauthn_retention_definer'
            ) OR EXISTS (
                SELECT 1
                  FROM pg_auth_members membership
                  JOIN pg_roles member ON member.oid = membership.member
                 WHERE member.rolname = 'request_webauthn_retention_definer'
            ) THEN
                RAISE EXCEPTION 'WebAuthn retention definer role has unexpected memberships'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM pg_auth_members membership
                  JOIN pg_roles member ON member.oid = membership.member
                 WHERE member.rolname = 'request_webauthn_retention'
            ) THEN
                RAISE EXCEPTION 'WebAuthn retention caller role inherits an unexpected parent role'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM pg_auth_members membership
                  JOIN pg_roles member ON member.oid = membership.member
                  JOIN pg_roles granted ON granted.oid = membership.roleid
                 WHERE granted.rolname = 'request_webauthn_retention'
                   AND (NOT member.rolcanlogin OR member.rolsuper OR member.rolcreatedb
                        OR member.rolcreaterole OR member.rolreplication OR member.rolbypassrls
                        OR membership.admin_option OR membership.inherit_option
                        OR NOT membership.set_option)
            ) THEN
                RAISE EXCEPTION 'WebAuthn retention caller has an unsafe login membership'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM (
                    SELECT 'schema'::text AS kind, n.nspname AS object_name,
                           role.rolname AS grantee, acl.privilege_type, acl.is_grantable
                      FROM pg_namespace n
                      CROSS JOIN LATERAL aclexplode(
                          COALESCE(n.nspacl, acldefault('n', n.nspowner))
                      ) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE role.rolname IN (
                         'request_webauthn_retention',
                         'request_webauthn_retention_definer'
                     )
                    UNION ALL
                    SELECT 'relation', n.nspname || '.' || relation.relname,
                           role.rolname, acl.privilege_type, acl.is_grantable
                      FROM pg_class relation
                      JOIN pg_namespace n ON n.oid = relation.relnamespace
                      CROSS JOIN LATERAL aclexplode(
                          COALESCE(relation.relacl, acldefault('r', relation.relowner))
                      ) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE role.rolname IN (
                         'request_webauthn_retention',
                         'request_webauthn_retention_definer'
                     )
                    UNION ALL
                    SELECT 'column', n.nspname || '.' || relation.relname || '.'
                           || attribute.attname,
                           role.rolname, acl.privilege_type, acl.is_grantable
                      FROM pg_attribute attribute
                      JOIN pg_class relation ON relation.oid = attribute.attrelid
                      JOIN pg_namespace n ON n.oid = relation.relnamespace
                      CROSS JOIN LATERAL aclexplode(attribute.attacl) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
                       AND role.rolname IN (
                           'request_webauthn_retention',
                           'request_webauthn_retention_definer'
                       )
                    UNION ALL
                    SELECT 'function', n.nspname || '.' || routine.proname,
                           role.rolname, acl.privilege_type, acl.is_grantable
                      FROM pg_proc routine
                      JOIN pg_namespace n ON n.oid = routine.pronamespace
                      CROSS JOIN LATERAL aclexplode(
                          COALESCE(routine.proacl, acldefault('f', routine.proowner))
                      ) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE role.rolname IN (
                         'request_webauthn_retention',
                         'request_webauthn_retention_definer'
                     )
                    UNION ALL
                    SELECT 'type', n.nspname || '.' || type.typname,
                           role.rolname, acl.privilege_type, acl.is_grantable
                      FROM pg_type type
                      JOIN pg_namespace n ON n.oid = type.typnamespace
                      CROSS JOIN LATERAL aclexplode(
                          COALESCE(type.typacl, acldefault('T', type.typowner))
                      ) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE role.rolname IN (
                         'request_webauthn_retention',
                         'request_webauthn_retention_definer'
                     )
                    UNION ALL
                    SELECT 'database', database.datname,
                           role.rolname, acl.privilege_type, acl.is_grantable
                      FROM pg_database database
                      CROSS JOIN LATERAL aclexplode(
                          COALESCE(database.datacl, acldefault('d', database.datdba))
                      ) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE role.rolname IN (
                         'request_webauthn_retention',
                         'request_webauthn_retention_definer'
                     )
                    UNION ALL
                    SELECT 'default', defaults.defaclobjtype::text,
                           role.rolname, acl.privilege_type, acl.is_grantable
                      FROM pg_default_acl defaults
                      CROSS JOIN LATERAL aclexplode(defaults.defaclacl) acl
                      JOIN pg_roles role ON role.oid = acl.grantee
                     WHERE role.rolname IN (
                         'request_webauthn_retention',
                         'request_webauthn_retention_definer'
                     )
                  ) AS existing_grants
                 WHERE NOT (
                    (grantee = 'request_webauthn_retention'
                     AND kind = 'schema' AND object_name = 'request_auth'
                     AND privilege_type = 'USAGE' AND NOT is_grantable)
                    OR
                    (grantee = 'request_webauthn_retention_definer'
                     AND kind = 'schema' AND object_name = 'request_engine'
                     AND privilege_type = 'USAGE' AND NOT is_grantable)
                    OR
                    (grantee = 'request_webauthn_retention_definer'
                     AND kind = 'relation'
                     AND object_name = 'request_engine.webauthn_challenges'
                     AND privilege_type = 'DELETE' AND NOT is_grantable)
                    OR
                    (grantee = 'request_webauthn_retention_definer'
                     AND kind = 'column'
                     AND object_name = 'request_engine.webauthn_challenges.id'
                     AND privilege_type IN ('SELECT', 'UPDATE') AND NOT is_grantable)
                    OR
                    (grantee = 'request_webauthn_retention_definer'
                     AND kind = 'column'
                     AND object_name IN (
                         'request_engine.webauthn_challenges.status',
                         'request_engine.webauthn_challenges.expires_at',
                         'request_engine.webauthn_challenges.consumed_at'
                     )
                     AND privilege_type = 'SELECT' AND NOT is_grantable)
                 )
            ) THEN
                RAISE EXCEPTION 'WebAuthn retention roles have unexpected direct ACLs'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE contype = 'f'
                   AND confrelid = 'request_engine.webauthn_challenges'::regclass
            ) THEN
                RAISE EXCEPTION
                    'WebAuthn challenge retention requires disposition of dependent foreign keys'
                    USING ERRCODE = '55000';
            END IF;
        END $$;

        GRANT USAGE ON SCHEMA request_engine TO request_webauthn_retention_definer;
        GRANT SELECT (id, status, expires_at, consumed_at), UPDATE (id), DELETE
            ON request_engine.webauthn_challenges TO request_webauthn_retention_definer;
        GRANT USAGE ON SCHEMA request_auth TO request_webauthn_retention;
        CREATE INDEX webauthn_challenges_retention_scan_idx
            ON request_engine.webauthn_challenges(expires_at, id)
            INCLUDE (status, consumed_at);

        CREATE FUNCTION request_auth.delete_retained_webauthn_challenges(
            p_retention_seconds integer,
            p_batch_size integer
        ) RETURNS integer
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, pg_temp
        AS $$
        DECLARE
            v_cutoff timestamptz;
            v_deleted integer;
        BEGIN
            IF p_retention_seconds IS NULL
                OR p_retention_seconds < 86400
                OR p_retention_seconds > 7776000 THEN
                RAISE EXCEPTION 'retention must be between 86400 and 7776000 seconds'
                    USING ERRCODE = '22023';
            END IF;
            IF p_batch_size IS NULL OR p_batch_size < 1 OR p_batch_size > 1000 THEN
                RAISE EXCEPTION 'batch size must be between 1 and 1000'
                    USING ERRCODE = '22023';
            END IF;
            v_cutoff := clock_timestamp() - make_interval(secs => p_retention_seconds);

            DELETE FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.id IN (
                SELECT candidate.id
                  FROM request_engine.webauthn_challenges AS candidate
                 WHERE candidate.expires_at <= v_cutoff
                   AND candidate.status IN ('pending', 'expired', 'consumed')
                   AND (candidate.status <> 'consumed' OR candidate.consumed_at <= v_cutoff)
                 ORDER BY candidate.expires_at, candidate.id
                 FOR UPDATE SKIP LOCKED
                 LIMIT p_batch_size
             );
            GET DIAGNOSTICS v_deleted = ROW_COUNT;
            RETURN v_deleted;
        END;
        $$;
        ALTER FUNCTION request_auth.delete_retained_webauthn_challenges(integer, integer)
            OWNER TO request_webauthn_retention_definer;
        REVOKE ALL ON FUNCTION
            request_auth.delete_retained_webauthn_challenges(integer, integer)
            FROM PUBLIC, request_engine_app, request_engine_worker;
        GRANT EXECUTE ON FUNCTION
            request_auth.delete_retained_webauthn_challenges(integer, integer)
            TO request_webauthn_retention;
        """
    )


def downgrade() -> None:
    raise RuntimeError("WebAuthn challenge retention is roll-forward only")
