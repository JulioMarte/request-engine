"""Add tenant staff membership lifecycle and bounded authority replacement.

Revision ID: 0019_staff_membership
Revises: 0018_provisioning_facts_rls
Create Date: 2026-09-08

Membership records administrative belonging only. Principal authority remains
owned by principal_authority_grants and Representations. Tenant-control writers
are RE-owned, revisioned, fail closed on stale state, and cannot amplify beyond
the caller's explicitly delegable standing authority.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019_staff_membership"
down_revision: str | Sequence[str] | None = "0018_provisioning_facts_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MINIMUM_CONTROL = (
    "staff.manage_membership",
    "staff.manage_authority",
    "identity.bind",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.staff_memberships (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL
                REFERENCES request_engine.organizations(id),
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            identity_binding_id uuid NOT NULL
                REFERENCES request_engine.identity_bindings(id),
            authority_anchor_party_id uuid NOT NULL
                REFERENCES request_engine.parties(id),
            status text NOT NULL DEFAULT 'invited',
            revision bigint NOT NULL DEFAULT 1,
            established_by_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            provenance_kind text NOT NULL,
            provenance_reference text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            activated_at timestamptz,
            suspended_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT staff_memberships_status_check
                CHECK (status IN ('invited', 'active', 'suspended', 'revoked')),
            CONSTRAINT staff_memberships_revision_check CHECK (revision > 0),
            CONSTRAINT staff_memberships_provenance_kind_check
                CHECK (provenance_kind IN ('root_provisioning', 'staff_invitation')),
            CONSTRAINT staff_memberships_provenance_reference_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT staff_memberships_state_time_check CHECK (
                (status = 'invited'
                    AND activated_at IS NULL
                    AND suspended_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'active'
                    AND activated_at IS NOT NULL
                    AND suspended_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'suspended'
                    AND activated_at IS NOT NULL
                    AND suspended_at IS NOT NULL
                    AND revoked_at IS NULL)
                OR (status = 'revoked'
                    AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX staff_memberships_principal_live_uq
            ON request_engine.staff_memberships (principal_id)
            WHERE status <> 'revoked';
        CREATE UNIQUE INDEX staff_memberships_binding_live_uq
            ON request_engine.staff_memberships (identity_binding_id)
            WHERE status <> 'revoked';
        CREATE INDEX staff_memberships_tenant_status_idx
            ON request_engine.staff_memberships
            (organization_id, status, principal_id);
        ALTER TABLE request_engine.staff_memberships
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.staff_memberships ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.staff_memberships FORCE ROW LEVEL SECURITY;
        CREATE POLICY staff_memberships_tenant_isolation
            ON request_engine.staff_memberships
            USING (
                organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.staff_memberships FROM PUBLIC;
        GRANT SELECT ON request_engine.staff_memberships TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_staff_membership()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_principal_org uuid;
            v_principal_plane text;
            v_principal_kind text;
            v_binding_org uuid;
            v_binding_principal uuid;
            v_anchor_org uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Staff memberships are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.id,
                    NEW.organization_id,
                    NEW.principal_id,
                    NEW.identity_binding_id,
                    NEW.authority_anchor_party_id,
                    NEW.established_by_principal_id,
                    NEW.provenance_kind,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.organization_id,
                    OLD.principal_id,
                    OLD.identity_binding_id,
                    OLD.authority_anchor_party_id,
                    OLD.established_by_principal_id,
                    OLD.provenance_kind,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Staff membership identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       (OLD.status = 'invited'
                           AND NEW.status IN ('active', 'revoked'))
                       OR (OLD.status = 'active'
                           AND NEW.status IN ('suspended', 'revoked'))
                       OR (OLD.status = 'suspended'
                           AND NEW.status IN ('active', 'revoked'))
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Staff membership state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT organization_id, principal_plane, principal_kind
              INTO v_principal_org, v_principal_plane, v_principal_kind
              FROM request_engine.principals
             WHERE id = NEW.principal_id;
            IF NOT FOUND
               OR v_principal_org IS DISTINCT FROM NEW.organization_id
               OR v_principal_plane <> 'tenant'
               OR v_principal_kind <> 'human'
            THEN
                RAISE EXCEPTION 'Staff membership requires a tenant HUMAN Principal'
                    USING ERRCODE = '23514';
            END IF;

            SELECT organization_id, principal_id
              INTO v_binding_org, v_binding_principal
              FROM request_engine.identity_bindings
             WHERE id = NEW.identity_binding_id;
            IF NOT FOUND
               OR v_binding_org IS DISTINCT FROM NEW.organization_id
               OR v_binding_principal <> NEW.principal_id
            THEN
                RAISE EXCEPTION 'Staff membership binding scope is invalid'
                    USING ERRCODE = '23514';
            END IF;

            SELECT organization_id INTO v_anchor_org
              FROM request_engine.parties
             WHERE id = NEW.authority_anchor_party_id;
            IF NOT FOUND OR v_anchor_org <> NEW.organization_id THEN
                RAISE EXCEPTION 'Staff membership authority anchor is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_staff_membership()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_staff_membership() FROM PUBLIC;
        CREATE TRIGGER staff_memberships_guard
            BEFORE INSERT OR UPDATE OR DELETE
            ON request_engine.staff_memberships
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_staff_membership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.seed_root_staff_membership()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'request_auth'
        AS $$
        DECLARE
            v_grant record;
        BEGIN
            PERFORM set_config(
                'request_engine.organization_id',
                NEW.organization_id::text,
                true
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
                provenance_reference,
                activated_at
            ) VALUES (
                gen_random_uuid(),
                NEW.organization_id,
                NEW.controller_principal_id,
                NEW.controller_binding_id,
                NEW.organization_party_id,
                'active',
                NEW.provisioned_by_principal_id,
                'root_provisioning',
                NEW.provenance_reference,
                clock_timestamp()
            );

            FOR v_grant IN
                SELECT *
                  FROM request_engine.principal_authority_grants
                 WHERE principal_id = NEW.controller_principal_id
                   AND organization_id = NEW.organization_id
                   AND authority_plane = 'tenant_control'
                   AND status = 'active'
                   AND NOT delegable
                 FOR UPDATE
            LOOP
                UPDATE request_engine.principal_authority_grants
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp(),
                       revoked_by_principal_id = NEW.provisioned_by_principal_id
                 WHERE id = v_grant.id;
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
                    NEW.organization_id,
                    NEW.controller_principal_id,
                    'tenant',
                    v_grant.authority_plane,
                    v_grant.capability_key,
                    true,
                    v_grant.granted_by_principal_id,
                    'provisioning',
                    NEW.provenance_reference || ':root-delegable'
                );
            END LOOP;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.seed_root_staff_membership()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.seed_root_staff_membership() FROM PUBLIC;
        CREATE TRIGGER organization_root_seed_staff_membership
            AFTER INSERT ON request_engine.organization_root_provisioning_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.seed_root_staff_membership();
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.assert_staff_manager(
            p_capability text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid;
        BEGIN
            BEGIN
                v_actor_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_org_id := request_engine.current_organization_id();
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Tenant actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_org_id IS NULL THEN
                RAISE EXCEPTION 'Tenant actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;
            PERFORM 1
              FROM request_engine.principals AS principal
              JOIN request_engine.staff_memberships AS membership
                ON membership.principal_id = principal.id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
              JOIN request_engine.principal_authority_grants AS grant_row
                ON grant_row.principal_id = principal.id
               AND grant_row.organization_id = v_org_id
               AND grant_row.capability_key = p_capability
               AND grant_row.status = 'active'
             WHERE principal.id = v_actor_id
               AND principal.organization_id = v_org_id
               AND principal.principal_plane = 'tenant'
               AND principal.principal_kind = 'human'
               AND principal.active
             FOR SHARE OF principal, membership, grant_row;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current Principal lacks active staff authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN v_actor_id;
        END
        $$;
        ALTER FUNCTION request_engine.assert_staff_manager(text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.assert_staff_manager(text) FROM PUBLIC;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.assert_other_tenant_controller(
            p_excluded_principal_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            PERFORM id
              FROM request_engine.staff_memberships
             WHERE organization_id = v_org_id
               AND status = 'active'
             ORDER BY principal_id
             FOR UPDATE;

            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
               AND membership.principal_id <> p_excluded_principal_id
               AND (
                   SELECT count(DISTINCT grant_row.capability_key)
                     FROM request_engine.principal_authority_grants AS grant_row
                    WHERE grant_row.organization_id = v_org_id
                      AND grant_row.principal_id = membership.principal_id
                      AND grant_row.status = 'active'
                      AND grant_row.capability_key IN (
                          'staff.manage_membership',
                          'staff.manage_authority',
                          'identity.bind'
                      )
               ) = 3
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;
        ALTER FUNCTION request_engine.assert_other_tenant_controller(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.assert_other_tenant_controller(uuid)
            FROM PUBLIC;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.invite_native_staff(
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
        SET search_path TO 'pg_catalog', 'request_engine', 'request_auth'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_existing record;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager('staff.invite');
            IF p_principal_id = v_actor_id
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Invalid staff invitation input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT principal_id, identity_binding_id
              INTO v_existing
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id;
            IF FOUND THEN
                IF v_existing.principal_id <> p_principal_id
                   OR v_existing.identity_binding_id <> p_binding_id
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
                p_authority_anchor_party_id,
                'invited',
                v_actor_id,
                'staff_invitation',
                btrim(p_provenance_reference)
            );
            RETURN p_binding_id;
        END
        $$;
        ALTER FUNCTION request_engine.invite_native_staff(
            uuid, uuid, uuid, uuid, uuid, uuid, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.invite_native_staff(
            uuid, uuid, uuid, uuid, uuid, uuid, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.invite_native_staff(
            uuid, uuid, uuid, uuid, uuid, uuid, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.transition_staff_membership(
            p_membership_id uuid,
            p_expected_revision bigint,
            p_target_status text,
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'request_auth'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_membership request_engine.staff_memberships%ROWTYPE;
            v_native_identity_id uuid;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_membership'
            );
            SELECT * INTO v_membership
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Staff membership not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_membership.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff membership self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF v_membership.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Staff membership revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0 THEN
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
                 WHERE id = v_membership.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE id = v_membership.identity_binding_id;
                UPDATE request_engine.staff_memberships
                   SET status = 'active',
                       revision = revision + 1,
                       activated_at = COALESCE(activated_at, clock_timestamp()),
                       suspended_at = NULL
                 WHERE id = p_membership_id;
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                IF v_membership.status <> 'active' THEN
                    RAISE EXCEPTION 'Only active Staff membership may be ended'
                        USING ERRCODE = '55000';
                END IF;
                IF (
                    SELECT count(DISTINCT capability_key)
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = v_membership.principal_id
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
                 WHERE id = v_membership.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = p_target_status,
                       revision = revision + 1,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = v_membership.identity_binding_id;
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
                 WHERE id = p_membership_id;

                SELECT subject_id::uuid INTO v_native_identity_id
                  FROM request_engine.identity_bindings AS binding
                  JOIN request_engine.identity_authorities AS authority
                    ON authority.id = binding.identity_authority_id
                 WHERE binding.id = v_membership.identity_binding_id
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
        $$;
        ALTER FUNCTION request_engine.transition_staff_membership(
            uuid, bigint, text, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.transition_staff_membership(
            uuid, bigint, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.transition_staff_membership(
            uuid, bigint, text, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.replace_staff_authority(
            p_membership_id uuid,
            p_expected_authority_revision bigint,
            p_desired_capabilities text[],
            p_provenance_reference text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
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
        $$;
        ALTER FUNCTION request_engine.replace_staff_authority(
            uuid, bigint, text[], text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.replace_staff_authority(
            uuid, bigint, text[], text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.replace_staff_authority(
            uuid, bigint, text[], text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_engine.replace_staff_authority(uuid, bigint, text[], text)")
    op.execute("DROP FUNCTION request_engine.transition_staff_membership(uuid, bigint, text, text)")
    op.execute(
        "DROP FUNCTION request_engine.invite_native_staff(uuid, uuid, uuid, uuid, uuid, uuid, text)"
    )
    op.execute("DROP FUNCTION request_engine.assert_other_tenant_controller(uuid)")
    op.execute("DROP FUNCTION request_engine.assert_staff_manager(text)")
    op.execute(
        "DROP TRIGGER organization_root_seed_staff_membership "
        "ON request_engine.organization_root_provisioning_facts"
    )
    op.execute("DROP FUNCTION request_engine.seed_root_staff_membership()")
    op.execute("DROP TABLE request_engine.staff_memberships CASCADE")
    op.execute("DROP FUNCTION request_engine.guard_staff_membership()")
