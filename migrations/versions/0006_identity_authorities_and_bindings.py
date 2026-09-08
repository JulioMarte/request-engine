"""Persist provider-neutral authentication authorities and Principal bindings.

Revision ID: 0006_identity_bindings
Revises: 0005_platform_auth_definer
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_identity_bindings"
down_revision: str | Sequence[str] | None = "0005_platform_auth_definer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.identity_authorities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            kind text NOT NULL,
            issuer_or_environment text NOT NULL,
            status text NOT NULL DEFAULT 'active',
            configuration_ref text,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT identity_authorities_kind_check CHECK (length(btrim(kind)) > 0),
            CONSTRAINT identity_authorities_issuer_check
                CHECK (length(btrim(issuer_or_environment)) > 0),
            CONSTRAINT identity_authorities_status_check
                CHECK (status IN ('active', 'disabled')),
            CONSTRAINT identity_authorities_revision_check CHECK (revision > 0),
            UNIQUE (kind, issuer_or_environment)
        );
        ALTER TABLE request_engine.identity_authorities OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.identity_authorities FROM PUBLIC;

        CREATE TABLE request_engine.identity_bindings (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid REFERENCES request_engine.organizations(id),
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            principal_plane text NOT NULL,
            identity_authority_id uuid NOT NULL
                REFERENCES request_engine.identity_authorities(id),
            subject_id text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            revision bigint NOT NULL DEFAULT 1,
            last_seen_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            revoked_at timestamptz,
            CONSTRAINT identity_bindings_principal_plane_check
                CHECK (principal_plane IN ('tenant', 'platform')),
            CONSTRAINT identity_bindings_scope_check CHECK (
                (principal_plane = 'tenant' AND organization_id IS NOT NULL)
                OR (principal_plane = 'platform' AND organization_id IS NULL)
            ),
            CONSTRAINT identity_bindings_subject_check CHECK (length(btrim(subject_id)) > 0),
            CONSTRAINT identity_bindings_status_check
                CHECK (status IN ('pending', 'active', 'suspended', 'revoked')),
            CONSTRAINT identity_bindings_revision_check CHECK (revision > 0),
            CONSTRAINT identity_bindings_revocation_check CHECK (
                (status = 'revoked' AND revoked_at IS NOT NULL)
                OR (status <> 'revoked' AND revoked_at IS NULL)
            ),
            CONSTRAINT identity_bindings_last_seen_check
                CHECK (last_seen_at IS NULL OR last_seen_at >= created_at)
        );
        CREATE UNIQUE INDEX identity_bindings_tenant_subject_live_uq
            ON request_engine.identity_bindings
            (identity_authority_id, subject_id, organization_id)
            WHERE organization_id IS NOT NULL AND status <> 'revoked';
        CREATE UNIQUE INDEX identity_bindings_platform_subject_live_uq
            ON request_engine.identity_bindings (identity_authority_id, subject_id)
            WHERE organization_id IS NULL AND status <> 'revoked';
        CREATE INDEX identity_bindings_principal_lookup_idx
            ON request_engine.identity_bindings (principal_id, status, identity_authority_id);
        ALTER TABLE request_engine.identity_bindings OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.identity_bindings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.identity_bindings FORCE ROW LEVEL SECURITY;
        CREATE POLICY identity_bindings_tenant_isolation ON request_engine.identity_bindings
            USING (
                principal_plane = 'tenant'
                AND organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                principal_plane = 'tenant'
                AND organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.identity_bindings FROM PUBLIC;
        GRANT SELECT ON request_engine.identity_bindings TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_identity_binding()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_org uuid;
            v_plane text;
            v_principal_active boolean;
            v_authority_active boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Identity bindings are append-preserving' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.organization_id, NEW.principal_id, NEW.principal_plane,
                       NEW.identity_authority_id, NEW.subject_id, NEW.created_at)
                   IS DISTINCT FROM
                   ROW(OLD.organization_id, OLD.principal_id, OLD.principal_plane,
                       OLD.identity_authority_id, OLD.subject_id, OLD.created_at)
                THEN
                    RAISE EXCEPTION 'Identity binding identity and scope are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status = OLD.status THEN
                    IF NEW.revision <> OLD.revision
                       OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                       OR NEW.last_seen_at IS NOT DISTINCT FROM OLD.last_seen_at
                       OR (OLD.last_seen_at IS NOT NULL AND NEW.last_seen_at < OLD.last_seen_at)
                    THEN
                        RAISE EXCEPTION 'Only monotonic last_seen_at may change without state transition'
                            USING ERRCODE = '55000';
                    END IF;
                    RETURN NEW;
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       (OLD.status = 'pending' AND NEW.status IN ('active', 'revoked'))
                       OR (OLD.status = 'active' AND NEW.status IN ('suspended', 'revoked'))
                       OR (OLD.status = 'suspended' AND NEW.status IN ('active', 'revoked'))
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Identity binding state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT organization_id, principal_plane, active
              INTO v_org, v_plane, v_principal_active
              FROM request_engine.principals WHERE id = NEW.principal_id;
            IF NOT FOUND OR NEW.organization_id IS DISTINCT FROM v_org
               OR NEW.principal_plane <> v_plane
            THEN
                RAISE EXCEPTION 'Identity binding scope must match target Principal scope'
                    USING ERRCODE = '23514';
            END IF;
            SELECT status = 'active' INTO v_authority_active
              FROM request_engine.identity_authorities WHERE id = NEW.identity_authority_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity authority does not exist' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IN ('pending', 'active')
               AND (NOT v_principal_active OR NOT v_authority_active)
            THEN
                RAISE EXCEPTION 'Live Identity binding requires active authority and Principal'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_identity_binding() OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_identity_binding() FROM PUBLIC;
        CREATE TRIGGER identity_bindings_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.identity_bindings
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_identity_binding();

        CREATE FUNCTION request_engine.bump_principal_authority_from_identity_binding()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'INSERT' AND NEW.status <> 'active' THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            UPDATE request_engine.principals
               SET authority_revision = authority_revision + 1
             WHERE id = NEW.principal_id;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.bump_principal_authority_from_identity_binding()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.bump_principal_authority_from_identity_binding()
            FROM PUBLIC;
        CREATE TRIGGER identity_bindings_bump_principal_revision
            AFTER INSERT OR UPDATE ON request_engine.identity_bindings
            FOR EACH ROW EXECUTE FUNCTION
                request_engine.bump_principal_authority_from_identity_binding();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE request_engine.identity_bindings CASCADE")
    op.execute("DROP FUNCTION request_engine.bump_principal_authority_from_identity_binding()")
    op.execute("DROP FUNCTION request_engine.guard_identity_binding()")
    op.execute("DROP TABLE request_engine.identity_authorities")
