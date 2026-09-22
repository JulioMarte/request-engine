"""Add capability-scoped provider candidate reads for P7-E.

Revision ID: 0085_provider_candidate_read
Revises: 0084_provider_validation_fence

Provider validation/test orchestration must inspect a candidate without requiring
the independent administrative read capability. This projection is available
only to the control login and accepts exactly the validate/test capabilities.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0085_provider_candidate_read"
down_revision: str | Sequence[str] | None = "0084_provider_validation_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_SIGNATURE = "request_platform.read_platform_provider_candidate(text,bigint,text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        GRANT SELECT (
            id,
            configuration_kind,
            provider_kind,
            revision,
            configuration,
            secret_binding_id,
            state,
            created_by_principal_id,
            created_at,
            validated_at,
            activated_at,
            disabled_at
        )
        ON request_engine.platform_configuration_revisions
        TO request_platform_control_definer;

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO request_platform_control_definer;

        CREATE FUNCTION request_platform.read_platform_provider_candidate(
            p_configuration_kind text,
            p_revision bigint,
            p_capability_key text
        )
        RETURNS TABLE (
            configuration_revision_id uuid,
            configuration_kind text,
            provider_kind text,
            revision bigint,
            configuration jsonb,
            secret_binding_id uuid,
            state text,
            created_by_principal_id uuid,
            created_at timestamptz,
            validated_at timestamptz,
            activated_at timestamptz,
            disabled_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_ignore_actor uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
        BEGIN
            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL OR p_revision < 1
               OR p_capability_key NOT IN (
                   'platform.configuration.validate',
                   'platform.provider.test'
               )
            THEN
                RAISE EXCEPTION 'Platform provider candidate input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_ignore_actor, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  p_capability_key
              );

            RETURN QUERY
            SELECT
                r.id,
                r.configuration_kind,
                r.provider_kind,
                r.revision,
                r.configuration,
                r.secret_binding_id,
                r.state,
                r.created_by_principal_id,
                r.created_at,
                r.validated_at,
                r.activated_at,
                r.disabled_at
              FROM request_engine.platform_configuration_revisions AS r
             WHERE r.configuration_kind = p_configuration_kind
               AND r.revision = p_revision;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform configuration revision does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
        END
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Provider candidate projection is a governed surface; roll forward")
