"""Derive Staff authority anchors from tenant-root provenance.

Revision ID: 0021_staff_anchor_authority
Revises: 0020_staff_definer_path
Create Date: 2026-09-08

The legacy Staff invitation signature accepted an authority Party identifier from
its caller. Preserve the signature for compatibility, but remove that input's
authority: every new membership is anchored to the canonical Organization Party
recorded by zero-to-one tenant-root provisioning.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_staff_anchor_authority"
down_revision: str | Sequence[str] | None = "0020_staff_definer_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNCTION = "request_engine.invite_native_staff(uuid, uuid, uuid, uuid, uuid, uuid, text)"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION request_engine.invite_native_staff(
            p_membership_id uuid,
            p_principal_id uuid,
            p_binding_id uuid,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_authority_anchor_party_id uuid,
            p_provenance_reference text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority_anchor_party_id uuid;
            v_existing record;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager('staff.invite');
            IF p_principal_id = v_actor_id
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Invalid staff invitation input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT root_fact.organization_party_id
              INTO v_authority_anchor_party_id
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = v_org_id;
            IF v_authority_anchor_party_id IS NULL THEN
                RAISE EXCEPTION 'Tenant root authority anchor is unavailable'
                    USING ERRCODE = '23514';
            END IF;

            SELECT principal_id, identity_binding_id, authority_anchor_party_id
              INTO v_existing
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id;
            IF FOUND THEN
                IF v_existing.principal_id <> p_principal_id
                   OR v_existing.identity_binding_id <> p_binding_id
                   OR v_existing.authority_anchor_party_id <> v_authority_anchor_party_id
                THEN
                    RAISE EXCEPTION 'Staff invitation replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.identity_binding_id;
            END IF;

            IF NOT request_auth.lock_credentialed_native_identity(
                p_identity_authority_id,
                p_native_identity_id
            ) THEN
                RAISE EXCEPTION 'Staff invitation requires a credentialed Native identity'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.principals (
                id,
                organization_id,
                principal_plane,
                principal_kind,
                external_subject
            ) VALUES (
                p_principal_id,
                v_org_id,
                'tenant',
                'human',
                'native:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id,
                organization_id,
                principal_id,
                principal_plane,
                identity_authority_id,
                subject_id,
                status
            ) VALUES (
                p_binding_id,
                v_org_id,
                p_principal_id,
                'tenant',
                p_identity_authority_id,
                p_native_identity_id::text,
                'pending'
            );
            INSERT INTO request_engine.staff_memberships (
                id,
                organization_id,
                principal_id,
                identity_binding_id,
                authority_anchor_party_id,
                status,
                established_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_membership_id,
                v_org_id,
                p_principal_id,
                p_binding_id,
                v_authority_anchor_party_id,
                'invited',
                v_actor_id,
                'staff_invitation',
                btrim(p_provenance_reference)
            );
            RETURN p_binding_id;
        END
        $$;
        """
    )
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO request_engine_schema_owner")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO request_engine_app")


def downgrade() -> None:
    # Do not restore caller-selected authority. The legacy parameter remains only
    # as a compatibility slot until the old signature is retired.
    pass
