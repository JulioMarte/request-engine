"""Project managed OIDC state into platform readiness.

Revision ID: 0094_managed_oidc_readiness
Revises: 0093_managed_oidc_projection

OIDC readiness is now a durable fact derived from the governed ACTIVE revision,
not from a deployment/environment flag.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0094_managed_oidc_readiness"
down_revision: str | Sequence[str] | None = "0093_managed_oidc_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READ_DEFINER = "request_platform_definer"
_SIGNATURE = "request_platform.read_platform_readiness()"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        f"""
        GRANT SELECT (
            id, kind, issuer_or_environment, status, configuration_ref
        )
        ON request_engine.identity_authorities
        TO {_READ_DEFINER};
        """
    )
    op.execute(f"DROP FUNCTION {_SIGNATURE}")
    op.execute(
        r"""
        CREATE FUNCTION request_platform.read_platform_readiness()
        RETURNS TABLE (
            managed_smtp_source text,
            smtp_active_revision bigint,
            smtp_last_validated_at timestamptz,
            smtp_last_provider_test_outcome text,
            smtp_last_provider_test_at timestamptz,
            smtp_secret_configured boolean,
            oidc text
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
            active_oidc AS (
                SELECT
                    config.revision,
                    config.configuration ->> 'issuer' AS issuer,
                    config.configuration ->> 'jwks_uri' AS jwks_uri,
                    config.configuration ->> 'audience' AS audience
                FROM request_engine.platform_configuration_revisions AS config
                WHERE config.configuration_kind = 'identity.oidc'
                  AND config.provider_kind = 'oidc'
                  AND config.state = 'active'
                LIMIT 1
            ),
            projected_oidc AS (
                SELECT authority.id
                FROM active_oidc AS config
                JOIN request_engine.identity_authorities AS authority
                  ON authority.kind = 'oidc'
                 AND authority.issuer_or_environment = config.issuer
                 AND authority.status = 'active'
                 AND authority.configuration_ref::jsonb ->> 'jwks_uri' = config.jwks_uri
                 AND authority.configuration_ref::jsonb ->> 'audience' = config.audience
                 AND (authority.configuration_ref::jsonb ->> 'managed_configuration_revision')::bigint
                     = config.revision
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
                active.secret_binding_id IS NOT NULL,
                CASE
                    WHEN oidc.revision IS NULL THEN 'unconfigured'
                    WHEN projected.id IS NULL THEN 'degraded'
                    ELSE 'managed'
                END
            FROM (SELECT 1) AS singleton
            LEFT JOIN active_smtp AS active ON true
            LEFT JOIN active_oidc AS oidc ON true
            LEFT JOIN projected_oidc AS projected ON true
            LEFT JOIN latest_test AS latest ON true;
        END
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_READ_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")


def downgrade() -> None:
    raise RuntimeError("Managed OIDC readiness is accepted security surface; roll forward")
