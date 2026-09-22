"""Expose ACTIVE platform configuration to the trusted worker runtime.

Revision ID: 0087_active_runtime_config
Revises: 0086_provider_test_facts

The worker receives one narrow SECURITY DEFINER projection. It cannot read
configuration/secret tables directly and receives only the opaque secret_id
needed to call PlatformSecretStore. PostgreSQL ACTIVE state remains authority.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0087_active_runtime_config"
down_revision: str | Sequence[str] | None = "0086_provider_test_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_definer"
_RUNTIME = "request_engine_worker"
_SIGNATURE = "request_platform.read_active_platform_runtime_configuration(text)"


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
            state
        )
        ON request_engine.platform_configuration_revisions
        TO request_platform_definer;

        GRANT SELECT (
            id,
            secret_id,
            purpose,
            backend,
            backend_version,
            status,
            revision
        )
        ON request_engine.platform_secret_bindings
        TO request_platform_definer;

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO request_platform_definer;

        CREATE FUNCTION request_platform.read_active_platform_runtime_configuration(
            p_configuration_kind text
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
               AND config.state = 'active'
               AND p_configuration_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA request_platform TO request_engine_worker")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO {_RUNTIME}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError(
        "Runtime configuration projection is accepted security surface; roll forward"
    )
