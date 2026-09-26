"""Project managed OIDC state into platform readiness.

Revision ID: 0094_managed_oidc_readiness
Revises: 0093_managed_oidc_projection

The database reports whether managed OIDC is configured and internally healthy.
Whether an unconfigured provider is optional is a deployment/product-policy fact
composed above this durable PostgreSQL projection.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0094_managed_oidc_readiness"
down_revision: str | Sequence[str] | None = "0093_managed_oidc_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READ_DEFINER = "request_platform_definer"
_SCHEMA_OWNER = "request_engine_schema_owner"
_SIGNATURE = "request_platform.read_platform_readiness()"
_PROJECTION_SIGNATURE = (
    "request_platform.managed_oidc_projection_matches(text, text, text, bigint)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # request_engine_schema_owner already owns request_platform. Keep the
    # platform read definer on its reviewed column-level surface: readiness gets
    # only a boolean identity projection through this narrow SECURITY DEFINER
    # boundary instead of direct reads from identity_authorities.
    op.execute(
        r"""
        CREATE FUNCTION request_platform.managed_oidc_projection_matches(
            p_issuer text,
            p_jwks_uri text,
            p_audience text,
            p_revision bigint
        )
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.kind = 'oidc'
                   AND authority.issuer_or_environment = p_issuer
                   AND authority.status = 'active'
                   AND authority.configuration_ref = jsonb_build_object(
                       'jwks_uri', p_jwks_uri,
                       'audience', p_audience,
                       'managed_configuration_revision', p_revision
                   )::text
            )
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_PROJECTION_SIGNATURE} OWNER TO {_SCHEMA_OWNER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_PROJECTION_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_PROJECTION_SIGNATURE} TO {_READ_DEFINER}")

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
                    WHEN request_platform.managed_oidc_projection_matches(
                        oidc.issuer,
                        oidc.jwks_uri,
                        oidc.audience,
                        oidc.revision
                    ) THEN 'managed'
                    ELSE 'degraded'
                END
            FROM (SELECT 1) AS singleton
            LEFT JOIN active_smtp AS active ON true
            LEFT JOIN active_oidc AS oidc ON true
            LEFT JOIN latest_test AS latest ON true;
        END
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_READ_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")


def downgrade() -> None:
    raise RuntimeError("Managed OIDC readiness is accepted security surface; roll forward")
