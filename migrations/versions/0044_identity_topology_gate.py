"""Serialize identity-topology writers with a transactional advisory gate (D5/B3).

Revision ID: 0044_identity_topology_gate
Revises: 0043_provisioner_lifecycle

The identity-topology gate is a transaction-scoped PostgreSQL advisory lock with
the registered namespace pair (1380274257, 1902476357). SHARE is taken by every
local command that can alter identity bindings, control grants, staff
memberships or the reachability they express. EXCLUSIVE is reserved for global
disable or global authority modification; ``request_platform.establish_root``
is the only EXCLUSIVE writer today.

Ordering contract: the gate is the first statement of each command, before any
row lock. Command bodies are mechanically re-emitted from the accepted head
(0001..0043) with exactly one inserted statement and no other change; the
INSERT/UPDATE/DELETE statements, validation order and ACLs are unchanged.

Runtime roles hold no direct DML on the topology tables and cannot execute the
gate functions directly (PUBLIC revoked; only the owning definers are granted).
Trigger functions ``request_engine.seed_initial_controller_policy``,
``request_engine.seed_root_staff_membership`` and
``request_engine.seed_root_staff_read_authority`` are intentionally NOT gated:
they fire from ``request_engine.organization_root_provisioning_facts`` rows
written inside the gated ``provision_native_organization_root`` transaction and
are not independently callable by runtime roles. Privileged maintenance paths
(migration backfills, superuser DDL/DML) bypass the gate by construction and
must acquire it explicitly when they mutate topology outside a command.

Downgrade is roll-forward only: removing the gate would silently reopen the
discovery race this revision closes.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044_identity_topology_gate"
down_revision: str | Sequence[str] | None = "0043_provisioner_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_engine.acquire_identity_topology_share()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock_shared(1380274257, 1902476357);
        END
        $function$;

        CREATE OR REPLACE FUNCTION request_engine.acquire_identity_topology_exclusive()
        RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476357);
        END
        $function$;

        ALTER FUNCTION request_engine.acquire_identity_topology_share()
            OWNER TO request_engine_schema_owner;
        ALTER FUNCTION request_engine.acquire_identity_topology_exclusive()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.acquire_identity_topology_share()
            FROM PUBLIC;
        REVOKE ALL ON FUNCTION request_engine.acquire_identity_topology_exclusive()
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.acquire_identity_topology_share()
            TO request_platform_control_definer, request_bootstrap_definer;
        GRANT EXECUTE ON FUNCTION request_engine.acquire_identity_topology_exclusive()
            TO request_platform_control_definer, request_bootstrap_definer;
        """
    )

    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.invite_native_staff(p_membership_id uuid, p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_authority_anchor_party_id uuid, p_provenance_reference text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority_anchor_party_id uuid;
            v_existing record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.provision_agent(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_display_name text, p_purpose text, p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority record;
            v_existing request_engine.agent_profiles%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager('agent.provision');
            IF p_principal_id = v_actor_id
               OR p_sponsor_principal_id = p_principal_id
               OR length(btrim(p_provenance_reference)) = 0
               OR length(btrim(p_display_name)) = 0
               OR length(btrim(p_purpose)) = 0
               OR p_operating_mode NOT IN ('autonomous', 'assisted')
               OR p_credential_expires_at IS NULL
               OR p_credential_expires_at <= clock_timestamp()
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
            THEN
                RAISE EXCEPTION 'Invalid agent provisioning input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_existing
              FROM request_engine.agent_profiles
             WHERE principal_id = p_principal_id;
            IF FOUND THEN
                IF ROW(
                    v_existing.organization_id,
                    v_existing.workload_identity_id,
                    v_existing.display_name,
                    v_existing.purpose,
                    v_existing.sponsor_principal_id,
                    v_existing.operating_mode
                ) IS DISTINCT FROM ROW(
                    v_org_id,
                    p_workload_identity_id,
                    p_display_name,
                    p_purpose,
                    p_sponsor_principal_id,
                    p_operating_mode
                ) THEN
                    RAISE EXCEPTION 'Agent provisioning replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.revision;
            END IF;

            IF EXISTS (
                SELECT 1 FROM request_engine.principals
                 WHERE id = p_principal_id
            ) OR EXISTS (
                SELECT 1 FROM request_engine.workload_identities
                 WHERE id = p_workload_identity_id
            ) OR EXISTS (
                SELECT 1 FROM request_engine.workload_credentials
                 WHERE id = p_credential_id
            ) THEN
                RAISE EXCEPTION 'Agent provisioning identifiers already exist'
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
                RAISE EXCEPTION 'Agent provisioning requires an active workload authority'
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
                'agent',
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
                'agent',
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

            INSERT INTO request_engine.agent_profiles (
                principal_id,
                organization_id,
                display_name,
                purpose,
                sponsor_principal_id,
                status,
                operating_mode,
                workload_identity_id,
                established_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_principal_id,
                v_org_id,
                btrim(p_display_name),
                btrim(p_purpose),
                p_sponsor_principal_id,
                'pending',
                p_operating_mode,
                p_workload_identity_id,
                v_actor_id,
                'agent_provisioning',
                btrim(p_provenance_reference)
            );
            RETURN 1;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.provision_integration_state(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority record;
            v_existing request_engine.principals%ROWTYPE;
            v_existing_binding record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.replace_agent_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_profile_status text;
            v_workload_identity_id uuid;
            v_current_revision bigint;
            v_capability text;
            v_plane text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager(
                'agent.manage_authority'
            );
            SELECT status, workload_identity_id
              INTO v_profile_status, v_workload_identity_id
              FROM request_engine.agent_profiles
             WHERE principal_id = p_principal_id
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent profile not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_profile_status NOT IN ('pending', 'active') THEN
                RAISE EXCEPTION 'Suspended or revoked agents cannot receive authority'
                    USING ERRCODE = '55000';
            END IF;
            IF p_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Agent authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id
             FOR UPDATE;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Agent authority revision is stale'
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
                RAISE EXCEPTION 'Desired agent authority is invalid'
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
                        'Desired authority exceeds the agent operational ceiling'
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
                        'agent_authority_management',
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.replace_integration_authority_state(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_principal record;
            v_active boolean;
            v_current_revision bigint;
            v_capability text;
            v_plane text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_target_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_current_revision bigint;
            v_capability text;
            v_plane text;
            v_target_is_controller boolean;
            v_desired_is_controller boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_authority'
            );
            SELECT membership.principal_id
              INTO v_target_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.id = p_membership_id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active Staff membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = v_target_id
             FOR UPDATE;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Staff authority revision is stale'
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
                RAISE EXCEPTION 'Desired Staff authority is invalid'
                    USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                SELECT authority_plane INTO v_plane
                  FROM request_engine.principal_authority_grants
                 WHERE organization_id = v_org_id
                   AND principal_id = v_actor_id
                   AND capability_key = v_capability
                   AND status = 'active'
                   AND delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane = 'platform' THEN
                    RAISE EXCEPTION 'Desired authority exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            SELECT (
                SELECT count(DISTINCT capability_key) = 3
                  FROM request_engine.principal_authority_grants
                 WHERE principal_id = v_target_id
                   AND status = 'active'
                   AND capability_key IN (
                       'staff.manage_membership',
                       'staff.manage_authority',
                       'identity.bind'
                   )
            ) INTO v_target_is_controller;
            SELECT (
                SELECT count(DISTINCT cap) = 3
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
                 WHERE cap IN (
                     'staff.manage_membership',
                     'staff.manage_authority',
                     'identity.bind'
                 )
            ) INTO v_desired_is_controller;
            IF v_target_is_controller AND NOT v_desired_is_controller THEN
                PERFORM request_engine.assert_other_tenant_controller(v_target_id);
            END IF;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE organization_id = v_org_id
               AND principal_id = v_target_id
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
                     WHERE principal_id = v_target_id
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    SELECT authority_plane INTO v_plane
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = v_actor_id
                       AND organization_id = v_org_id
                       AND capability_key = v_capability
                       AND status = 'active'
                       AND delegable;
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
                        v_target_id,
                        'tenant',
                        v_plane,
                        v_capability,
                        false,
                        v_actor_id,
                        'authority_management',
                        btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;
            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = v_target_id;
            RETURN v_current_revision;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.set_integration_status_state(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_principal record;
            v_active boolean;
            v_binding_status text;
            v_workload_identity_id uuid;
            v_current_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.transition_agent_profile(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_profile request_engine.agent_profiles%ROWTYPE;
            v_new_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_target_status = 'active' THEN
                v_actor_id := request_engine.assert_staff_manager('agent.provision');
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                v_actor_id := request_engine.assert_staff_manager('agent.suspend');
            ELSE
                RAISE EXCEPTION 'Unsupported agent profile target status'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_profile
              FROM request_engine.agent_profiles
             WHERE principal_id = p_principal_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent profile not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_profile.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Agent self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF v_profile.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Agent profile revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT (
                (v_profile.status = 'pending'
                    AND p_target_status IN ('active', 'revoked'))
                OR (v_profile.status = 'active'
                    AND p_target_status IN ('suspended', 'revoked'))
                OR (v_profile.status = 'suspended'
                    AND p_target_status IN ('active', 'revoked'))
            ) THEN
                RAISE EXCEPTION 'Invalid agent profile state transition'
                    USING ERRCODE = '55000';
            END IF;
            v_new_revision := v_profile.revision + 1;

            IF p_target_status = 'active' THEN
                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = v_profile.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE principal_id = v_profile.principal_id
                   AND subject_id = v_profile.workload_identity_id::text
                   AND status <> 'revoked';
            ELSIF p_target_status = 'suspended' THEN
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_profile.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended',
                       revision = revision + 1
                 WHERE principal_id = v_profile.principal_id
                   AND subject_id = v_profile.workload_identity_id::text
                   AND status <> 'revoked';
            ELSE
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_profile.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE principal_id = v_profile.principal_id
                   AND subject_id = v_profile.workload_identity_id::text
                   AND status <> 'revoked';
                UPDATE request_engine.workload_credentials
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE workload_identity_id = v_profile.workload_identity_id
                   AND status = 'active';
                UPDATE request_engine.workload_identities
                   SET status = 'disabled',
                       revision = revision + 1,
                       disabled_at = clock_timestamp()
                 WHERE id = v_profile.workload_identity_id
                   AND status = 'active';
            END IF;

            UPDATE request_engine.agent_profiles
               SET status = p_target_status,
                   revision = v_new_revision,
                   suspended_at = CASE
                       WHEN p_target_status = 'suspended'
                       THEN clock_timestamp()
                       ELSE suspended_at
                   END,
                   revoked_at = CASE
                       WHEN p_target_status = 'revoked'
                       THEN clock_timestamp()
                       ELSE NULL
                   END
             WHERE principal_id = p_principal_id;
            RETURN v_new_revision;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_membership request_engine.staff_memberships%ROWTYPE;
            v_native_identity_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_membership'
            );
            SELECT * INTO v_membership
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id
               AND organization_id = v_org_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Staff membership not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_membership.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff membership self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'A positive Staff membership revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF v_membership.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Staff membership revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_provenance_reference IS NULL OR length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            IF p_target_status = 'active' THEN
                IF v_membership.status NOT IN ('invited', 'suspended') THEN
                    RAISE EXCEPTION 'Staff membership cannot be activated'
                        USING ERRCODE = '55000';
                END IF;
                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = v_membership.principal_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE id = v_membership.identity_binding_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.staff_memberships
                   SET status = 'active',
                       revision = revision + 1,
                       activated_at = COALESCE(activated_at, clock_timestamp()),
                       suspended_at = NULL
                 WHERE id = p_membership_id
                   AND organization_id = v_org_id;
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                IF (p_target_status = 'suspended' AND v_membership.status <> 'active')
                   OR (p_target_status = 'revoked'
                       AND v_membership.status NOT IN ('invited', 'active', 'suspended')) THEN
                    RAISE EXCEPTION 'Staff membership cannot make this terminal transition'
                        USING ERRCODE = '55000';
                END IF;
                IF (
                    SELECT count(DISTINCT capability_key)
                      FROM request_engine.principal_authority_grants
                     WHERE organization_id = v_org_id
                       AND principal_id = v_membership.principal_id
                       AND status = 'active'
                       AND capability_key IN (
                           'staff.manage_membership',
                           'staff.manage_authority',
                           'identity.bind'
                       )
                ) = 3 THEN
                    PERFORM request_engine.assert_other_tenant_controller(
                        v_membership.principal_id
                    );
                END IF;
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_membership.principal_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.identity_bindings
                   SET status = p_target_status,
                       revision = revision + 1,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = v_membership.identity_binding_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.staff_memberships
                   SET status = p_target_status,
                       revision = revision + 1,
                       suspended_at = CASE
                           WHEN p_target_status = 'suspended'
                           THEN clock_timestamp()
                           ELSE suspended_at
                       END,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = p_membership_id
                   AND organization_id = v_org_id;

                SELECT binding.subject_id::uuid INTO v_native_identity_id
                  FROM request_engine.identity_bindings AS binding
                  JOIN request_engine.identity_authorities AS authority
                    ON authority.id = binding.identity_authority_id
                 WHERE binding.id = v_membership.identity_binding_id
                   AND binding.organization_id = v_org_id
                   AND authority.kind = 'native';
                IF v_native_identity_id IS NOT NULL THEN
                    PERFORM request_auth.revoke_native_sessions(
                        v_native_identity_id,
                        'staff_' || p_target_status
                    );
                END IF;
            ELSE
                RAISE EXCEPTION 'Unsupported Staff membership target status'
                    USING ERRCODE = '22023';
            END IF;
            RETURN p_expected_revision + 1;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.provision_integration(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := 'integration.provision';
            BEGIN
                PERFORM request_engine.acquire_identity_topology_share();
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                
                IF EXISTS (SELECT 1 FROM request_engine.principals WHERE id = p_principal_id)
                THEN
                    RAISE EXCEPTION 'Provisioning identifier already exists'
                        USING ERRCODE = '23505';
                END IF;
            
                IF 'provision' <> 'provision' THEN
                    SELECT authority_revision INTO v_before
                      FROM request_engine.principals
                     WHERE id = p_principal_id
                       AND organization_id = request_engine.current_organization_id()
                       AND principal_kind = 'integration' AND principal_plane = 'tenant'
                     FOR UPDATE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Integration Principal not found' USING ERRCODE = 'P0002';
                    END IF;
                END IF;
                v_revision := request_engine.provision_integration_state(p_principal_id, p_binding_id, p_workload_identity_id, p_credential_id, p_identity_authority_id, p_token_digest, p_token_fingerprint, p_credential_expires_at, p_provenance_reference);
                IF 'provision' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, 'provision', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.replace_integration_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := 'integration.manage_authority';
            BEGIN
                PERFORM request_engine.acquire_identity_topology_share();
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                
                IF p_expected_authority_revision IS NULL OR p_expected_authority_revision < 1
                   OR p_desired_capabilities IS NULL
                   OR array_position(p_desired_capabilities, NULL) IS NOT NULL
                   OR cardinality(p_desired_capabilities) > 128 THEN
                    RAISE EXCEPTION 'Invalid integration authority input'
                        USING ERRCODE = '22023';
                END IF;
            
                IF 'authority_replace' <> 'provision' THEN
                    SELECT authority_revision INTO v_before
                      FROM request_engine.principals
                     WHERE id = p_principal_id
                       AND organization_id = request_engine.current_organization_id()
                       AND principal_kind = 'integration' AND principal_plane = 'tenant'
                     FOR UPDATE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Integration Principal not found' USING ERRCODE = 'P0002';
                    END IF;
                END IF;
                v_revision := request_engine.replace_integration_authority_state(p_principal_id, p_expected_authority_revision, p_desired_capabilities, p_provenance_reference);
                IF 'authority_replace' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, 'authority_replace', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_engine.set_integration_status(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text)
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := CASE WHEN p_target_status = 'active' THEN 'integration.provision' ELSE 'integration.suspend' END;
            BEGIN
                PERFORM request_engine.acquire_identity_topology_share();
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                
                IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                    RAISE EXCEPTION 'Invalid integration revision' USING ERRCODE = '22023';
                END IF;
            
                IF 'status_transition' <> 'provision' THEN
                    SELECT authority_revision INTO v_before
                      FROM request_engine.principals
                     WHERE id = p_principal_id
                       AND organization_id = request_engine.current_organization_id()
                       AND principal_kind = 'integration' AND principal_plane = 'tenant'
                     FOR UPDATE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Integration Principal not found' USING ERRCODE = 'P0002';
                    END IF;
                END IF;
                v_revision := request_engine.set_integration_status_state(p_principal_id, p_expected_revision, p_target_status, p_provenance_reference);
                IF 'status_transition' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, 'status_transition', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_platform.provision_native_organization_root(p_organization_id uuid, p_organization_key text, p_display_name text, p_organization_party_id uuid, p_controller_principal_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text)
 RETURNS TABLE(organization_id uuid, organization_party_id uuid, controller_principal_id uuid, controller_binding_id uuid)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_creator_id uuid;
            v_expected_revision bigint;
            v_current_revision bigint;
            v_creator_kind text;
            v_can_provision boolean;
            v_binding_id uuid := pg_catalog.gen_random_uuid();
            v_existing record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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

            SELECT principal.principal_kind, principal.authority_revision
              INTO v_creator_kind, v_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_creator_id
               AND principal.principal_plane = 'platform'
               AND principal.organization_id IS NULL
               AND principal.active
             FOR UPDATE OF principal;
            IF NOT FOUND OR v_creator_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal is not provision-capable'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> v_expected_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale' USING ERRCODE = '40001';
            END IF;
            SELECT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_creator_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.capability_key = 'organization.provision'
                   AND grant_row.status = 'active'
            ) INTO v_can_provision;
            IF NOT v_can_provision THEN
                RAISE EXCEPTION 'Current Platform Principal lacks organization.provision'
                    USING ERRCODE = '42501';
            END IF;

            SELECT root_fact.organization_id,
                   root_fact.organization_party_id,
                   root_fact.controller_principal_id,
                   root_fact.controller_binding_id,
                   root_fact.provisioned_by_principal_id,
                   root_fact.provenance_reference
              INTO v_existing
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = p_organization_id;
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

            IF NOT request_auth.lock_credentialed_native_identity(
                p_identity_authority_id,
                p_native_identity_id
            ) THEN
                RAISE EXCEPTION
                    'First tenant controller requires an active credentialed Native identity'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.organizations (id, organization_key, display_name)
            VALUES (p_organization_id, btrim(p_organization_key), btrim(p_display_name));
            INSERT INTO request_engine.parties (
                id, organization_id, party_kind, display_name
            ) VALUES (
                p_organization_party_id, p_organization_id, 'organization',
                btrim(p_display_name)
            );
            INSERT INTO request_engine.party_identity_revisions (
                organization_id, party_id, revision, change_kind, display_name, active, state
            ) VALUES (
                p_organization_id, p_organization_party_id, 1, 'registered',
                btrim(p_display_name), true,
                pg_catalog.jsonb_build_object(
                    'display_name', btrim(p_display_name),
                    'active', true,
                    'contact_points', '[]'::jsonb,
                    'documents', '[]'::jsonb
                )
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
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_platform.provision_native_tenant_provisioner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_creator_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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
        END $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_platform.provision_tenant_provisioner(p_new_principal_id uuid, p_external_subject text, p_provenance_reference text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_creator_id uuid;
            v_expected_revision bigint;
            v_current_revision bigint;
            v_creator_kind text;
            v_has_command boolean;
            v_can_delegate_org boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
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
            IF length(btrim(p_external_subject)) = 0
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Provisioning subject and provenance must be nonblank'
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
                          AND capability_key = 'platform.tenant_provisioner.provision'
                          AND status = 'active'
                   ),
                   EXISTS (
                       SELECT 1 FROM request_engine.principal_authority_grants
                        WHERE principal_id = v_creator_id
                          AND principal_plane = 'platform'
                          AND authority_plane = 'platform'
                          AND capability_key = 'organization.provision'
                          AND delegable
                          AND status = 'active'
                   )
              INTO v_has_command, v_can_delegate_org;
            IF NOT v_has_command OR NOT v_can_delegate_org THEN
                RAISE EXCEPTION 'Current Platform Principal lacks bounded provisioning authority'
                    USING ERRCODE = '42501';
            END IF;

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_new_principal_id, 'platform', 'human', btrim(p_external_subject)
            );
            INSERT INTO request_engine.principal_authority_grants (
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_new_principal_id,
                'platform',
                'platform',
                'organization.provision',
                false,
                v_creator_id,
                'provisioning',
                btrim(p_provenance_reference)
            );
            RETURN p_new_principal_id;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_platform.transition_native_platform_provisioner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text)
 RETURNS TABLE(fact_id uuid, principal_id uuid, action text, authority_revision bigint, binding_id uuid, binding_status text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_target_kind text;
            v_target_active boolean;
            v_revision_before bigint;
            v_revision_after bigint;
            v_binding_id uuid;
            v_binding_status text;
            v_binding_authority uuid;
            v_binding_subject text;
            v_subject_uuid uuid;
            v_authority_kind text;
            v_replay record;
            v_fact_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_principal_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'Target provisioner and expected revision are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_action IS NULL OR p_action NOT IN ('suspend', 'reactivate', 'revoke') THEN
                RAISE EXCEPTION 'Unknown platform provisioner lifecycle action'
                    USING ERRCODE = '22023';
            END IF;
            IF p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR (p_external_case_reference IS NOT NULL
                   AND length(btrim(p_external_case_reference)) NOT BETWEEN 1 AND 200)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Lifecycle reason, case reference or digests are invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_actor_method := NULLIF(current_setting(
                    'request_engine.authentication_method', true
                ), '');
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            -- Platform-plane serialization root: every lifecycle command locks the
            -- platform Principal set in id order before bindings, grants or facts.
            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot manage provisioners'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS actor_grant
                 WHERE actor_grant.principal_id = v_actor_id
                   AND actor_grant.principal_plane = 'platform'
                   AND actor_grant.authority_plane = 'platform'
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = 'platform.provisioner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks provisioner lifecycle authority'
                    USING ERRCODE = '42501';
            END IF;

            -- Replay is evaluated only after revalidating current actor authority.
            SELECT fact.id, fact.principal_id, fact.action, fact.intent_digest,
                   fact.revision_after
              INTO v_replay
              FROM request_engine.platform_authority_lifecycle_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.provisioner.manage_lifecycle'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.principal_id <> p_principal_id
                   OR v_replay.action <> p_action
                   OR v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another lifecycle intent'
                        USING ERRCODE = '23505';
                END IF;
                SELECT candidate.id, candidate.status
                  INTO v_binding_id, v_binding_status
                  FROM request_engine.identity_bindings AS candidate
                 WHERE candidate.principal_id = p_principal_id
                   AND candidate.principal_plane = 'platform'
                   AND candidate.organization_id IS NULL
                 ORDER BY (candidate.status <> 'revoked') DESC, candidate.id
                 LIMIT 1;
                RETURN QUERY SELECT v_replay.id, v_replay.principal_id, v_replay.action,
                                    v_replay.revision_after, v_binding_id,
                                    v_binding_status;
                RETURN;
            END IF;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_target_kind, v_target_active, v_revision_before
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR v_target_kind <> 'human' OR NOT v_target_active THEN
                RAISE EXCEPTION 'Target is not an active platform provisioner'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.provenance_kind = 'provisioning'
            ) THEN
                RAISE EXCEPTION 'Target is not a platform provisioner'
                    USING ERRCODE = '22023';
            END IF;
            IF v_revision_before <> p_expected_revision THEN
                RAISE EXCEPTION 'Target authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT binding.id, binding.status, binding.identity_authority_id,
                   binding.subject_id
              INTO v_binding_id, v_binding_status, v_binding_authority,
                   v_binding_subject
              FROM request_engine.identity_bindings AS binding
             WHERE binding.principal_id = p_principal_id
               AND binding.principal_plane = 'platform'
               AND binding.organization_id IS NULL
               AND binding.status <> 'revoked'
             ORDER BY binding.id
             LIMIT 1
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform provisioner has no live identity binding'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action = 'suspend' AND v_binding_status <> 'active' THEN
                RAISE EXCEPTION 'Only an active provisioner can be suspended'
                    USING ERRCODE = '55000';
            ELSIF p_action = 'reactivate' AND v_binding_status <> 'suspended' THEN
                RAISE EXCEPTION 'Only a suspended provisioner can be reactivated'
                    USING ERRCODE = '55000';
            ELSIF p_action = 'revoke'
               AND v_binding_status NOT IN ('active', 'suspended') THEN
                RAISE EXCEPTION 'Provisioner is already terminally revoked'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action IN ('suspend', 'revoke')
               AND request_platform.principal_is_effective_platform_controller(
                       p_principal_id) THEN
                PERFORM request_platform.assert_other_platform_controller(p_principal_id);
            END IF;

            IF p_action = 'reactivate' THEN
                SELECT authority.kind
                  INTO v_authority_kind
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.id = v_binding_authority;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Provisioner identity authority is unavailable'
                        USING ERRCODE = '23514';
                END IF;
                IF v_authority_kind = 'native' THEN
                    BEGIN
                        v_subject_uuid := v_binding_subject::uuid;
                    EXCEPTION WHEN invalid_text_representation THEN
                        RAISE EXCEPTION
                            'Provisioner native binding subject is not addressable'
                            USING ERRCODE = '23514';
                    END;
                    IF NOT request_auth.lock_credentialed_native_identity(
                        v_binding_authority, v_subject_uuid
                    ) THEN
                        RAISE EXCEPTION
                            'Reactivate requires an active credentialed Native identity'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
            END IF;

            IF p_action = 'suspend' THEN
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended', revision = revision + 1
                 WHERE id = v_binding_id;
            ELSIF p_action = 'reactivate' THEN
                UPDATE request_engine.identity_bindings
                   SET status = 'active', revision = revision + 1
                 WHERE id = v_binding_id;
            ELSE
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked', revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE id = v_binding_id;
                UPDATE request_engine.principal_authority_grants AS grant_row
                   SET status = 'revoked', revision = grant_row.revision + 1,
                       revoked_at = clock_timestamp(),
                       revoked_by_principal_id = v_actor_id
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.status = 'active';
            END IF;

            SELECT principal.authority_revision
              INTO v_revision_after
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id;

            v_fact_id := gen_random_uuid();
            INSERT INTO request_engine.platform_authority_lifecycle_facts (
                id, principal_id, action, actor_principal_id,
                actor_authentication_method, reason_code, external_case_reference,
                revision_before, revision_after, correlation_id, capability_key,
                idempotency_key_digest, intent_digest
            ) VALUES (
                v_fact_id, p_principal_id, p_action, v_actor_id,
                v_actor_method, btrim(p_reason_code),
                NULLIF(btrim(p_external_case_reference), ''),
                v_revision_before, v_revision_after, v_correlation_id,
                'platform.provisioner.manage_lifecycle',
                p_idempotency_key_digest, p_intent_digest
            );

            SELECT binding.status
              INTO v_binding_status
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_binding_id;

            RETURN QUERY SELECT v_fact_id, p_principal_id, p_action, v_revision_after,
                                v_binding_id, v_binding_status;
        END
        $function$;
        """
    )
    op.execute(
        r"""
CREATE OR REPLACE FUNCTION request_platform.establish_root(p_intent_id uuid, p_token_digest bytea, p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_password_verifier text, p_principal_id uuid, p_binding_id uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
AS $function$
        DECLARE
            v_provenance text;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();
            -- Different intents must not race to create two initial Platform roots.
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476356);

            SELECT provenance_reference
              INTO v_provenance
              FROM request_engine.platform_bootstrap_intents
             WHERE id = p_intent_id
               AND token_digest = p_token_digest
               AND permitted_action = 'platform.root.establish'
               AND status = 'pending'
               AND expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1 FROM request_engine.principals
             WHERE principal_plane = 'platform'
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Platform root already exists' USING ERRCODE = '55000';
            END IF;

            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native'
               OR v_authority_status <> 'active' THEN
                RAISE EXCEPTION 'Platform root requires an active Native identity authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (p_native_identity_id, p_identity_authority_id, p_login_handle);
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (p_credential_id, p_native_identity_id, p_password_verifier);
            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id,
                'platform',
                'human',
                'native-bootstrap:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                p_binding_id,
                p_principal_id,
                'platform',
                p_identity_authority_id,
                p_native_identity_id::text,
                'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT p_principal_id,
                   'platform',
                   'platform',
                   capability_key,
                   delegable,
                   'trust_bootstrap',
                   'platform-bootstrap:' || p_intent_id::text || ':' || v_provenance
              FROM (VALUES
                  ('platform.principal.provision', true),
                  ('platform.tenant_provisioner.provision', true),
                  ('organization.provision', true),
                  ('platform.identity.recover', false),
                  ('platform.provisioner.read', false),
                  ('platform.provisioner.manage_lifecycle', false)
              ) AS initial_grant(capability_key, delegable);

            UPDATE request_engine.platform_bootstrap_intents
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_intent_id;
            RETURN p_principal_id;
        END
        $function$;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove the identity topology gate; roll forward")
