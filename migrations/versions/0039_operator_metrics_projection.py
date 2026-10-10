"""Expose bounded, aggregate operational metrics to a dedicated monitor."""

from alembic import op

revision: str = "0039_operator_metrics_projection"
down_revision: str | None = "0038_shared_http_auth_admission"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )

    # Keep aggregate probes index-backed and limit each sampled set to 1,001 rows.
    for index in (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS scheduled_actions_metrics_pending_due_idx "
        "ON request_engine.scheduled_actions ((GREATEST(execute_at, next_attempt_at))) "
        "WHERE status = 'pending'",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS scheduled_actions_metrics_expired_lease_idx "
        "ON request_engine.scheduled_actions (lease_until) "
        "WHERE status = 'leased'",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS outbox_messages_metrics_oldest_idx "
        "ON request_engine.outbox_messages (created_at) "
        "WHERE status IN ('pending', 'leased')",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS provider_events_metrics_oldest_idx "
        "ON request_engine.provider_events (received_at) "
        "WHERE status IN ('received', 'leased')",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS provider_events_metrics_failure_idx "
        "ON request_engine.provider_events (updated_at) WHERE status = 'dead'",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS communication_deliveries_metrics_failure_idx "
        "ON request_engine.communication_deliveries (updated_at) "
        "WHERE status IN ('failed', 'ambiguous')",
    ):
        with op.get_context().autocommit_block():
            op.execute(index)

    op.execute(
        """
        GRANT USAGE ON SCHEMA request_engine TO request_operator_metrics_definer;
        GRANT SELECT (status, created_at, execute_at, next_attempt_at, lease_until)
            ON request_engine.scheduled_actions TO request_operator_metrics_definer;
        GRANT SELECT (status, created_at) ON request_engine.outbox_messages
            TO request_operator_metrics_definer;
        GRANT SELECT (status, received_at, updated_at)
            ON request_engine.provider_events TO request_operator_metrics_definer;
        GRANT SELECT (status, updated_at)
            ON request_engine.communication_deliveries TO request_operator_metrics_definer;
        CREATE POLICY operator_metrics_read ON request_engine.scheduled_actions
            FOR SELECT TO request_operator_metrics_definer USING (true);
        CREATE POLICY operator_metrics_read ON request_engine.outbox_messages
            FOR SELECT TO request_operator_metrics_definer USING (true);
        CREATE POLICY operator_metrics_read ON request_engine.provider_events
            FOR SELECT TO request_operator_metrics_definer USING (true);
        CREATE POLICY operator_metrics_read ON request_engine.communication_deliveries
            FOR SELECT TO request_operator_metrics_definer USING (true);
        GRANT USAGE ON SCHEMA request_admin TO request_operator_metrics_definer;
        GRANT USAGE ON SCHEMA request_admin TO request_operator_metrics;

        CREATE FUNCTION request_admin.read_operator_metrics()
        RETURNS TABLE(
            scheduled_action_backlog bigint,
            scheduled_action_oldest_age_seconds double precision,
            outbox_backlog bigint,
            outbox_oldest_age_seconds double precision,
            provider_event_backlog bigint,
            provider_event_oldest_age_seconds double precision,
            provider_event_failures_10m bigint,
            communication_failures_10m bigint,
            communication_ambiguous_10m bigint
        )
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, request_engine, request_admin, pg_temp
        SET statement_timeout = '3s'
        AS $$
          SELECT
            LEAST(1001, (SELECT count(*) FROM (
                SELECT 1 FROM request_engine.scheduled_actions
                 WHERE status = 'pending'
                   AND GREATEST(execute_at, next_attempt_at) <= statement_timestamp()
                 LIMIT 1001
            ) pending_bounded) + (SELECT count(*) FROM (
                SELECT 1 FROM request_engine.scheduled_actions
                 WHERE status = 'leased' AND lease_until <= statement_timestamp()
                 LIMIT 1001
            ) leased_bounded))::bigint,
            COALESCE((SELECT EXTRACT(EPOCH FROM (statement_timestamp() - oldest.due_at))
                FROM (SELECT NULLIF(LEAST(
                    COALESCE((SELECT GREATEST(execute_at, next_attempt_at)
                                FROM request_engine.scheduled_actions
                               WHERE status = 'pending'
                                 AND GREATEST(execute_at, next_attempt_at) <= statement_timestamp()
                               ORDER BY GREATEST(execute_at, next_attempt_at) LIMIT 1),
                             'infinity'::timestamptz),
                    COALESCE((SELECT lease_until FROM request_engine.scheduled_actions
                               WHERE status = 'leased'
                                 AND lease_until <= statement_timestamp()
                               ORDER BY lease_until LIMIT 1), 'infinity'::timestamptz)
                ), 'infinity'::timestamptz) AS due_at) oldest), 0)::double precision,
            (SELECT count(*) FROM (
                SELECT created_at FROM request_engine.outbox_messages
                 WHERE status IN ('pending', 'leased') LIMIT 1001
            ) bounded)::bigint,
            COALESCE((SELECT EXTRACT(EPOCH FROM
                (statement_timestamp() - oldest.created_at))
                FROM (SELECT created_at FROM request_engine.outbox_messages
                       WHERE status IN ('pending', 'leased')
                       ORDER BY created_at LIMIT 1) oldest), 0)::double precision,
            (SELECT count(*) FROM (
                SELECT received_at FROM request_engine.provider_events
                 WHERE status IN ('received', 'leased') LIMIT 1001
            ) bounded)::bigint,
            COALESCE((SELECT EXTRACT(EPOCH FROM
                (statement_timestamp() - oldest.received_at))
                FROM (SELECT received_at FROM request_engine.provider_events
                       WHERE status IN ('received', 'leased')
                       ORDER BY received_at LIMIT 1) oldest), 0)::double precision,
            (SELECT count(*) FROM (
                SELECT updated_at FROM request_engine.provider_events
                 WHERE status = 'dead'
                   AND updated_at >= statement_timestamp() - interval '10 minutes'
                 LIMIT 1001
            ) bounded)::bigint,
            (SELECT count(*) FROM (
                SELECT updated_at FROM request_engine.communication_deliveries
                 WHERE status = 'failed'
                   AND updated_at >= statement_timestamp() - interval '10 minutes'
                 LIMIT 1001
            ) bounded)::bigint,
            (SELECT count(*) FROM (
                SELECT updated_at FROM request_engine.communication_deliveries
                 WHERE status = 'ambiguous'
                   AND updated_at >= statement_timestamp() - interval '10 minutes'
                 LIMIT 1001
            ) bounded)::bigint
        $$;
        ALTER FUNCTION request_admin.read_operator_metrics()
            OWNER TO request_operator_metrics_definer;
        REVOKE ALL ON FUNCTION request_admin.read_operator_metrics() FROM PUBLIC;
        REVOKE ALL ON FUNCTION request_admin.read_operator_metrics()
            FROM request_engine_app, request_engine_worker, request_engine_admin;
        GRANT EXECUTE ON FUNCTION request_admin.read_operator_metrics()
            TO request_operator_metrics;
        """
    )


def downgrade() -> None:
    raise RuntimeError("operator metrics projection is roll-forward only")
