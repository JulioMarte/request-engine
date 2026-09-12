"""Add first-class Agent Principal governance and workload credential issuance.

Revision ID: 0024_agent_governance
Revises: 0023_workload_auth
Create Date: 2026-09-08

Agent Principals are first-class security actors. Their governance profile,
workload identity, credential, and identity binding are created atomically by
RE-owned SECURITY DEFINER functions. Standing agent authority is bounded by the
provisioner's current delegable authority restricted to the operational plane:
platform, tenant-control and identity authority can never be assigned to an
AGENT Principal. Suspension stops authorization immediately by deactivating the
Principal and suspending its binding; revocation additionally destroys the
workload credential and disables the workload identity.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0024_agent_governance"
down_revision: str | Sequence[str] | None = "0023_workload_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE request_engine.agent_profiles (
            principal_id uuid NOT NULL,
            organization_id uuid NOT NULL
                REFERENCES request_engine.organizations(id),
            display_name text NOT NULL,
            purpose text NOT NULL,
            sponsor_principal_id uuid NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            operating_mode text NOT NULL DEFAULT 'autonomous',
            workload_identity_id uuid NOT NULL
                REFERENCES request_engine.workload_identities(id),
            established_by_principal_id uuid NOT NULL,
            provenance_kind text NOT NULL DEFAULT 'agent_provisioning',
            provenance_reference text NOT NULL,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            suspended_at timestamptz,
            revoked_at timestamptz,
            PRIMARY KEY (principal_id),
            FOREIGN KEY (organization_id, principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            FOREIGN KEY (organization_id, sponsor_principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            FOREIGN KEY (organization_id, established_by_principal_id)
                REFERENCES request_engine.principals(organization_id, id),
            CONSTRAINT agent_profiles_display_name_check
                CHECK (length(btrim(display_name)) BETWEEN 1 AND 200),
            CONSTRAINT agent_profiles_purpose_check
                CHECK (length(btrim(purpose)) BETWEEN 1 AND 2000),
            CONSTRAINT agent_profiles_status_check
                CHECK (status IN ('pending', 'active', 'suspended', 'revoked')),
            CONSTRAINT agent_profiles_operating_mode_check
                CHECK (operating_mode IN ('autonomous', 'assisted')),
            CONSTRAINT agent_profiles_provenance_kind_check
                CHECK (provenance_kind = 'agent_provisioning'),
            CONSTRAINT agent_profiles_provenance_reference_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT agent_profiles_revision_check CHECK (revision > 0),
            CONSTRAINT agent_profiles_state_time_check CHECK (
                (status = 'pending'
                    AND suspended_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'active'
                    AND revoked_at IS NULL)
                OR (status = 'suspended'
                    AND suspended_at IS NOT NULL
                    AND revoked_at IS NULL)
                OR (status = 'revoked'
                    AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX agent_profiles_workload_identity_uq
            ON request_engine.agent_profiles (workload_identity_id);
        CREATE INDEX agent_profiles_organization_status_idx
            ON request_engine.agent_profiles
            (organization_id, status, principal_id);
        ALTER TABLE request_engine.agent_profiles
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.agent_profiles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.agent_profiles FORCE ROW LEVEL SECURITY;
        CREATE POLICY agent_profiles_tenant_isolation
            ON request_engine.agent_profiles
            USING (
                organization_id = request_engine.current_organization_id()
            )
            WITH CHECK (
                organization_id = request_engine.current_organization_id()
            );
        REVOKE ALL ON request_engine.agent_profiles FROM PUBLIC;
        GRANT SELECT ON request_engine.agent_profiles TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_agent_profile()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_principal record;
            v_sponsor record;
            v_workload_kind text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Agent profiles are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.principal_id,
                    NEW.organization_id,
                    NEW.display_name,
                    NEW.purpose,
                    NEW.sponsor_principal_id,
                    NEW.operating_mode,
                    NEW.workload_identity_id,
                    NEW.established_by_principal_id,
                    NEW.provenance_kind,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.principal_id,
                    OLD.organization_id,
                    OLD.display_name,
                    OLD.purpose,
                    OLD.sponsor_principal_id,
                    OLD.operating_mode,
                    OLD.workload_identity_id,
                    OLD.established_by_principal_id,
                    OLD.provenance_kind,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Agent profile identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status = NEW.status THEN
                    RAISE EXCEPTION 'Invalid Agent profile update'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       (OLD.status = 'pending'
                           AND NEW.status IN ('active', 'revoked'))
                       OR (OLD.status = 'active'
                           AND NEW.status IN ('suspended', 'revoked'))
                       OR (OLD.status = 'suspended'
                           AND NEW.status IN ('active', 'revoked'))
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Agent profile state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT principal_plane, principal_kind, organization_id, active
              INTO v_principal
              FROM request_engine.principals
             WHERE id = NEW.principal_id;
            IF NOT FOUND
               OR v_principal.principal_plane <> 'tenant'
               OR v_principal.principal_kind <> 'agent'
               OR v_principal.organization_id IS DISTINCT FROM NEW.organization_id
            THEN
                RAISE EXCEPTION 'Agent profile requires a tenant AGENT Principal'
                    USING ERRCODE = '23514';
            END IF;
            IF (
                NEW.status = 'active' AND NOT v_principal.active
            ) OR (
                NEW.status IN ('suspended', 'revoked') AND v_principal.active
            ) THEN
                RAISE EXCEPTION 'Agent profile status contradicts Principal state'
                    USING ERRCODE = '23514';
            END IF;

            SELECT principal_plane, principal_kind, organization_id, active
              INTO v_sponsor
              FROM request_engine.principals
             WHERE id = NEW.sponsor_principal_id;
            IF NOT FOUND
               OR v_sponsor.principal_plane <> 'tenant'
               OR v_sponsor.principal_kind <> 'human'
               OR v_sponsor.organization_id IS DISTINCT FROM NEW.organization_id
               OR NOT v_sponsor.active
               OR NEW.sponsor_principal_id = NEW.principal_id
            THEN
                RAISE EXCEPTION 'Agent sponsor must be an active tenant HUMAN Principal'
                    USING ERRCODE = '23514';
            END IF;

            SELECT workload_kind
              INTO v_workload_kind
              FROM request_engine.workload_identities
             WHERE id = NEW.workload_identity_id;
            IF NOT FOUND OR v_workload_kind <> 'agent' THEN
                RAISE EXCEPTION 'Agent profile requires an agent workload identity'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_agent_profile()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_agent_profile() FROM PUBLIC;
        CREATE TRIGGER agent_profiles_guard
            BEFORE INSERT OR UPDATE OR DELETE
            ON request_engine.agent_profiles
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_agent_profile();
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.provision_agent(
            p_principal_id uuid,
            p_binding_id uuid,
            p_workload_identity_id uuid,
            p_credential_id uuid,
            p_identity_authority_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_credential_expires_at timestamptz,
            p_display_name text,
            p_purpose text,
            p_sponsor_principal_id uuid,
            p_operating_mode text,
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
            v_existing request_engine.agent_profiles%ROWTYPE;
        BEGIN
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
        $$;
        ALTER FUNCTION request_engine.provision_agent(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz,
            text, text, uuid, text, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.provision_agent(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz,
            text, text, uuid, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.provision_agent(
            uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz,
            text, text, uuid, text, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.replace_agent_authority(
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
            v_profile_status text;
            v_workload_identity_id uuid;
            v_current_revision bigint;
            v_capability text;
            v_plane text;
        BEGIN
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
        $$;
        ALTER FUNCTION request_engine.replace_agent_authority(
            uuid, bigint, text[], text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.replace_agent_authority(
            uuid, bigint, text[], text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.replace_agent_authority(
            uuid, bigint, text[], text
        ) TO request_engine_app;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.transition_agent_profile(
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
            v_profile request_engine.agent_profiles%ROWTYPE;
            v_new_revision bigint;
        BEGIN
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
        $$;
        ALTER FUNCTION request_engine.transition_agent_profile(
            uuid, bigint, text, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.transition_agent_profile(
            uuid, bigint, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.transition_agent_profile(
            uuid, bigint, text, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION request_engine.transition_agent_profile(uuid, bigint, text, text)")
    op.execute("DROP FUNCTION request_engine.replace_agent_authority(uuid, bigint, text[], text)")
    op.execute(
        "DROP FUNCTION request_engine.provision_agent("
        "uuid, uuid, uuid, uuid, uuid, bytea, text, timestamptz, "
        "text, text, uuid, text, text)"
    )
    op.execute("DROP TRIGGER agent_profiles_guard ON request_engine.agent_profiles")
    op.execute("DROP FUNCTION request_engine.guard_agent_profile()")
    op.execute("DROP TABLE request_engine.agent_profiles CASCADE")
