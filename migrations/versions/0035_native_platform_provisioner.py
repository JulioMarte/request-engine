"""Atomically bind a bounded native platform provisioner with safe replay.

Revision ID: 0035_native_platform_provisioner
Revises: 0034_platform_binding_read
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035_native_platform_provisioner"
down_revision: str | Sequence[str] | None = "0034_platform_binding_read"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE = "request_platform_control_definer"
_FUNCTION = "request_platform.provision_native_tenant_provisioner(uuid, uuid, uuid, uuid, text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "GRANT SELECT (id, organization_id, principal_id, principal_plane, "
        "identity_authority_id, subject_id) ON request_engine.identity_bindings "
        f"TO {_ROLE}"
    )
    op.execute(
        "GRANT SELECT (granted_by_principal_id, provenance_kind, provenance_reference) "
        f"ON request_engine.principal_authority_grants TO {_ROLE}"
    )
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_ROLE}")
    op.execute("""
        CREATE FUNCTION request_platform.provision_native_tenant_provisioner(
            p_principal_id uuid,
            p_binding_id uuid,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_provenance_reference text
        ) RETURNS uuid
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_creator_id uuid;
        BEGIN
            IF p_principal_id IS NULL OR p_binding_id IS NULL
               OR p_identity_authority_id IS NULL OR p_native_identity_id IS NULL
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                RAISE EXCEPTION 'Native provisioner identity and provenance are required'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                v_creator_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed' USING ERRCODE = '28000';
            END;
            IF v_creator_id IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;

            -- Keep the creator lock outside the exception subtransaction so a
            -- replay cannot race a committed revocation of the creator's grants.
            PERFORM 1 FROM request_engine.principals
             WHERE id = v_creator_id AND principal_plane = 'platform'
             FOR UPDATE;
            BEGIN
                -- This existing command remains the single authority/ceiling
                -- gate, including on replay before it reaches a unique conflict.
                PERFORM request_platform.provision_tenant_provisioner(
                    p_principal_id,
                    'native:' || p_identity_authority_id::text || ':' || p_native_identity_id::text,
                    btrim(p_provenance_reference)
                );
                IF NOT request_auth.lock_credentialed_native_identity(
                    p_identity_authority_id, p_native_identity_id
                ) THEN
                    RAISE EXCEPTION 'Active credentialed Native identity is required'
                        USING ERRCODE = '23514';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM request_engine.identity_bindings
                     WHERE identity_authority_id = p_identity_authority_id
                       AND subject_id = p_native_identity_id::text
                       AND principal_plane = 'platform' AND organization_id IS NULL
                ) THEN
                    RAISE EXCEPTION 'Native identity already has platform binding history'
                        USING ERRCODE = '23505';
                END IF;
                INSERT INTO request_engine.identity_bindings (
                    id, principal_id, principal_plane, identity_authority_id, subject_id, status
                ) VALUES (
                    p_binding_id, p_principal_id, 'platform', p_identity_authority_id,
                    p_native_identity_id::text, 'active'
                );
                RETURN p_principal_id;
            EXCEPTION WHEN unique_violation THEN
                -- The failed attempt has rolled back all of its writes. Compare
                -- every immutable input/provenance field; never activate/regrant.
                IF EXISTS (
                    SELECT 1 FROM request_engine.identity_bindings b
                    JOIN request_engine.principals p ON p.id = b.principal_id
                    JOIN request_engine.principal_authority_grants g ON g.principal_id = p.id
                    WHERE b.id = p_binding_id AND b.principal_id = p_principal_id
                      AND b.identity_authority_id = p_identity_authority_id
                      AND b.subject_id = p_native_identity_id::text
                      AND b.principal_plane = 'platform' AND b.organization_id IS NULL
                      AND p.principal_plane = 'platform' AND p.organization_id IS NULL
                      AND p.principal_kind = 'human'
                      AND g.principal_plane = 'platform' AND g.authority_plane = 'platform'
                      AND g.capability_key = 'organization.provision' AND NOT g.delegable
                      AND g.granted_by_principal_id = v_creator_id
                      AND g.provenance_kind = 'provisioning'
                      AND g.provenance_reference = btrim(p_provenance_reference)
                ) THEN
                    RETURN p_principal_id;
                END IF;
                RAISE;
            END;
        END $$;
    """)
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO {_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO request_platform_control")


def downgrade() -> None:
    raise RuntimeError("Native provisioner provenance requires a forward migration")
