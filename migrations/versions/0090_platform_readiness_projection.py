"""Expose an honest read-only P7 platform readiness projection.

Revision ID: 0090_platform_readiness
Revises: 0089_control_runtime_config

The projection reports only durable facts PostgreSQL can prove today. Operational
evidence that is not yet persisted (backup acceptance, restore drills and clone
fencing) remains explicitly unknown at the HTTP/application layer rather than
being guessed from deployment environment variables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0090_platform_readiness"
down_revision: str | Sequence[str] | None = "0089_control_runtime_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READ_DEFINER = "request_platform_definer"
_ACTOR_HELPER = "request_platform.assert_platform_configuration_actor(text)"
_SIGNATURE = "request_platform.read_platform_readiness()"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        f"""
        GRANT SELECT (
            id,
            configuration_kind,
            provider_kind,
            revision,
            secret_binding_id,
            state,
            validated_at
        )
        ON request_engine.platform_configuration_revisions
        TO {_READ_DEFINER};

        GRANT SELECT (
            event_kind,
            configuration_revision_id,
            detail,
            created_at
        )
        ON request_engine.platform_configuration_facts
        TO {_READ_DEFINER};

        GRANT EXECUTE ON FUNCTION {_ACTOR_HELPER}
        TO {_READ_DEFINER};

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO {_READ_DEFINER};
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_platform.read_platform_readiness()
        RETURNS TABLE (
            managed_smtp_source text,
            smtp_active_revision bigint,
            smtp_last_validated_at timestamptz,
            smtp_last_provider_test_outcome text,
            smtp_last_provider_test_at timestamptz,
            smtp_secret_configured boolean
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            PERFORM 1
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.readiness.read'
              );

            RETURN QUERY
            WITH active_smtp AS (
                SELECT
                    config.id,
                    config.revision,
                    config.validated_at,
                    config.secret_binding_id
                FROM request_engine.platform_configuration_revisions AS config
                WHERE config.configuration_kind = 'email.delivery'
                  AND config.provider_kind = 'smtp'
                  AND config.state = 'active'
                LIMIT 1
            ),
            latest_test AS (
                SELECT
                    fact.detail ->> 'outcome' AS outcome,
                    fact.created_at
                FROM request_engine.platform_configuration_facts AS fact
                JOIN active_smtp AS active
                  ON active.id = fact.configuration_revision_id
                WHERE fact.event_kind = 'provider_tested'
                ORDER BY fact.created_at DESC
                LIMIT 1
            )
            SELECT
                CASE WHEN active.id IS NULL THEN 'none' ELSE 'managed' END,
                active.revision,
                active.validated_at,
                latest.outcome,
                latest.created_at,
                active.secret_binding_id IS NOT NULL
            FROM (SELECT 1) AS singleton
            LEFT JOIN active_smtp AS active ON true
            LEFT JOIN latest_test AS latest ON true;
        END
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_READ_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_READ_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Platform readiness projection is accepted security surface; roll forward")
