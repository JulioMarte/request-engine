"""Create Organizations without implicit tenant authority.

Revision ID: 0014_platform_organization_provision
Revises: 0013_platform_tenant_provisioner
Create Date: 2026-09-08

A Platform tenant provisioner may create an Organization when it currently owns
organization.provision. The transition deliberately creates no tenant Principal,
Representation, staff membership, tenant-control grant or operational grant.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014_platform_organization_provision"
down_revision: str | Sequence[str] | None = "0013_platform_tenant_provisioner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_ROLE = "request_engine_platform_control"
_DEFINER_ROLE = "request_platform_control_definer"
_FUNCTION = "request_platform.provision_organization(uuid, text, text, text)"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.organization_provisioning_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL UNIQUE
                REFERENCES request_engine.organizations(id),
            provisioned_by_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            provenance_reference text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT organization_provisioning_facts_provenance_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500)
        );
        ALTER TABLE request_engine.organization_provisioning_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.organization_provisioning_facts FROM PUBLIC;
        REVOKE ALL ON request_engine.organization_provisioning_facts FROM request_engine_app;
        """
    )
    op.execute(
        "GRANT INSERT (id, organization_key, display_name) "
        f"ON request_engine.organizations TO {_DEFINER_ROLE}"
    )
    op.execute(
        "GRANT INSERT (organization_id, provisioned_by_principal_id, provenance_reference) "
        f"ON request_engine.organization_provisioning_facts TO {_DEFINER_ROLE}"
    )
    op.execute(f"GRANT USAGE, CREATE ON SCHEMA request_platform TO {_DEFINER_ROLE}")
    op.execute(
        """
        CREATE FUNCTION request_platform.provision_organization(
            p_organization_id uuid,
            p_organization_key text,
            p_display_name text,
            p_provenance_reference text
        ) RETURNS uuid
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
                RAISE EXCEPTION 'Organization provisioning inputs must be nonblank'
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

            INSERT INTO request_engine.organizations (
                id, organization_key, display_name
            ) VALUES (
                p_organization_id, btrim(p_organization_key), btrim(p_display_name)
            );
            INSERT INTO request_engine.organization_provisioning_facts (
                organization_id, provisioned_by_principal_id, provenance_reference
            ) VALUES (
                p_organization_id, v_creator_id, btrim(p_provenance_reference)
            );
            RETURN p_organization_id;
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
        "REVOKE INSERT (organization_id, provisioned_by_principal_id, provenance_reference) "
        f"ON request_engine.organization_provisioning_facts FROM {_DEFINER_ROLE}"
    )
    op.execute(
        "REVOKE INSERT (id, organization_key, display_name) "
        f"ON request_engine.organizations FROM {_DEFINER_ROLE}"
    )
    op.execute("DROP TABLE request_engine.organization_provisioning_facts")
