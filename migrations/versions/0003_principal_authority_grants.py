"""Persist RE-owned standing Principal authority grants.

Revision ID: 0003_principal_authority_grants
Revises: 0002_principal_trust_root
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_principal_authority_grants"
down_revision: str | Sequence[str] | None = "0002_principal_trust_root"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.principal_authority_grants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid REFERENCES request_engine.organizations(id),
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            principal_plane text NOT NULL,
            authority_plane text NOT NULL,
            capability_key text NOT NULL,
            delegable boolean NOT NULL DEFAULT false,
            status text NOT NULL DEFAULT 'active',
            revision bigint NOT NULL DEFAULT 1,
            granted_by_principal_id uuid REFERENCES request_engine.principals(id),
            provenance_kind text NOT NULL,
            provenance_reference text NOT NULL,
            granted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            revoked_at timestamptz,
            revoked_by_principal_id uuid REFERENCES request_engine.principals(id),
            CONSTRAINT principal_authority_grants_principal_plane_check
                CHECK (principal_plane IN ('tenant', 'platform')),
            CONSTRAINT principal_authority_grants_authority_plane_check
                CHECK (authority_plane IN ('platform', 'tenant_control', 'operational')),
            CONSTRAINT principal_authority_grants_status_check
                CHECK (status IN ('active', 'revoked')),
            CONSTRAINT principal_authority_grants_revision_check CHECK (revision > 0),
            CONSTRAINT principal_authority_grants_capability_key_check
                CHECK (length(btrim(capability_key)) > 0),
            CONSTRAINT principal_authority_grants_provenance_reference_check
                CHECK (length(btrim(provenance_reference)) > 0),
            CONSTRAINT principal_authority_grants_provenance_check CHECK (
                (provenance_kind = 'trust_bootstrap' AND granted_by_principal_id IS NULL)
                OR (provenance_kind <> 'trust_bootstrap' AND granted_by_principal_id IS NOT NULL)
            ),
            CONSTRAINT principal_authority_grants_revocation_check CHECK (
                (status = 'active' AND revoked_at IS NULL AND revoked_by_principal_id IS NULL)
                OR (status = 'revoked' AND revoked_at IS NOT NULL
                    AND revoked_by_principal_id IS NOT NULL AND revoked_at >= granted_at)
            )
        );
        CREATE UNIQUE INDEX principal_authority_grants_active_capability_uq
            ON request_engine.principal_authority_grants (principal_id, capability_key)
            WHERE status = 'active';
        CREATE INDEX principal_authority_grants_tenant_lookup_idx
            ON request_engine.principal_authority_grants
            (organization_id, principal_id, authority_plane, capability_key)
            WHERE status = 'active';
        ALTER TABLE request_engine.principal_authority_grants
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.principal_authority_grants ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.principal_authority_grants FORCE ROW LEVEL SECURITY;
        CREATE POLICY principal_authority_grants_tenant_isolation
            ON request_engine.principal_authority_grants
            USING (
                principal_plane = 'tenant'
                AND organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                principal_plane = 'tenant'
                AND organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.principal_authority_grants FROM PUBLIC;
        GRANT SELECT ON request_engine.principal_authority_grants TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_principal_authority_grant()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_org uuid;
            v_plane text;
            v_active boolean;
            v_grantor_active boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Principal authority grants are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.organization_id, NEW.principal_id, NEW.principal_plane,
                       NEW.authority_plane, NEW.capability_key, NEW.delegable,
                       NEW.granted_by_principal_id, NEW.provenance_kind,
                       NEW.provenance_reference, NEW.granted_at)
                   IS DISTINCT FROM
                   ROW(OLD.organization_id, OLD.principal_id, OLD.principal_plane,
                       OLD.authority_plane, OLD.capability_key, OLD.delegable,
                       OLD.granted_by_principal_id, OLD.provenance_kind,
                       OLD.provenance_reference, OLD.granted_at)
                   OR OLD.status <> 'active' OR NEW.status <> 'revoked'
                   OR NEW.revision <> OLD.revision + 1
                THEN
                    RAISE EXCEPTION
                        'Principal authority grant may only transition active to revoked'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            SELECT organization_id, principal_plane, active
              INTO v_org, v_plane, v_active
              FROM request_engine.principals WHERE id = NEW.principal_id;
            IF NOT FOUND OR NOT v_active THEN
                RAISE EXCEPTION 'Authority target Principal must be active'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.organization_id IS DISTINCT FROM v_org OR NEW.principal_plane <> v_plane THEN
                RAISE EXCEPTION 'Authority grant scope must match target Principal scope'
                    USING ERRCODE = '23514';
            END IF;
            IF (v_plane = 'platform' AND NEW.authority_plane <> 'platform')
               OR (v_plane = 'tenant' AND NEW.authority_plane = 'platform')
            THEN
                RAISE EXCEPTION 'Authority plane is incompatible with target Principal plane'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.granted_by_principal_id IS NOT NULL THEN
                SELECT active INTO v_grantor_active FROM request_engine.principals
                 WHERE id = NEW.granted_by_principal_id;
                IF NOT FOUND OR NOT v_grantor_active THEN
                    RAISE EXCEPTION 'Grantor Principal must be active' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_principal_authority_grant()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_principal_authority_grant() FROM PUBLIC;
        CREATE TRIGGER principal_authority_grants_guard
            BEFORE INSERT OR UPDATE OR DELETE ON request_engine.principal_authority_grants
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_principal_authority_grant();

        CREATE FUNCTION request_engine.bump_principal_authority_from_grant()
        RETURNS trigger LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            UPDATE request_engine.principals
               SET authority_revision = authority_revision + 1
             WHERE id = NEW.principal_id;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.bump_principal_authority_from_grant()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.bump_principal_authority_from_grant() FROM PUBLIC;
        CREATE TRIGGER principal_authority_grants_bump_revision
            AFTER INSERT OR UPDATE ON request_engine.principal_authority_grants
            FOR EACH ROW EXECUTE FUNCTION request_engine.bump_principal_authority_from_grant();
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE request_engine.principal_authority_grants CASCADE")
    op.execute("DROP FUNCTION request_engine.bump_principal_authority_from_grant()")
    op.execute("DROP FUNCTION request_engine.guard_principal_authority_grant()")
