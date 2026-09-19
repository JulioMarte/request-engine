"""Self-service dual-proof identity linking (plan D2, ADR 0013 D3).

Adds the tenant-scoped self-service linking primitive: a short-TTL intent bound
to the actor, its current binding revision, the selected target authority and a
server nonce digest, plus the command that consumes that intent exactly once to
create a second active binding for the SAME tenant Principal. There is no
generic ``bindings {principal_id, subject_id}`` surface, no administrative
linking and no merge of Principals, Parties, staff or grants.

Both commands acquire the identity-topology gate SHARE and the ordered active
staff-membership root before any specific row, revalidate the actor inside the
transaction, and never trust a body-supplied identity: the confirm command
re-locks the credentialed native identity under the intent's authority and
conflicts when the subject is already live for another Principal.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049_identity_link_self"
down_revision: str | Sequence[str] | None = "0048_native_reauth_freshness"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE TABLE request_engine.identity_link_intents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id uuid NOT NULL
                REFERENCES request_engine.organizations(id),
            actor_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            actor_binding_id uuid NOT NULL
                REFERENCES request_engine.identity_bindings(id),
            target_authority_id uuid NOT NULL
                REFERENCES request_engine.identity_authorities(id),
            actor_binding_revision bigint NOT NULL
                CHECK (actor_binding_revision >= 1),
            nonce_digest text NOT NULL
                CHECK (nonce_digest ~ '^[0-9a-f]{64}$'),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'consumed', 'revoked', 'expired')),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            resulting_binding_id uuid
                REFERENCES request_engine.identity_bindings(id),
            provenance_reference text NOT NULL
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 400),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT identity_link_intents_expiry_check
                CHECK (expires_at > created_at),
            CONSTRAINT identity_link_intents_actor_principal_tenant_fk
                FOREIGN KEY (organization_id, actor_principal_id)
                REFERENCES request_engine.principals (organization_id, id),
            CONSTRAINT identity_link_intents_actor_binding_tenant_fk
                FOREIGN KEY (organization_id, actor_principal_id, actor_binding_id)
                REFERENCES request_engine.identity_bindings
                    (organization_id, principal_id, id),
            CONSTRAINT identity_link_intents_resulting_binding_tenant_fk
                FOREIGN KEY (organization_id, actor_principal_id, resulting_binding_id)
                REFERENCES request_engine.identity_bindings
                    (organization_id, principal_id, id)
        );
        ALTER TABLE request_engine.identity_link_intents
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.identity_link_intents ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.identity_link_intents FORCE ROW LEVEL SECURITY;
        CREATE POLICY identity_link_intents_tenant_isolation
            ON request_engine.identity_link_intents
            USING (organization_id = request_engine.current_organization_id())
            WITH CHECK (organization_id = request_engine.current_organization_id());
        REVOKE ALL ON request_engine.identity_link_intents FROM PUBLIC;
        CREATE UNIQUE INDEX identity_link_intents_nonce_uq
            ON request_engine.identity_link_intents (organization_id, nonce_digest);
        CREATE INDEX identity_link_intents_actor_lookup_idx
            ON request_engine.identity_link_intents
            (actor_principal_id, status, created_at);

        CREATE TABLE request_engine.identity_link_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            actor_principal_id uuid NOT NULL,
            organization_id uuid NOT NULL,
            capability_key text NOT NULL,
            action text NOT NULL,
            intent_id uuid,
            target_authority_id uuid NOT NULL,
            subject_id text,
            binding_id uuid,
            nonce_digest text NOT NULL,
            provenance_reference text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT identity_link_facts_capability_check
                CHECK (capability_key = 'identity.link_self'),
            CONSTRAINT identity_link_facts_action_check
                CHECK (action IN ('intent_created', 'linked', 'conflict'))
        );
        ALTER TABLE request_engine.identity_link_facts
            OWNER TO request_engine_schema_owner;
        ALTER TABLE request_engine.identity_link_facts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE request_engine.identity_link_facts FORCE ROW LEVEL SECURITY;
        CREATE POLICY identity_link_facts_tenant_isolation
            ON request_engine.identity_link_facts
            USING (organization_id = request_engine.current_organization_id())
            WITH CHECK (organization_id = request_engine.current_organization_id());
        REVOKE ALL ON request_engine.identity_link_facts FROM PUBLIC;

        CREATE FUNCTION request_engine.guard_identity_link_intent()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Identity link intents are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(NEW.id, NEW.organization_id, NEW.actor_principal_id,
                   NEW.actor_binding_id, NEW.target_authority_id,
                   NEW.actor_binding_revision, NEW.nonce_digest, NEW.expires_at,
                   NEW.provenance_reference, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.organization_id, OLD.actor_principal_id,
                   OLD.actor_binding_id, OLD.target_authority_id,
                   OLD.actor_binding_revision, OLD.nonce_digest, OLD.expires_at,
                   OLD.provenance_reference, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Identity link intent identity and scope are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'pending' AND NEW.status = 'consumed'
               AND NEW.consumed_at IS NOT NULL
               AND NEW.resulting_binding_id IS NOT NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'pending' AND NEW.status IN ('revoked', 'expired') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Identity link intent mutation'
                USING ERRCODE = '55000';
        END
        $$;
        ALTER FUNCTION request_engine.guard_identity_link_intent()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_identity_link_intent()
            FROM PUBLIC;
        CREATE TRIGGER identity_link_intents_guard
            BEFORE UPDATE OR DELETE ON request_engine.identity_link_intents
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_identity_link_intent();
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_engine.create_identity_link_intent(
            p_intent_id uuid,
            p_actor_binding_id uuid,
            p_target_authority_id uuid,
            p_nonce_digest text,
            p_ttl_seconds integer,
            p_provenance_reference text
        ) RETURNS TABLE (
            intent_id uuid,
            expires_at timestamp with time zone,
            target_authority_id uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_expires_at timestamptz;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL
               OR p_actor_binding_id IS NULL
               OR p_target_authority_id IS NULL THEN
                RAISE EXCEPTION 'Identity link intent identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_ttl_seconds IS NULL OR p_ttl_seconds < 60 OR p_ttl_seconds > 900 THEN
                RAISE EXCEPTION 'Identity link intent TTL must be between 60 and 900 seconds'
                    USING ERRCODE = '22023';
            END IF;
            IF p_nonce_digest IS NULL OR p_nonce_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity link intent nonce digest is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link intent provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_binding
              FROM request_engine.identity_bindings
             WHERE id = p_actor_binding_id
               AND organization_id = v_org_id
               AND principal_id = v_actor_id
               AND principal_plane = 'tenant'
               AND status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active actor identity binding not found'
                    USING ERRCODE = 'P0002';
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities
             WHERE id = p_target_authority_id
               AND status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Target identity authority is not active'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_link_intents AS intent
                 WHERE intent.actor_principal_id = v_actor_id
                   AND intent.target_authority_id = p_target_authority_id
                   AND intent.status = 'pending'
                   AND intent.expires_at > clock_timestamp()
            ) THEN
                RAISE EXCEPTION 'A live Identity link intent already exists for this authority'
                    USING ERRCODE = '23505';
            END IF;

            v_expires_at := clock_timestamp()
                + make_interval(secs => p_ttl_seconds);
            INSERT INTO request_engine.identity_link_intents (
                id, organization_id, actor_principal_id, actor_binding_id,
                target_authority_id, actor_binding_revision, nonce_digest,
                status, expires_at, provenance_reference
            ) VALUES (
                p_intent_id, v_org_id, v_actor_id, p_actor_binding_id,
                p_target_authority_id, v_binding.revision, p_nonce_digest,
                'pending', v_expires_at, btrim(p_provenance_reference)
            );

            INSERT INTO request_engine.identity_link_facts (
                actor_principal_id, organization_id, capability_key, action,
                intent_id, target_authority_id, nonce_digest,
                provenance_reference
            ) VALUES (
                v_actor_id, v_org_id, 'identity.link_self', 'intent_created',
                p_intent_id, p_target_authority_id, p_nonce_digest,
                btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_intent_id, v_expires_at, p_target_authority_id;
        END
        $$;
        ALTER FUNCTION request_engine.create_identity_link_intent(
            uuid, uuid, uuid, text, integer, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.create_identity_link_intent(
            uuid, uuid, uuid, text, integer, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.create_identity_link_intent(
            uuid, uuid, uuid, text, integer, text
        ) TO request_engine_app;
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION request_engine.confirm_identity_link_intent(
            p_intent_id uuid,
            p_expected_actor_binding_revision bigint,
            p_native_identity_id uuid,
            p_binding_id uuid,
            p_provenance_reference text
        ) RETURNS TABLE (
            binding_id uuid,
            principal_id uuid,
            binding_revision bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_intent request_engine.identity_link_intents%ROWTYPE;
            v_binding request_engine.identity_bindings%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_binding_id IS NULL THEN
                RAISE EXCEPTION 'Identity link confirmation identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_expected_actor_binding_revision IS NULL
               OR p_expected_actor_binding_revision < 1 THEN
                RAISE EXCEPTION 'A positive actor binding revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link confirmation provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_intent
              FROM request_engine.identity_link_intents
             WHERE id = p_intent_id
               AND organization_id = v_org_id
               AND actor_principal_id = v_actor_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity link intent not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_intent.status <> 'pending' THEN
                RAISE EXCEPTION 'Identity link intent is no longer pending'
                    USING ERRCODE = '55000';
            END IF;
            IF v_intent.expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Identity link intent has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF p_expected_actor_binding_revision <> v_intent.actor_binding_revision THEN
                RAISE EXCEPTION 'Identity link intent actor binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT * INTO v_binding
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_intent.actor_binding_id
               AND binding.organization_id = v_org_id
               AND binding.principal_id = v_actor_id
               AND binding.principal_plane = 'tenant'
               AND binding.status = 'active'
             FOR UPDATE;
            IF NOT FOUND OR v_binding.revision <> v_intent.actor_binding_revision THEN
                RAISE EXCEPTION 'Actor identity binding is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF NOT request_auth.lock_credentialed_native_identity(
                v_intent.target_authority_id, p_native_identity_id
            ) THEN
                RAISE EXCEPTION 'Native identity proof is no longer valid'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS existing
                 WHERE existing.identity_authority_id = v_intent.target_authority_id
                   AND existing.subject_id = p_native_identity_id::text
                   AND existing.organization_id = v_org_id
                   AND existing.status <> 'revoked'
            ) THEN
                RAISE EXCEPTION 'Native identity is already linked in this tenant'
                    USING ERRCODE = '23505';
            END IF;

            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                p_binding_id, v_org_id, v_actor_id, 'tenant',
                v_intent.target_authority_id, p_native_identity_id::text, 'active'
            );

            UPDATE request_engine.identity_link_intents
               SET status = 'consumed',
                   consumed_at = clock_timestamp(),
                   resulting_binding_id = p_binding_id
             WHERE id = p_intent_id;

            INSERT INTO request_engine.identity_link_facts (
                actor_principal_id, organization_id, capability_key, action,
                intent_id, target_authority_id, subject_id, binding_id,
                nonce_digest, provenance_reference
            ) VALUES (
                v_actor_id, v_org_id, 'identity.link_self', 'linked',
                p_intent_id, v_intent.target_authority_id,
                p_native_identity_id::text, p_binding_id, v_intent.nonce_digest,
                btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_binding_id, v_actor_id, 1::bigint;
        END
        $$;
        ALTER FUNCTION request_engine.confirm_identity_link_intent(
            uuid, bigint, uuid, uuid, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.confirm_identity_link_intent(
            uuid, bigint, uuid, uuid, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.confirm_identity_link_intent(
            uuid, bigint, uuid, uuid, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove self-service dual-proof identity linking; roll forward")
