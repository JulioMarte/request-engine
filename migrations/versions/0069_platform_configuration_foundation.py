"""Private platform configuration revision and secret-binding foundation.

Revision ID: 0069_platform_configuration
Revises: 0068_recovery_code_password_reset

This migration establishes durable, private platform configuration metadata but
intentionally exposes no application mutation function yet. P5 must establish
the governed Platform Owner/admin authority that future P7 HTTP commands consume.

- configuration payloads are versioned and typed by kind/provider;
- at most one revision per kind can be active;
- payload/secret binding identity is immutable once staged;
- lifecycle transitions are constrained by a trigger;
- secret bindings store only opaque backend IDs/versions, never plaintext;
- all three tables are private to runtime roles until a later reviewed command
  surface grants narrow authority.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0069_platform_configuration"
down_revision: str | Sequence[str] | None = "0068_recovery_code_password_reset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE TABLE request_engine.platform_secret_bindings (
            id uuid PRIMARY KEY,
            purpose text NOT NULL,
            backend text NOT NULL,
            secret_id uuid NOT NULL UNIQUE,
            backend_version integer NOT NULL,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            rotated_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT platform_secret_bindings_purpose_check CHECK (
                purpose ~ '^[a-z][a-z0-9_.-]{1,127}$'
            ),
            CONSTRAINT platform_secret_bindings_backend_check CHECK (
                backend IN ('openbao', 'vault')
            ),
            CONSTRAINT platform_secret_bindings_version_check CHECK (backend_version > 0),
            CONSTRAINT platform_secret_bindings_status_check CHECK (
                status IN ('active', 'revoked')
            ),
            CONSTRAINT platform_secret_bindings_revision_check CHECK (revision > 0),
            CONSTRAINT platform_secret_bindings_revocation_check CHECK (
                (status = 'active' AND revoked_at IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX platform_secret_bindings_active_purpose_uq
            ON request_engine.platform_secret_bindings (purpose)
            WHERE status = 'active';
        ALTER TABLE request_engine.platform_secret_bindings
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_secret_bindings FROM PUBLIC;

        CREATE TABLE request_engine.platform_configuration_revisions (
            id uuid PRIMARY KEY,
            configuration_kind text NOT NULL,
            provider_kind text NOT NULL,
            revision bigint NOT NULL,
            configuration jsonb NOT NULL,
            secret_binding_id uuid
                REFERENCES request_engine.platform_secret_bindings(id),
            state text NOT NULL DEFAULT 'draft',
            created_by_principal_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            validated_at timestamptz,
            activated_at timestamptz,
            disabled_at timestamptz,
            CONSTRAINT platform_configuration_kind_check CHECK (
                configuration_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'
            ),
            CONSTRAINT platform_configuration_provider_check CHECK (
                provider_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'
            ),
            CONSTRAINT platform_configuration_revision_check CHECK (revision > 0),
            CONSTRAINT platform_configuration_object_check CHECK (
                jsonb_typeof(configuration) = 'object'
            ),
            CONSTRAINT platform_configuration_state_check CHECK (
                state IN ('draft', 'validated', 'active', 'superseded', 'disabled')
            ),
            CONSTRAINT platform_configuration_lifecycle_time_check CHECK (
                (state = 'draft'
                    AND validated_at IS NULL
                    AND activated_at IS NULL
                    AND disabled_at IS NULL)
                OR (state = 'validated'
                    AND validated_at IS NOT NULL
                    AND activated_at IS NULL
                    AND disabled_at IS NULL)
                OR (state = 'active'
                    AND validated_at IS NOT NULL
                    AND activated_at IS NOT NULL
                    AND disabled_at IS NULL)
                OR (state = 'superseded'
                    AND validated_at IS NOT NULL
                    AND activated_at IS NOT NULL
                    AND disabled_at IS NULL)
                OR (state = 'disabled' AND disabled_at IS NOT NULL)
            ),
            UNIQUE (configuration_kind, revision)
        );
        CREATE UNIQUE INDEX platform_configuration_one_active_kind_uq
            ON request_engine.platform_configuration_revisions (configuration_kind)
            WHERE state = 'active';
        CREATE INDEX platform_configuration_kind_revision_idx
            ON request_engine.platform_configuration_revisions (
                configuration_kind, revision DESC
            );
        ALTER TABLE request_engine.platform_configuration_revisions
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_configuration_revisions FROM PUBLIC;

        CREATE TABLE request_engine.platform_configuration_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            event_kind text NOT NULL,
            configuration_revision_id uuid,
            configuration_kind text NOT NULL,
            revision bigint,
            secret_binding_id uuid,
            actor_principal_id uuid,
            actor_authentication_method text,
            correlation_id uuid,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_configuration_facts_kind_check CHECK (
                event_kind IN (
                    'staged',
                    'validated',
                    'activated',
                    'superseded',
                    'disabled',
                    'secret_bound',
                    'secret_rotated',
                    'secret_revoked'
                )
            ),
            CONSTRAINT platform_configuration_facts_detail_check CHECK (
                jsonb_typeof(detail) = 'object'
            )
        );
        ALTER TABLE request_engine.platform_configuration_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_configuration_facts FROM PUBLIC;
        CREATE TRIGGER platform_configuration_facts_append_only
            BEFORE UPDATE OR DELETE ON request_engine.platform_configuration_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_engine.guard_platform_secret_binding()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.purpose, NEW.backend, NEW.secret_id, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.purpose, OLD.backend, OLD.secret_id, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Platform secret binding identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'active'
               AND NEW.backend_version > OLD.backend_version
               AND NEW.revision = OLD.revision + 1
               AND NEW.rotated_at IS NOT NULL
               AND (OLD.rotated_at IS NULL OR NEW.rotated_at >= OLD.rotated_at)
               AND NEW.revoked_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'revoked'
               AND NEW.backend_version = OLD.backend_version
               AND NEW.revision = OLD.revision + 1
               AND NEW.rotated_at IS NOT DISTINCT FROM OLD.rotated_at
               AND NEW.revoked_at IS NOT NULL
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid platform secret binding transition'
                USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_platform_secret_binding()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_platform_secret_binding() FROM PUBLIC;
        CREATE TRIGGER platform_secret_binding_guard
            BEFORE UPDATE ON request_engine.platform_secret_bindings
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_secret_binding();

        CREATE FUNCTION request_engine.guard_platform_configuration_revision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(
                NEW.id,
                NEW.configuration_kind,
                NEW.provider_kind,
                NEW.revision,
                NEW.configuration,
                NEW.secret_binding_id,
                NEW.created_by_principal_id,
                NEW.created_at
            ) IS DISTINCT FROM ROW(
                OLD.id,
                OLD.configuration_kind,
                OLD.provider_kind,
                OLD.revision,
                OLD.configuration,
                OLD.secret_binding_id,
                OLD.created_by_principal_id,
                OLD.created_at
            )
            THEN
                RAISE EXCEPTION 'Platform configuration payload is immutable'
                    USING ERRCODE = '55000';
            END IF;

            IF OLD.state = 'draft'
               AND NEW.state = 'validated'
               AND NEW.validated_at IS NOT NULL
               AND NEW.activated_at IS NULL
               AND NEW.disabled_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.state = 'validated'
               AND NEW.state = 'active'
               AND NEW.validated_at IS NOT DISTINCT FROM OLD.validated_at
               AND NEW.activated_at IS NOT NULL
               AND NEW.disabled_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.state = 'active'
               AND NEW.state = 'superseded'
               AND NEW.validated_at IS NOT DISTINCT FROM OLD.validated_at
               AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
               AND NEW.disabled_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.state IN ('draft', 'validated', 'active')
               AND NEW.state = 'disabled'
               AND NEW.validated_at IS NOT DISTINCT FROM OLD.validated_at
               AND NEW.activated_at IS NOT DISTINCT FROM OLD.activated_at
               AND NEW.disabled_at IS NOT NULL
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid platform configuration lifecycle transition'
                USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_platform_configuration_revision()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_platform_configuration_revision() FROM PUBLIC;
        CREATE TRIGGER platform_configuration_revision_guard
            BEFORE UPDATE ON request_engine.platform_configuration_revisions
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_configuration_revision();
        """
    )


def downgrade() -> None:
    raise RuntimeError("Platform configuration state is append-preserving; roll forward")
