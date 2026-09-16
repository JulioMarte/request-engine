"""OIDC second-proof for self-service identity linking (plan D2 extension).

Adds the subject-based confirmation primitive that consumes a self-service link
intent with a verified external OIDC access token as the second proof. It mirrors
``confirm_identity_link_intent`` exactly: the same identity-topology gate, ordered
staff root and manager assertion, the same actor/intent revalidation, and the same
consume-once semantics. The only difference is the proof: the OIDC subject was
verified against the intent's authority outside any authoritative lock, so this
function re-locks that authority ``FOR SHARE`` and creates the binding for the
SAME tenant Principal. Native linking keeps its own function; a native authority
is rejected here.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0051_oidc_identity_link"
down_revision: str | Sequence[str] | None = "0050_identity_link_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE FUNCTION request_engine.confirm_identity_link_subject(
            p_intent_id uuid,
            p_expected_actor_binding_revision bigint,
            p_subject_id text,
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
            v_authority request_engine.identity_authorities%ROWTYPE;
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_subject_id text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL OR p_binding_id IS NULL THEN
                RAISE EXCEPTION 'Identity link confirmation identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_expected_actor_binding_revision IS NULL
               OR p_expected_actor_binding_revision < 1 THEN
                RAISE EXCEPTION 'A positive actor binding revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_subject_id IS NULL
               OR length(btrim(p_subject_id)) NOT BETWEEN 1 AND 320 THEN
                RAISE EXCEPTION 'Identity link subject is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link confirmation provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            v_subject_id := btrim(p_subject_id);

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

            SELECT * INTO v_authority
              FROM request_engine.identity_authorities
             WHERE id = v_intent.target_authority_id
             FOR SHARE;
            IF NOT FOUND OR v_authority.status <> 'active' THEN
                RAISE EXCEPTION 'Target identity authority is not active'
                    USING ERRCODE = '23514';
            END IF;
            IF v_authority.kind = 'native' THEN
                RAISE EXCEPTION 'Native identity linking uses the native confirmation path'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS existing
                 WHERE existing.identity_authority_id = v_intent.target_authority_id
                   AND existing.subject_id = v_subject_id
                   AND existing.organization_id = v_org_id
                   AND existing.status <> 'revoked'
            ) THEN
                RAISE EXCEPTION 'Identity subject is already linked in this tenant'
                    USING ERRCODE = '23505';
            END IF;

            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                p_binding_id, v_org_id, v_actor_id, 'tenant',
                v_intent.target_authority_id, v_subject_id, 'active'
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
                p_intent_id, v_intent.target_authority_id, v_subject_id,
                p_binding_id, v_intent.nonce_digest, btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_binding_id, v_actor_id, 1::bigint;
        END
        $$;
        ALTER FUNCTION request_engine.confirm_identity_link_subject(
            uuid, bigint, text, uuid, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.confirm_identity_link_subject(
            uuid, bigint, text, uuid, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_engine.confirm_identity_link_subject(
            uuid, bigint, text, uuid, text
        ) TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Do not remove OIDC identity linking; roll forward")
