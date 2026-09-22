"""Invalidate managed runtime caches when an active secret binding changes.

Revision ID: 0088_secret_runtime_notify
Revises: 0087_active_runtime_configuration

Configuration activation already emits request_engine_platform_configuration.
Secret rotation/revocation can change the runtime fingerprint without changing
the configuration revision, so this trigger emits the same invalidation signal
for ACTIVE configurations referencing the changed binding.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0088_secret_runtime_notify"
down_revision: str | Sequence[str] | None = "0087_active_runtime_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE FUNCTION request_engine.notify_platform_secret_runtime_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_config record;
        BEGIN
            IF ROW(NEW.backend_version, NEW.revision, NEW.status)
               IS NOT DISTINCT FROM
               ROW(OLD.backend_version, OLD.revision, OLD.status)
            THEN
                RETURN NEW;
            END IF;

            FOR v_config IN
                SELECT configuration_kind, revision
                  FROM request_engine.platform_configuration_revisions
                 WHERE secret_binding_id = NEW.id
                   AND state = 'active'
            LOOP
                PERFORM pg_catalog.pg_notify(
                    'request_engine_platform_configuration',
                    jsonb_build_object(
                        'configuration_kind', v_config.configuration_kind,
                        'revision', v_config.revision,
                        'secret_binding_revision', NEW.revision,
                        'secret_backend_version', NEW.backend_version,
                        'secret_status', NEW.status
                    )::text
                );
            END LOOP;
            RETURN NEW;
        END
        $function$;

        ALTER FUNCTION request_engine.notify_platform_secret_runtime_change()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
            request_engine.notify_platform_secret_runtime_change()
            FROM PUBLIC;

        CREATE TRIGGER platform_secret_binding_runtime_notify
            AFTER UPDATE ON request_engine.platform_secret_bindings
            FOR EACH ROW
            EXECUTE FUNCTION request_engine.notify_platform_secret_runtime_change();
        """
    )


def downgrade() -> None:
    raise RuntimeError("Runtime invalidation behavior is accepted history; roll forward")
