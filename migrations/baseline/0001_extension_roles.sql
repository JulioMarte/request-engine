-- Audited Request Engine extension-role ensure blocks.
-- Extracted verbatim from the collapsed 0013/0020/0024/0037/0038/0039 revisions.
-- Each block creates its closed-namespace NOLOGIN group only when missing and
-- fails closed when an existing cluster-global role is unsafe. Credentials are
-- intentionally forbidden from this payload.

SELECT pg_advisory_xact_lock(731527893422021);

-- request_retention_recorder (historical 0013 creation under the 0020 canonical name; its complete 0020 inventory audit runs after the schema payload)
DO $$ BEGIN
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='request_engine_retention_recorder') THEN
        RAISE EXCEPTION 'legacy retention recorder group exists; reset clusters that predate the 0047 rebaseline'
            USING ERRCODE='55000';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='request_retention_recorder') THEN
        CREATE ROLE request_retention_recorder NOLOGIN NOSUPERUSER
            NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;

-- request_proof_cleanup_worker (historical 0024)
DO $$ DECLARE worker record; BEGIN
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname LIKE 'request_proof_cleanup_%'
        AND rolname<>'request_proof_cleanup_worker') THEN
        RAISE EXCEPTION 'cleanup namespace contains unaudited roles'
            USING ERRCODE='42501';
    END IF;
    IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='request_proof_cleanup_worker') THEN
        CREATE ROLE request_proof_cleanup_worker NOLOGIN NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    SELECT * INTO STRICT worker FROM pg_roles WHERE rolname='request_proof_cleanup_worker';
    IF worker.rolcanlogin OR worker.rolsuper OR worker.rolcreatedb OR worker.rolcreaterole
        OR worker.rolreplication OR worker.rolbypassrls OR worker.rolconfig IS NOT NULL
        OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=worker.oid)
        OR EXISTS(SELECT 1 FROM pg_db_role_setting WHERE setrole=worker.oid)
        OR EXISTS(SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass
            AND refobjid=worker.oid AND (deptype='o' OR (deptype='a'
                AND (dbid=0 OR dbid=(SELECT oid FROM pg_database
                    WHERE datname=current_database()))))) THEN
        RAISE EXCEPTION 'retention worker group is not isolated' USING ERRCODE='42501';
    END IF;
    IF EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
        WHERE m.roleid=worker.oid AND (m.admin_option OR NOT r.rolcanlogin OR r.rolsuper
            OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
            OR r.rolconfig IS NOT NULL
            OR EXISTS(SELECT 1 FROM pg_auth_members extra WHERE extra.member=r.oid
                AND (extra.roleid<>worker.oid OR extra.admin_option)))) THEN
        RAISE EXCEPTION 'retention worker membership is not isolated' USING ERRCODE='42501';
    END IF;
END $$;

-- request_webauthn_retention / request_webauthn_retention_definer (historical 0037)
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
    -- The dependent-foreign-key check needs request_engine.webauthn_challenges;
    -- that historical 0037 check runs after the schema payload.
END $$;

-- request_http_admission_definer (historical 0038)
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

-- request_operator_metrics / request_operator_metrics_definer (historical 0039)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'request_operator_metrics_definer'
    ) THEN
        CREATE ROLE request_operator_metrics_definer NOLOGIN NOINHERIT NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'request_operator_metrics'
    ) THEN
        CREATE ROLE request_operator_metrics NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles
         WHERE rolname IN ('request_operator_metrics_definer', 'request_operator_metrics')
           AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
                OR rolreplication OR rolbypassrls OR rolinherit)
    ) THEN
        RAISE EXCEPTION 'operator metrics roles have unexpected attributes'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_auth_members membership
        JOIN pg_roles granted_role ON granted_role.oid = membership.roleid
        JOIN pg_roles member ON member.oid = membership.member
        WHERE granted_role.rolname = 'request_operator_metrics_definer'
           OR member.rolname = 'request_operator_metrics_definer'
           OR member.rolname = 'request_operator_metrics'
    ) THEN
        RAISE EXCEPTION 'operator metrics roles have unexpected memberships'
            USING ERRCODE = '55000';
    END IF;
    IF EXISTS (
        SELECT 1 FROM (
            SELECT n.nspname AS object_name, role.rolname AS grantee
              FROM pg_namespace n CROSS JOIN LATERAL aclexplode(
                  COALESCE(n.nspacl, acldefault('n', n.nspowner))
              ) acl JOIN pg_roles role ON role.oid = acl.grantee
            UNION ALL
            SELECT n.nspname || '.' || relation.relname, role.rolname
              FROM pg_class relation JOIN pg_namespace n ON n.oid = relation.relnamespace
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(relation.relacl, acldefault('r', relation.relowner))
              ) acl JOIN pg_roles role ON role.oid = acl.grantee
            UNION ALL
            SELECT n.nspname || '.' || routine.proname, role.rolname
              FROM pg_proc routine JOIN pg_namespace n ON n.oid = routine.pronamespace
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(routine.proacl, acldefault('f', routine.proowner))
              ) acl JOIN pg_roles role ON role.oid = acl.grantee
            UNION ALL
            SELECT n.nspname || '.' || type.typname, role.rolname
              FROM pg_type type JOIN pg_namespace n ON n.oid = type.typnamespace
              CROSS JOIN LATERAL aclexplode(
                  COALESCE(type.typacl, acldefault('T', type.typowner))
              ) acl JOIN pg_roles role ON role.oid = acl.grantee
            UNION ALL
            SELECT n.nspname || '.' || relation.relname || '.' || attribute.attname,
                   role.rolname
              FROM pg_attribute attribute
              JOIN pg_class relation ON relation.oid = attribute.attrelid
              JOIN pg_namespace n ON n.oid = relation.relnamespace
              CROSS JOIN LATERAL aclexplode(attribute.attacl) acl
              JOIN pg_roles role ON role.oid IN (acl.grantee, acl.grantor)
             WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
        ) existing_acl
        WHERE grantee IN (
            'request_operator_metrics_definer', 'request_operator_metrics'
        )
    ) OR EXISTS (
        SELECT 1 FROM pg_database database CROSS JOIN LATERAL aclexplode(
            COALESCE(database.datacl, acldefault('d', database.datdba))
        ) acl JOIN pg_roles role ON role.oid IN (acl.grantee, acl.grantor)
        WHERE role.rolname IN (
            'request_operator_metrics_definer', 'request_operator_metrics'
        ) AND database.datname = current_database()
    ) OR EXISTS (
        SELECT 1 FROM pg_default_acl defaults CROSS JOIN LATERAL aclexplode(
            defaults.defaclacl
        ) acl JOIN pg_roles role ON role.oid IN (acl.grantee, acl.grantor)
        WHERE role.rolname IN (
            'request_operator_metrics_definer', 'request_operator_metrics'
        )
    ) OR EXISTS (
        SELECT 1
          FROM pg_shdepend dependency
          JOIN pg_roles role ON dependency.refclassid = 'pg_authid'::regclass
                            AND dependency.refobjid = role.oid
         WHERE role.rolname IN (
                   'request_operator_metrics_definer', 'request_operator_metrics'
               )
           AND dependency.deptype IN ('o', 'a')
           AND dependency.dbid IN (
               0, (SELECT oid FROM pg_database WHERE datname = current_database())
           )
    ) THEN
        RAISE EXCEPTION 'operator metrics roles have pre-existing object grants'
            USING ERRCODE = '55000';
    END IF;
END $$;
