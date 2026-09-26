"""Add the trusted provider-secret resolution boundary for P7-E.

Revision ID: 0083_provider_secret_resolution
Revises: 0082_platform_secret_mutations

SMTP/provider validation needs the opaque secret-store identifier, but the
administrative read projection must never expose it. This migration adds a
control-login-only SECURITY DEFINER projection that returns only the technical
reference needed by trusted provider orchestration. Plaintext remains exclusively
inside PlatformSecretStore.resolve().
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0083_provider_secret_resolution"
down_revision: str | Sequence[str] | None = "0082_platform_secret_mutations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_SIGNATURE = "request_platform.resolve_platform_provider_secret(uuid,text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        GRANT SELECT (
            id,
            purpose,
            backend,
            secret_id,
            backend_version,
            status,
            revision
        )
        ON request_engine.platform_secret_bindings
        TO request_platform_control_definer;

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO request_platform_control_definer;

        CREATE FUNCTION request_platform.resolve_platform_provider_secret(
            p_binding_id uuid,
            p_capability_key text
        )
        RETURNS TABLE (
            binding_id uuid,
            secret_id uuid,
            purpose text,
            backend text,
            backend_version integer,
            status text,
            revision bigint
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
            IF p_binding_id IS NULL
               OR p_capability_key NOT IN (
                   'platform.configuration.validate',
                   'platform.provider.test'
               )
            THEN
                RAISE EXCEPTION 'Platform provider secret resolution input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_ignore_actor, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  p_capability_key
              );

            RETURN QUERY
            SELECT
                binding.id,
                binding.secret_id,
                binding.purpose,
                binding.backend,
                binding.backend_version,
                binding.status,
                binding.revision
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
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
    raise RuntimeError("Provider secret resolution is security-sensitive history; roll forward")
