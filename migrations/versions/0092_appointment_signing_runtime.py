"""Expose only the ACTIVE appointment-option signing keyring reference to HTTP.

Revision ID: 0092_appointment_signing_runtime
Revises: 0091_runtime_config_revision

The public HTTP process must never receive the broad P7 runtime configuration
surface. This SECURITY DEFINER function exposes exactly one configuration family
and only the opaque OpenBao reference/version metadata needed to load its HMAC
keyring from a separately scoped signing-secret proxy.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0092_appointment_signing_runtime"
down_revision: str | Sequence[str] | None = "0091_runtime_config_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_definer"
_HTTP_ROLE = "request_engine_app"
_SIGNATURE = "request_platform.read_active_appointment_option_signing_keyring()"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        GRANT USAGE, CREATE ON SCHEMA request_platform TO request_platform_definer;

        CREATE FUNCTION request_platform.read_active_appointment_option_signing_keyring()
        RETURNS TABLE (
            configuration_revision bigint,
            secret_binding_revision bigint,
            secret_id uuid,
            secret_backend_version integer
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
            SELECT
                config.revision,
                binding.revision,
                binding.secret_id,
                binding.backend_version
              FROM request_engine.platform_configuration_revisions AS config
              JOIN request_engine.platform_secret_bindings AS binding
                ON binding.id = config.secret_binding_id
             WHERE config.configuration_kind = 'security.appointment_option_signing'
               AND config.provider_kind = 'hmac-sha256-keyring'
               AND config.state = 'active'
               AND config.configuration = '{}'::jsonb
               AND binding.purpose = 'security.appointment_option_signing'
               AND binding.backend = 'openbao'
               AND binding.status = 'active'
        $function$;
        """
    )
    op.execute(f"ALTER FUNCTION {_SIGNATURE} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA request_platform TO {_HTTP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO {_HTTP_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError(
        "Appointment signing runtime projection is accepted security surface; roll forward"
    )
