"""Atomically provision an Organization and its first Native tenant controller.

Revision ID: 0015_native_tenant_root
Revises: 0014_org_provisioning
Create Date: 2026-09-08

The supported zero-to-one transition creates the Organization, its authority
Party, a tenant HUMAN Principal, an active Native IdentityBinding, the minimum
tenant-control bundle, and the four canonical root operational Representations
in one transaction. The Platform provisioner remains outside the tenant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_native_tenant_root"
down_revision: str | Sequence[str] | None = "0014_org_provisioning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_ROLE = "request_engine_platform_control"
_DEFINER_ROLE = "request_platform_control_definer"
_OLD_FUNCTION = "request_platform.provision_organization(uuid, text, text, text)"
_FUNCTION = (
    "request_platform.provision_native_organization_root(uuid, text, text, uuid, uuid, "
    "uuid, uuid, text)"
)


def upgrade() -> None:
    op.execute(f"DROP FUNCTION {_OLD_FUNCTION}")
    op.execute(
        """
        CREATE TABLE request_engine.organization_root_provisioning_facts (
            organization_id uuid PRIMARY KEY
                REFERENCES request_engine.organizations(id),
            organization_party_id uuid NOT NULL UNIQUE
                REFERENCES request_engine.parties(id),
            controller_principal_id uuid NOT NULL UNIQUE
                REFERENCES request_engine.principals(id),
            controller_binding_id uuid NOT NULL UNIQUE
                REFERENCES request_engine.identity_bindings(id),
            provisioned_by_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            provenance_reference text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT organization_root_provisioning_facts_provenance_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500)
        );
        ALTER TABLE request_engine.organization_root_provisioning_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.organization_root_provisioning_facts FROM PUBLIC;
        REVOKE ALL ON request_engine.organization_root_provisioning_facts
            FROM request_engine_app;
        """
    )
    op.execute(
        "GRANT SELECT (id, identity_authority_id, status) "
        f"ON request_engine.native_identities TO {_DEFINER_ROLE}"
    )
    op.execute(
        f"GRANT SELECT (id, kind, status) ON request_engine.identity_authorities TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT INSERT (id, organization_id, party_kind, display_name, "
        "created_by_principal_id, source_kind, platform) "
        f"ON request_engine.parties TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT INSERT (id, organization_id, principal_plane, principal_kind, external_subject) "
        f"ON request_engine.principals TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT INSERT (id, organization_id, principal_id, principal_plane, "
        "identity_authority_id, subject_id, status) "
        f"ON request_engine.identity_bindings TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT INSERT (organization_id, principal_id, represented_party_id, authority_kind, "
        f"scope_key) ON request_engine.representations TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT SELECT (organization_id, organization_party_id, controller_principal_id, "
        "controller_binding_id, provisioned_by_principal_id, provenance_reference), "
        "INSERT (organization_id, organization_party_id, controller_principal_id, "
        "controller_binding_id, provisioned_by_principal_id, provenance_reference) "
        f"ON request_engine.organization_root_provisioning_facts TO {_DEFINER_ROLE}"
    )
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_DEFINER_ROLE}")
    op.execute(
        """
        CREATE FUNCTION request_platform.provision_native_organization_root(
            p_organization_id uuid,
            p_organization_key text,
            p_display_name text,
            p_organization_party_id uuid,
            p_controller_principal_id uuid,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_provenance_reference text
        ) RETURNS TABLE (
            organization_id uuid,
            organization_party_id uuid,
            controller_principal_id uuid,
            controller_binding_id uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_creator_id uuid;
            v_expected_revision bigint;
            v_current_revision bigint;
            v_creator_kind text;
            v_can_provision boolean;
            v_binding_id uuid := pg_catalog.gen_random_uuid();
            v_existing request_engine.organization_root_provisioning_facts%ROWTYPE;
        BEGIN
            BEGIN
                v_creator_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_expected_revision := current_setting(
                    'request_engine.authority_revision', true
                )::bigint;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is missing or malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_creator_id IS NULL OR v_expected_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required' USING ERRCODE = '28000';
            END IF;
            IF length(btrim(p_organization_key)) = 0
               OR length(btrim(p_display_name)) = 0
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Organization root provisioning inputs must be nonblank'
                    USING ERRCODE = '22023';
            END IF;

            SELECT principal_kind, authority_revision
              INTO v_creator_kind, v_current_revision
              FROM request_engine.principals
             WHERE id = v_creator_id
               AND principal_plane = 'platform'
               AND organization_id IS NULL
               AND active
             FOR UPDATE;
            IF NOT FOUND OR v_creator_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal is not provision-capable'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> v_expected_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale' USING ERRCODE = '40001';
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants
                 WHERE principal_id = v_creator_id
                   AND principal_plane = 'platform'
                   AND authority_plane = 'platform'
                   AND capability_key = 'organization.provision'
                   AND status = 'active'
            ) INTO v_can_provision;
            IF NOT v_can_provision THEN
                RAISE EXCEPTION 'Current Platform Principal lacks organization.provision'
                    USING ERRCODE = '42501';
            END IF;

            SELECT * INTO v_existing
              FROM request_engine.organization_root_provisioning_facts
             WHERE organization_id = p_organization_id;
            IF FOUND THEN
                IF v_existing.organization_party_id <> p_organization_party_id
                   OR v_existing.controller_principal_id <> p_controller_principal_id
                   OR v_existing.provisioned_by_principal_id <> v_creator_id
                   OR v_existing.provenance_reference <> btrim(p_provenance_reference)
                THEN
                    RAISE EXCEPTION 'Organization root replay conflicts with existing root'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    v_existing.organization_id,
                    v_existing.organization_party_id,
                    v_existing.controller_principal_id,
                    v_existing.controller_binding_id;
                RETURN;
            END IF;

            PERFORM 1
              FROM request_engine.native_identities AS native_identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = native_identity.identity_authority_id
             WHERE native_identity.id = p_native_identity_id
               AND native_identity.identity_authority_id = p_identity_authority_id
               AND native_identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR KEY SHARE OF native_identity, authority;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'First tenant controller requires an active Native identity'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.organizations (id, organization_key, display_name)
            VALUES (p_organization_id, btrim(p_organization_key), btrim(p_display_name));
            INSERT INTO request_engine.parties (
                id, organization_id, party_kind, display_name,
                created_by_principal_id, source_kind, platform
            ) VALUES (
                p_organization_party_id, p_organization_id, 'organization',
                btrim(p_display_name), v_creator_id, 'operator', 'request_engine'
            );
            INSERT INTO request_engine.principals (
                id, organization_id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_controller_principal_id, p_organization_id, 'tenant', 'human',
                'native:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                v_binding_id, p_organization_id, p_controller_principal_id, 'tenant',
                p_identity_authority_id, p_native_identity_id::text, 'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            )
            SELECT p_organization_id, p_controller_principal_id, 'tenant', 'tenant_control',
                   capability_key, false, v_creator_id, 'provisioning',
                   btrim(p_provenance_reference)
              FROM (VALUES
                  ('staff.invite'),
                  ('staff.manage_membership'),
                  ('staff.manage_authority'),
                  ('agent.provision'),
                  ('agent.manage_authority'),
                  ('agent.suspend'),
                  ('identity.bind')
              ) AS root_control(capability_key);

            INSERT INTO request_engine.representations (
                organization_id, principal_id, represented_party_id, authority_kind, scope_key
            )
            SELECT p_organization_id, p_controller_principal_id, p_organization_party_id,
                   'delegated', scope_key
              FROM (VALUES
                  ('operations.manage_profile'),
                  ('operations.manage_supply'),
                  ('operations.manage_terms'),
                  ('operations.manage_discovery')
              ) AS root_operations(scope_key);

            INSERT INTO request_engine.organization_provisioning_facts (
                organization_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, v_creator_id, btrim(p_provenance_reference)
            );
            INSERT INTO request_engine.organization_root_provisioning_facts (
                organization_id, organization_party_id, controller_principal_id,
                controller_binding_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, p_organization_party_id, p_controller_principal_id,
                v_binding_id, v_creator_id, btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT
                p_organization_id, p_organization_party_id,
                p_controller_principal_id, v_binding_id;
        END
        $$;
        """
    )
    op.execute(f"ALTER FUNCTION {_FUNCTION} OWNER TO {_DEFINER_ROLE}")
    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_DEFINER_ROLE}")
    op.execute(f"REVOKE ALL ON FUNCTION {_FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNCTION} TO {_RUNTIME_ROLE}")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_FUNCTION}")
    op.execute(
        "REVOKE SELECT (organization_id, organization_party_id, controller_principal_id, "
        "controller_binding_id, provisioned_by_principal_id, provenance_reference), "
        "INSERT (organization_id, organization_party_id, controller_principal_id, "
        "controller_binding_id, provisioned_by_principal_id, provenance_reference) "
        f"ON request_engine.organization_root_provisioning_facts FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (organization_id, principal_id, represented_party_id, authority_kind, "
        f"scope_key) ON request_engine.representations FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, organization_id, principal_id, principal_plane, "
        "identity_authority_id, subject_id, status) "
        f"ON request_engine.identity_bindings FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, organization_id, principal_plane, principal_kind, external_subject) "
        f"ON request_engine.principals FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, organization_id, party_kind, display_name, "
        "created_by_principal_id, source_kind, platform) "
        f"ON request_engine.parties FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE SELECT (id, kind, status) ON request_engine.identity_authorities "
        f"FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE SELECT (id, identity_authority_id, status) "
        f"ON request_engine.native_identities FROM {_DEFINER_ROLE}"
    )
    op.execute("DROP TABLE request_engine.organization_root_provisioning_facts")
    # The incomplete 0014 function is intentionally not restored on downgrade.
