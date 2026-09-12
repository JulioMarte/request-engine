"""Add tenant INTEGRATION Principal governance for external B2B callers.

Revision ID: 0027_integration_governance
Revises: 0026_agent_policy
Create Date: 2026-09-09

INTEGRATION Principals are external machine callers (B2B websites, partner
systems). Provisioning mirrors agent governance without an AgentProfile: the
principal starts with zero authority and a pending workload binding, authority
is assigned strictly within the provisioning HUMAN's active delegable
operational ceiling, and suspend/activate/revoke transitions run through one
revision-checked SECURITY DEFINER function whose state carrier is the identity
binding status. Revocation destroys the workload credential and binding so no
stale bearer can resurrect access.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_integration_governance"
down_revision: str | Sequence[str] | None = "0026_agent_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION request_engine.provision_integration(
            p_principal_id uuid,
            p_binding_id uuid,
            p_workload_identity_id uuid,
            p_credential_id uuid,
            p_identity_authority_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_credential_expires_at timestamptz,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority record;
            v_existing request_engine.principals%ROWTYPE;
            v_existing_binding record;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager(
                'integration.provision'
            );
            IF p_principal_id = v_actor_id
               OR length(btrim(p_provenance_reference)) = 0
               OR p_credential_expires_at IS NULL
               OR p_credential_expires_at <= clock_timestamp()
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
            THEN
                RAISE EXCEPTION 'Invalid integration provisioning input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_existing
              FROM request_engine.principals
             WHERE id = p_principal_id;
            IF FOUND THEN
                IF v_existing.principal_kind <> 'integration'
                   OR v_existing.organization_id IS DISTINCT FROM v_org_id
                THEN
                    RAISE EXCEPTION 'Integration provisioning replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                SELECT * INTO v_existing_binding
                  FROM request_engine.identity_bindings
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Integration provisioning replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.authority_revision;
            END IF;

            IF EXISTS (
                SELECT 1 FROM request_engine.workload_identities
                 WHERE id = p_workload_identity_id
            ) OR EXISTS (
                SELECT 1 FROM request_engine.workload_credentials
                 WHERE id = p_credential_id
            ) THEN
                RAISE EXCEPTION 'Integration provisioning identifiers already exist'
                    USING ERRCODE = '23505';
            END IF;

            SELECT kind, status
              INTO v_authority
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
             FOR SHARE;
            IF NOT FOUND
               OR v_authority.kind <> 'workload'
               OR v_authority.status <> 'active'
            THEN
                RAISE EXCEPTION
                    'Integration provisioning requires an active workload authority'
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
                'integration',
                'workload:' || p_workload_identity_id::text
            );

            INSERT INTO request_engine.workload_identities (
                id,
                identity_authority_id,
                workload_kind,
                status
            ) VALUES (
                p_workload_identity_id,
                p_identity_authority_id,
                'integration',
                'active'
            );

            INSERT INTO request_engine.workload_credentials (
                id,
                workload_identity_id,
                token_digest,
                token_fingerprint,
                status,
                expires_at
            ) VALUES (
                p_credential_id,
                p_workload_identity_id,
                p_token_digest,
                p_token_fingerprint,
                'active',
                p_credential_expires_at
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
                p_workload_identity_id::text,
                'pending'
            );

            SELECT authority_revision
              INTO v_existing.authority_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_existing.authority_revision;
        END
        $$;
        ALTER FUNCTION request_engine.provision_integration(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz, text
        )
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.provision_integration(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.provision_integration(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.replace_integration_authority(
            p_principal_id uuid,
            p_expected_authority_revision bigint,
            p_desired_capabilities text[],
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_principal record;
            v_active boolean;
            v_current_revision bigint;
            v_capability text;
            v_plane text;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager(
                'integration.manage_authority'
            );
            SELECT principal_kind, principal_plane
              INTO v_principal
              FROM request_engine.principals
             WHERE id = p_principal_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration Principal not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_principal.principal_kind <> 'integration'
               OR v_principal.principal_plane <> 'tenant'
            THEN
                RAISE EXCEPTION
                    'Integration authority requires a tenant INTEGRATION Principal'
                    USING ERRCODE = '23514';
            END IF;
            IF p_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Integration authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT active, authority_revision
              INTO v_active, v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id
             FOR UPDATE;
            IF NOT v_active THEN
                RAISE EXCEPTION
                    'Suspended or revoked integrations cannot receive authority'
                    USING ERRCODE = '55000';
            END IF;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Integration authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(COALESCE(p_desired_capabilities, ARRAY[]::text[])) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(COALESCE(p_desired_capabilities, ARRAY[]::text[])) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(
                                COALESCE(p_desired_capabilities, ARRAY[]::text[])
                            ) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Desired integration authority is invalid'
                    USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                SELECT authority_plane
                  INTO v_plane
                  FROM request_engine.principal_authority_grants
                 WHERE organization_id = v_org_id
                   AND principal_id = v_actor_id
                   AND capability_key = v_capability
                   AND status = 'active'
                   AND delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane <> 'operational' THEN
                    RAISE EXCEPTION
                        'Desired authority exceeds the integration operational ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE organization_id = v_org_id
               AND principal_id = p_principal_id
               AND status = 'active'
               AND NOT (
                   capability_key = ANY(
                       COALESCE(p_desired_capabilities, ARRAY[]::text[])
                   )
               );

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = p_principal_id
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    INSERT INTO request_engine.principal_authority_grants (
                        organization_id,
                        principal_id,
                        principal_plane,
                        authority_plane,
                        capability_key,
                        delegable,
                        granted_by_principal_id,
                        provenance_kind,
                        provenance_reference
                    ) VALUES (
                        v_org_id,
                        p_principal_id,
                        'tenant',
                        'operational',
                        v_capability,
                        false,
                        v_actor_id,
                        'integration_authority_management',
                        btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;

            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_current_revision;
        END
        $$;
        ALTER FUNCTION request_engine.replace_integration_authority(
            uuid, bigint, text[], text
        )
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.replace_integration_authority(
            uuid, bigint, text[], text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.replace_integration_authority(
            uuid, bigint, text[], text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.set_integration_status(
            p_principal_id uuid,
            p_expected_revision bigint,
            p_target_status text,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_principal record;
            v_active boolean;
            v_binding_status text;
            v_workload_identity_id uuid;
            v_current_revision bigint;
        BEGIN
            IF p_target_status = 'active' THEN
                v_actor_id := request_engine.assert_staff_manager(
                    'integration.provision'
                );
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                v_actor_id := request_engine.assert_staff_manager(
                    'integration.suspend'
                );
            ELSE
                RAISE EXCEPTION 'Unsupported integration target status'
                    USING ERRCODE = '22023';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            SELECT pr.active, pr.authority_revision,
                   b.status, wi.id
              INTO v_active, v_current_revision,
                   v_binding_status, v_workload_identity_id
              FROM request_engine.principals pr
              LEFT JOIN request_engine.identity_bindings b
                ON b.principal_id = pr.id
               AND b.status <> 'revoked'
              LEFT JOIN request_engine.workload_identities wi
                ON wi.id::text = b.subject_id
             WHERE pr.id = p_principal_id
               AND pr.principal_kind = 'integration'
               AND pr.principal_plane = 'tenant'
               AND pr.organization_id = v_org_id
             FOR UPDATE OF pr;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration Principal not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF p_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Integration self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Integration revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            v_binding_status := COALESCE(v_binding_status, 'revoked');
            IF NOT (
                (v_binding_status = 'pending'
                    AND p_target_status IN ('active', 'revoked'))
                OR (v_binding_status = 'active'
                    AND p_target_status IN ('suspended', 'revoked'))
                OR (v_binding_status = 'suspended'
                    AND p_target_status IN ('active', 'revoked'))
            ) THEN
                RAISE EXCEPTION 'Invalid integration state transition'
                    USING ERRCODE = '55000';
            END IF;
            IF p_target_status = 'active' THEN                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = p_principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
            ELSIF p_target_status = 'suspended' THEN
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = p_principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended',
                       revision = revision + 1
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
            ELSE
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = p_principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
                UPDATE request_engine.workload_credentials
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE workload_identity_id = v_workload_identity_id
                   AND status = 'active';
                UPDATE request_engine.workload_identities
                   SET status = 'disabled',
                       revision = revision + 1,
                       disabled_at = clock_timestamp()
                 WHERE id = v_workload_identity_id
                   AND status = 'active';
            END IF;

            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_current_revision;
        END
        $$;
        ALTER FUNCTION request_engine.set_integration_status(
            uuid, bigint, text, text
        )
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.set_integration_status(
            uuid, bigint, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.set_integration_status(
            uuid, bigint, text, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS request_engine.set_integration_status(
            uuid, bigint, text, text
        );
        DROP FUNCTION IF EXISTS request_engine.replace_integration_authority(
            uuid, bigint, text[], text
        );
        DROP FUNCTION IF EXISTS request_engine.provision_integration(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz, text
        );
        """
    )
