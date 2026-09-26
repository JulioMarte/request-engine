"""Expose exact historical P7 runtime revisions for delivery reconciliation.

Revision ID: 0091_runtime_config_revision
Revises: 0090_platform_readiness

New Communications sends may hot-reload the ACTIVE configuration. A later
provider lookup must use the same configuration revision that performed the
send, so the worker receives a narrow exact-revision projection for ACTIVE or
SUPERSEDED revisions. Disabled revisions intentionally fail closed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0091_runtime_config_revision"
down_revision: str | Sequence[str] | None = "0090_platform_readiness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_definer"
_RUNTIME = "request_engine_worker"
_SIGNATURE = "request_platform.read_platform_runtime_configuration_revision(text,bigint)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        GRANT USAGE, CREATE ON SCHEMA request_platform TO request_platform_definer;

        CREATE FUNCTION request_platform.read_platform_runtime_configuration_revision(
            p_configuration_kind text,
            p_revision bigint
        )
        RETURNS TABLE (
            configuration_revision_id uuid,
            configuration_kind text,
            provider_kind text,
            revision bigint,
            configuration jsonb,
            secret_binding_id uuid,
            secret_binding_revision bigint,
            secret_id uuid,
            secret_purpose text,
            secret_backend text,
            secret_backend_version integer,
            secret_status text
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
            SELECT
                config.id,
                config.configuration_kind,
                config.provider_kind,
                config.revision,
                config.configuration,
                config.secret_binding_id,
                binding.revision,
                binding.secret_id,
                binding.purpose,
                binding.backend,
                binding.backend_version,
                binding.status
              FROM request_engine.platform_configuration_revisions AS config
              LEFT JOIN request_engine.platform_secret_bindings AS binding
                ON binding.id = config.secret_binding_id
             WHERE config.configuration_kind = p_configuration_kind
               AND config.revision = p_revision
               AND config.state IN ('active', 'superseded')
               AND p_configuration_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'
               AND p_revision > 0
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError(
        "Historical runtime configuration projection is accepted history; roll forward"
    )
