"""Governed platform owner/admin lifecycle with one-time invitation proof.

Block P5 of ``docs/architecture/instance-claim-platform-owner-plan.md``. Adds a
platform-plane membership lifecycle (invited -> active <-> suspended -> revoked)
for additional Platform Owners/Admins, a digest-only one-time invitation proof,
and the revisioned/idempotent commands that create, accept, suspend, reactivate,
revoke and re-authorize them.

Every authority change is delegated within the actor's delegable ceiling, refuses
self-action, and refuses to leave the platform without an effective controller.
The immutable ``platform-owner-v2`` catalog extends ``platform-owner-v1`` with the
owner-administration capabilities; a trigger grants them on new claims and the
migration backfills existing claim owners. All high-risk operations require a
recent phishing-resistant Platform Owner session, enforced in the Python layer.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0068_platform_owner_lifecycle"
down_revision: str | Sequence[str] | None = "0067_webauthn_login"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"
_SCHEMA_OWNER = "request_engine_schema_owner"

_INVITE = "request_platform.invite_platform_owner(uuid, text, timestamptz, text, text)"
_ACCEPT = "request_platform.accept_platform_invitation(text, uuid, bigint, text, text)"
_TRANSITION = "request_platform.transition_platform_membership(uuid, bigint, text, text, text)"
_REPLACE = "request_platform.replace_platform_authority(uuid, bigint, text[], text, text)"

_V2_DELTA = """[
    {"capability_key": "platform.owner.read", "delegable": false},
    {"capability_key": "platform.owner.invite", "delegable": true},
    {"capability_key": "platform.owner.manage_membership", "delegable": true},
    {"capability_key": "platform.owner.manage_authority", "delegable": true}
]"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    # 1. Platform membership lifecycle aggregate. Platform-plane, so no RLS: the
    # control definer is the only writer and no runtime login is granted access.
    op.execute(
        """
        CREATE TABLE request_engine.platform_memberships (
            id uuid PRIMARY KEY,
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            identity_binding_id uuid NOT NULL
                REFERENCES request_engine.identity_bindings(id),
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
            CONSTRAINT platform_memberships_status_check
                CHECK (status IN ('invited', 'active', 'suspended', 'revoked')),
            CONSTRAINT platform_memberships_revision_check CHECK (revision > 0),
            CONSTRAINT platform_memberships_provenance_kind_check
                CHECK (provenance_kind IN ('owner_invitation')),
            CONSTRAINT platform_memberships_provenance_reference_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT platform_memberships_state_time_check CHECK (
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
        CREATE UNIQUE INDEX platform_memberships_principal_live_uq
            ON request_engine.platform_memberships (principal_id)
            WHERE status <> 'revoked';
        CREATE UNIQUE INDEX platform_memberships_binding_live_uq
            ON request_engine.platform_memberships (identity_binding_id)
            WHERE status <> 'revoked';
        ALTER TABLE request_engine.platform_memberships
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_memberships FROM PUBLIC;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_platform_membership()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_principal_plane text;
            v_principal_kind text;
            v_binding_principal uuid;
            v_binding_plane text;
            v_binding_org uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Platform memberships are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.id,
                    NEW.principal_id,
                    NEW.identity_binding_id,
                    NEW.established_by_principal_id,
                    NEW.provenance_kind,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.principal_id,
                    OLD.identity_binding_id,
                    OLD.established_by_principal_id,
                    OLD.provenance_kind,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Platform membership identity is immutable'
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
                    RAISE EXCEPTION 'Invalid Platform membership state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT principal_plane, principal_kind
              INTO v_principal_plane, v_principal_kind
              FROM request_engine.principals
             WHERE id = NEW.principal_id;
            IF NOT FOUND
               OR v_principal_plane <> 'platform'
               OR v_principal_kind <> 'human'
            THEN
                RAISE EXCEPTION 'Platform membership requires a platform HUMAN Principal'
                    USING ERRCODE = '23514';
            END IF;

            SELECT principal_id, principal_plane, organization_id
              INTO v_binding_principal, v_binding_plane, v_binding_org
              FROM request_engine.identity_bindings
             WHERE id = NEW.identity_binding_id;
            IF NOT FOUND
               OR v_binding_principal <> NEW.principal_id
               OR v_binding_plane <> 'platform'
               OR v_binding_org IS NOT NULL
            THEN
                RAISE EXCEPTION 'Platform membership binding scope is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_platform_membership()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_platform_membership() FROM PUBLIC;
        CREATE TRIGGER platform_memberships_guard
            BEFORE INSERT OR UPDATE OR DELETE
            ON request_engine.platform_memberships
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_membership();
        """
    )

    # 2. Digest-only one-time invitation proof. Only the SHA-256 digest is stored;
    # the plaintext proof is returned once to the inviter for out-of-band delivery.
    op.execute(
        """
        CREATE TABLE request_engine.platform_invitation_intents (
            id uuid PRIMARY KEY,
            membership_id uuid NOT NULL
                REFERENCES request_engine.platform_memberships(id),
            proof_digest text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            revision bigint NOT NULL DEFAULT 1,
            created_by_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT platform_invitation_status_check
                CHECK (status IN ('pending', 'consumed', 'revoked')),
            CONSTRAINT platform_invitation_proof_check
                CHECK (proof_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_invitation_revision_check CHECK (revision > 0),
            CONSTRAINT platform_invitation_state_time_check CHECK (
                (status = 'pending'
                    AND consumed_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'consumed'
                    AND consumed_at IS NOT NULL
                    AND revoked_at IS NULL)
                OR (status = 'revoked'
                    AND revoked_at IS NOT NULL)
            )
        );
        CREATE UNIQUE INDEX platform_invitation_proof_uq
            ON request_engine.platform_invitation_intents (proof_digest);
        CREATE UNIQUE INDEX platform_invitation_pending_uq
            ON request_engine.platform_invitation_intents (membership_id)
            WHERE status = 'pending';
        ALTER TABLE request_engine.platform_invitation_intents
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_invitation_intents FROM PUBLIC;
        """
    )
    op.execute(
        """
        CREATE FUNCTION request_engine.guard_platform_invitation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Platform invitation intents are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.id,
                    NEW.membership_id,
                    NEW.proof_digest,
                    NEW.created_by_principal_id,
                    NEW.created_at,
                    NEW.expires_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.membership_id,
                    OLD.proof_digest,
                    OLD.created_by_principal_id,
                    OLD.created_at,
                    OLD.expires_at
                ) THEN
                    RAISE EXCEPTION 'Platform invitation intent identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       OLD.status = 'pending'
                       AND NEW.status IN ('consumed', 'revoked')
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Platform invitation state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.guard_platform_invitation()
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_engine.guard_platform_invitation() FROM PUBLIC;
        CREATE TRIGGER platform_invitation_intents_guard
            BEFORE INSERT OR UPDATE OR DELETE
            ON request_engine.platform_invitation_intents
            FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_invitation();
        """
    )

    # 3. Append-only platform membership lifecycle facts (provenance, never proof).
    op.execute(
        """
        CREATE TABLE request_engine.platform_membership_facts (
            id uuid PRIMARY KEY,
            membership_id uuid NOT NULL
                REFERENCES request_engine.platform_memberships(id),
            principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            action text NOT NULL,
            actor_principal_id uuid NOT NULL REFERENCES request_engine.principals(id),
            actor_authentication_method text NOT NULL,
            revision_before bigint NOT NULL,
            revision_after bigint NOT NULL,
            authority_revision_after bigint,
            capability_key text NOT NULL,
            idempotency_key_digest text NOT NULL,
            intent_digest text NOT NULL,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_membership_facts_action_check CHECK (
                action IN (
                    'invite', 'accept', 'suspend', 'reactivate', 'revoke',
                    'replace_authority'
                )
            ),
            CONSTRAINT platform_membership_facts_method_check
                CHECK (length(btrim(actor_authentication_method)) > 0),
            CONSTRAINT platform_membership_facts_revision_check
                CHECK (revision_before >= 0 AND revision_after >= revision_before),
            CONSTRAINT platform_membership_facts_capability_check
                CHECK (length(btrim(capability_key)) > 0),
            CONSTRAINT platform_membership_facts_key_check
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_membership_facts_intent_check
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_membership_facts_actor_key_uq
                UNIQUE (actor_principal_id, capability_key, idempotency_key_digest)
        );
        ALTER TABLE request_engine.platform_membership_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_membership_facts FROM PUBLIC;
        CREATE TRIGGER platform_membership_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.platform_membership_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    # 4. Reviewed column authority for the control definer.
    op.execute(
        f"GRANT SELECT (id, principal_plane, principal_kind, active, "
        f"authority_revision), "
        f"INSERT (id, principal_plane, principal_kind, external_subject, active), "
        f"UPDATE (active) "
        f"ON request_engine.principals TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (id, principal_id, principal_plane, identity_authority_id, "
        f"subject_id, status, revision, organization_id), "
        f"INSERT (id, principal_id, principal_plane, identity_authority_id, "
        f"subject_id, status), "
        f"UPDATE (status, revision, revoked_at) "
        f"ON request_engine.identity_bindings TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (principal_id, principal_plane, authority_plane, "
        f"capability_key, delegable, status, revision, granted_by_principal_id, "
        f"provenance_kind, provenance_reference), "
        f"INSERT (principal_id, principal_plane, authority_plane, capability_key, "
        f"delegable, granted_by_principal_id, provenance_kind, provenance_reference), "
        f"UPDATE (status, revision, revoked_at, revoked_by_principal_id) "
        f"ON request_engine.principal_authority_grants TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON request_engine.platform_memberships TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE "
        f"ON request_engine.platform_invitation_intents TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON request_engine.platform_membership_facts TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (policy_key, revision, grants) "
        f"ON request_engine.platform_owner_policies TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT SELECT (built_in_native_authority_id) "
        f"ON request_engine.platform_instance TO {_CONTROL_DEFINER}"
    )
    op.execute(
        f"GRANT EXECUTE ON FUNCTION request_auth.revoke_native_sessions(uuid, text) "
        f"TO {_CONTROL_DEFINER}"
    )

    # 5. Invite: creates the pending Platform Principal, binding, membership and
    # one-time proof. Grants no authority; the invitee still must accept.
    op.execute(
        """
        CREATE FUNCTION request_platform.invite_platform_owner(
            p_native_identity_id uuid,
            p_proof_digest text,
            p_expires_at timestamptz,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            membership_id uuid,
            principal_id uuid,
            binding_id uuid,
            invitation_id uuid,
            expires_at timestamptz
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_authority_id uuid;
            v_principal_id uuid;
            v_binding_id uuid;
            v_membership_id uuid;
            v_invitation_id uuid;
            v_replay_membership uuid;
            v_replay_principal uuid;
            v_replay_intent text;
            v_replay_invitation uuid;
            v_replay_expires timestamptz;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();

            IF p_native_identity_id IS NULL OR p_expires_at IS NULL
               OR p_proof_digest !~ '^[0-9a-f]{64}$'
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
               OR p_expires_at <= clock_timestamp()
            THEN
                RAISE EXCEPTION 'Platform owner invitation input is invalid'
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
            IF v_actor_id IS NULL OR v_actor_revision IS NULL
               OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            PERFORM request_engine.acquire_identity_topology_share();

            -- Platform-plane serialization root.
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
                RAISE EXCEPTION 'Current Platform Principal cannot invite owners'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.invite'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks invitation authority'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.membership_id, fact.principal_id, fact.intent_digest
              INTO v_replay_membership, v_replay_principal, v_replay_intent
              FROM request_engine.platform_membership_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.owner.invite'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay_intent <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another invitation'
                        USING ERRCODE = '23505';
                END IF;
                SELECT invitation.id, invitation.expires_at
                  INTO v_replay_invitation, v_replay_expires
                  FROM request_engine.platform_invitation_intents AS invitation
                 WHERE invitation.membership_id = v_replay_membership
                 ORDER BY invitation.created_at DESC
                 LIMIT 1;
                SELECT membership.identity_binding_id INTO v_binding_id
                  FROM request_engine.platform_memberships AS membership
                 WHERE membership.id = v_replay_membership;
                RETURN QUERY SELECT v_replay_membership, v_replay_principal,
                                    v_binding_id, v_replay_invitation,
                                    v_replay_expires;
                RETURN;
            END IF;

            SELECT instance.built_in_native_authority_id INTO v_authority_id
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform instance is unavailable'
                    USING ERRCODE = '55000';
            END IF;

            IF NOT request_auth.lock_credentialed_native_identity(
                v_authority_id, p_native_identity_id
            ) THEN
                RAISE EXCEPTION
                    'Invitation requires an active credentialed Native identity'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_plane = 'platform'
                   AND binding.organization_id IS NULL
                   AND binding.identity_authority_id = v_authority_id
                   AND binding.subject_id = p_native_identity_id::text
                   AND binding.status <> 'revoked'
            ) THEN
                RAISE EXCEPTION 'Native identity already holds a live platform binding'
                    USING ERRCODE = '23505';
            END IF;

            v_principal_id := gen_random_uuid();
            v_binding_id := gen_random_uuid();
            v_membership_id := gen_random_uuid();
            v_invitation_id := gen_random_uuid();

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject, active
            ) VALUES (
                v_principal_id, 'platform', 'human',
                'platform-owner:' || v_principal_id::text, true
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                v_binding_id, v_principal_id, 'platform', v_authority_id,
                p_native_identity_id::text, 'pending'
            );
            INSERT INTO request_engine.platform_memberships (
                id, principal_id, identity_binding_id, status,
                established_by_principal_id, provenance_kind, provenance_reference
            ) VALUES (
                v_membership_id, v_principal_id, v_binding_id, 'invited',
                v_actor_id, 'owner_invitation',
                'platform-owner-invitation:' || v_principal_id::text
            );
            INSERT INTO request_engine.platform_invitation_intents (
                id, membership_id, proof_digest, status,
                created_by_principal_id, expires_at
            ) VALUES (
                v_invitation_id, v_membership_id, p_proof_digest, 'pending',
                v_actor_id, p_expires_at
            );

            INSERT INTO request_engine.platform_membership_facts (
                id, membership_id, principal_id, action, actor_principal_id,
                actor_authentication_method, revision_before, revision_after,
                authority_revision_after, capability_key, idempotency_key_digest,
                intent_digest, correlation_id
            ) VALUES (
                gen_random_uuid(), v_membership_id, v_principal_id, 'invite',
                v_actor_id, v_actor_method, 0, 1, v_actor_current_revision,
                'platform.owner.invite', p_idempotency_key_digest,
                p_intent_digest, v_correlation_id
            );

            RETURN QUERY SELECT v_membership_id, v_principal_id, v_binding_id,
                                v_invitation_id, p_expires_at;
        END
        $$;
        """
    )

    # 6. Accept: the invitee proves control of the bound native identity and
    # consumes the one-time proof, activating the membership. Grants no authority.
    op.execute(
        """
        CREATE FUNCTION request_platform.accept_platform_invitation(
            p_proof_digest text,
            p_native_identity_id uuid,
            p_expected_revision bigint,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            membership_id uuid,
            principal_id uuid,
            member_status text,
            member_revision bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_invitation request_engine.platform_invitation_intents%ROWTYPE;
            v_membership request_engine.platform_memberships%ROWTYPE;
            v_binding_subject text;
            v_replay_intent text;
            v_replay_status text;
            v_replay_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();

            IF p_proof_digest IS NULL OR p_proof_digest !~ '^[0-9a-f]{64}$'
               OR p_native_identity_id IS NULL
               OR p_expected_revision IS NULL OR p_expected_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform invitation acceptance input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_invitation
              FROM request_engine.platform_invitation_intents
             WHERE proof_digest = p_proof_digest
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Invitation proof is invalid'
                    USING ERRCODE = '28000';
            END IF;

            SELECT * INTO v_membership
              FROM request_engine.platform_memberships
             WHERE id = v_invitation.membership_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Invitation membership is unavailable'
                    USING ERRCODE = '55000';
            END IF;

            SELECT binding.subject_id INTO v_binding_subject
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_membership.identity_binding_id;
            IF v_binding_subject IS DISTINCT FROM p_native_identity_id::text THEN
                RAISE EXCEPTION 'Invitation identity proof does not match'
                    USING ERRCODE = '28000';
            END IF;

            SELECT fact.intent_digest, fact.revision_after
              INTO v_replay_intent, v_replay_revision
              FROM request_engine.platform_membership_facts AS fact
             WHERE fact.principal_id = v_membership.principal_id
               AND fact.capability_key = 'platform.owner.accept'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay_intent <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another acceptance'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT v_membership.id, v_membership.principal_id,
                                    v_membership.status, v_membership.revision;
                RETURN;
            END IF;

            IF v_membership.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Platform membership revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_membership.status <> 'invited' THEN
                RAISE EXCEPTION 'Platform invitation is no longer pending'
                    USING ERRCODE = '55000';
            END IF;
            IF v_invitation.status <> 'pending' THEN
                RAISE EXCEPTION 'Platform invitation proof is no longer active'
                    USING ERRCODE = '55000';
            END IF;
            IF v_invitation.expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Platform invitation proof has expired'
                    USING ERRCODE = '55000';
            END IF;

            UPDATE request_engine.principals
               SET active = true
             WHERE id = v_membership.principal_id;
            UPDATE request_engine.identity_bindings
               SET status = 'active', revision = revision + 1
             WHERE id = v_membership.identity_binding_id;
            UPDATE request_engine.platform_memberships
               SET status = 'active', revision = revision + 1,
                   activated_at = clock_timestamp()
             WHERE id = v_membership.id;
            UPDATE request_engine.platform_invitation_intents
               SET status = 'consumed', revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = v_invitation.id;

            INSERT INTO request_engine.platform_membership_facts (
                id, membership_id, principal_id, action, actor_principal_id,
                actor_authentication_method, revision_before, revision_after,
                authority_revision_after, capability_key, idempotency_key_digest,
                intent_digest, correlation_id
            ) VALUES (
                gen_random_uuid(), v_membership.id, v_membership.principal_id,
                'accept', v_membership.principal_id, 'invitation_proof',
                v_membership.revision, v_membership.revision + 1, NULL,
                'platform.owner.accept', p_idempotency_key_digest, p_intent_digest,
                NULL
            );

            RETURN QUERY SELECT v_membership.id, v_membership.principal_id,
                                'active'::text, v_membership.revision + 1;
        END
        $$;
        """
    )

    # 7. Transition: suspend/reactivate/revoke (and cancel an invited membership).
    op.execute(
        """
        CREATE FUNCTION request_platform.transition_platform_membership(
            p_membership_id uuid,
            p_expected_revision bigint,
            p_target_status text,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            membership_id uuid,
            member_status text,
            member_revision bigint,
            authority_revision bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_membership request_engine.platform_memberships%ROWTYPE;
            v_binding_id uuid;
            v_native_identity_id uuid;
            v_replay_intent text;
            v_replay_status text;
            v_replay_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();

            IF p_membership_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_target_status IS NULL
               OR p_target_status NOT IN ('active', 'suspended', 'revoked')
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform membership transition input is invalid'
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
            IF v_actor_id IS NULL OR v_actor_revision IS NULL
               OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            PERFORM request_engine.acquire_identity_topology_share();

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
                RAISE EXCEPTION 'Current Platform Principal cannot manage owners'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.manage_membership'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks membership authority'
                    USING ERRCODE = '42501';
            END IF;

            SELECT * INTO v_membership
              FROM request_engine.platform_memberships
             WHERE id = p_membership_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_membership.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Platform membership self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.intent_digest, fact.revision_after
              INTO v_replay_intent, v_replay_revision
              FROM request_engine.platform_membership_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.owner.manage_membership'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay_intent <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another transition'
                        USING ERRCODE = '23505';
                END IF;
                SELECT membership.status INTO v_replay_status
                  FROM request_engine.platform_memberships AS membership
                 WHERE membership.id = p_membership_id;
                RETURN QUERY SELECT p_membership_id, v_replay_status,
                                    v_replay_revision, v_actor_current_revision;
                RETURN;
            END IF;

            IF v_membership.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Platform membership revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_target_status = 'active'
               AND v_membership.status NOT IN ('suspended')
            THEN
                RAISE EXCEPTION 'Platform membership cannot be reactivated'
                    USING ERRCODE = '55000';
            ELSIF p_target_status = 'suspended'
               AND v_membership.status <> 'active'
            THEN
                RAISE EXCEPTION 'Platform membership cannot be suspended'
                    USING ERRCODE = '55000';
            ELSIF p_target_status = 'revoked'
               AND v_membership.status NOT IN ('invited', 'active', 'suspended')
            THEN
                RAISE EXCEPTION 'Platform membership is already terminally revoked'
                    USING ERRCODE = '55000';
            END IF;

            IF p_target_status IN ('suspended', 'revoked')
               AND request_platform.principal_is_effective_platform_controller(
                       v_membership.principal_id) THEN
                PERFORM request_platform.assert_other_platform_controller(
                    v_membership.principal_id);
            END IF;

            v_binding_id := v_membership.identity_binding_id;
            IF p_target_status = 'active' THEN
                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = v_membership.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active', revision = revision + 1
                 WHERE id = v_binding_id;
                UPDATE request_engine.platform_memberships
                   SET status = 'active', revision = revision + 1,
                       suspended_at = NULL
                 WHERE id = p_membership_id;
            ELSE
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
                 WHERE id = v_binding_id;
                UPDATE request_engine.platform_memberships
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

                IF p_target_status = 'revoked' THEN
                    UPDATE request_engine.principal_authority_grants AS grant_row
                       SET status = 'revoked',
                           revision = grant_row.revision + 1,
                           revoked_at = clock_timestamp(),
                           revoked_by_principal_id = v_actor_id
                     WHERE grant_row.principal_id = v_membership.principal_id
                       AND grant_row.principal_plane = 'platform'
                       AND grant_row.status = 'active';
                END IF;

                SELECT binding.subject_id::uuid INTO v_native_identity_id
                  FROM request_engine.identity_bindings AS binding
                  JOIN request_engine.identity_authorities AS authority
                    ON authority.id = binding.identity_authority_id
                 WHERE binding.id = v_binding_id
                   AND authority.kind = 'native';
                IF v_native_identity_id IS NOT NULL THEN
                    PERFORM request_auth.revoke_native_sessions(
                        v_native_identity_id,
                        'platform_owner_' || p_target_status
                    );
                END IF;
            END IF;

            INSERT INTO request_engine.platform_membership_facts (
                id, membership_id, principal_id, action, actor_principal_id,
                actor_authentication_method, revision_before, revision_after,
                authority_revision_after, capability_key, idempotency_key_digest,
                intent_digest, correlation_id
            ) VALUES (
                gen_random_uuid(), p_membership_id, v_membership.principal_id,
                CASE
                    WHEN p_target_status = 'active' THEN 'reactivate'
                    WHEN p_target_status = 'suspended' THEN 'suspend'
                    ELSE 'revoke'
                END,
                v_actor_id, v_actor_method, v_membership.revision,
                v_membership.revision + 1, v_actor_current_revision,
                'platform.owner.manage_membership', p_idempotency_key_digest,
                p_intent_digest, v_correlation_id
            );

            RETURN QUERY SELECT p_membership_id, p_target_status,
                                v_membership.revision + 1,
                                v_actor_current_revision;
        END
        $$;
        """
    )

    # 8. Replace authority: explicit grant/revoke within the delegable ceiling,
    # never self-elevating and never removing the last effective controller.
    op.execute(
        """
        CREATE FUNCTION request_platform.replace_platform_authority(
            p_membership_id uuid,
            p_expected_authority_revision bigint,
            p_desired_capabilities text[],
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            target_membership_id uuid,
            target_principal_id uuid,
            resulting_authority_revision bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_target_id uuid;
            v_target_revision bigint;
            v_capability text;
            v_plane text;
            v_target_is_controller boolean;
            v_desired_is_controller boolean;
            v_new_revision bigint;
            v_replay_intent text;
            v_replay_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();

            IF p_membership_id IS NULL
               OR p_expected_authority_revision IS NULL
               OR p_expected_authority_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
               OR EXISTS (
                   SELECT 1
                     FROM unnest(
                         COALESCE(p_desired_capabilities, ARRAY[]::text[])
                     ) AS cap
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
                RAISE EXCEPTION 'Desired platform authority is invalid'
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
            IF v_actor_id IS NULL OR v_actor_revision IS NULL
               OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            PERFORM request_engine.acquire_identity_topology_share();

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
                RAISE EXCEPTION 'Current Platform Principal cannot manage authority'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.manage_authority'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks authority management'
                    USING ERRCODE = '42501';
            END IF;

            SELECT membership.principal_id INTO v_target_id
              FROM request_engine.platform_memberships AS membership
             WHERE membership.id = p_membership_id
               AND membership.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active Platform membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target_id = v_actor_id THEN
                RAISE EXCEPTION 'Platform authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.intent_digest, fact.authority_revision_after
              INTO v_replay_intent, v_replay_revision
              FROM request_engine.platform_membership_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.owner.manage_authority'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay_intent <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another authority change'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT p_membership_id, v_target_id,
                                    COALESCE(v_replay_revision,
                                             v_actor_current_revision);
                RETURN;
            END IF;

            SELECT authority_revision INTO v_target_revision
              FROM request_engine.principals
             WHERE id = v_target_id
             FOR UPDATE;
            IF v_target_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                SELECT grant_row.authority_plane INTO v_plane
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.capability_key = v_capability
                   AND grant_row.status = 'active'
                   AND grant_row.delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane <> 'platform' THEN
                    RAISE EXCEPTION 'Desired authority exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            SELECT (
                SELECT count(DISTINCT capability_key) = 1
                  FROM request_engine.principal_authority_grants
                 WHERE principal_id = v_target_id
                   AND principal_plane = 'platform'
                   AND status = 'active'
                   AND capability_key = 'platform.tenant_provisioner.provision'
            ) INTO v_target_is_controller;
            SELECT (
                SELECT count(DISTINCT cap) = 1
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
                 WHERE cap = 'platform.tenant_provisioner.provision'
            ) INTO v_desired_is_controller;
            IF v_target_is_controller AND NOT v_desired_is_controller THEN
                PERFORM request_platform.assert_other_platform_controller(v_target_id);
            END IF;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE principal_id = v_target_id
               AND principal_plane = 'platform'
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
                       AND principal_plane = 'platform'
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    INSERT INTO request_engine.principal_authority_grants (
                        principal_id, principal_plane, authority_plane,
                        capability_key, delegable, granted_by_principal_id,
                        provenance_kind, provenance_reference
                    ) VALUES (
                        v_target_id, 'platform', 'platform', v_capability, false,
                        v_actor_id, 'authority_management',
                        'platform-owner-authority:' || p_membership_id::text
                    );
                END IF;
            END LOOP;

            SELECT authority_revision INTO v_new_revision
              FROM request_engine.principals
             WHERE id = v_target_id;

            INSERT INTO request_engine.platform_membership_facts (
                id, membership_id, principal_id, action, actor_principal_id,
                actor_authentication_method, revision_before, revision_after,
                authority_revision_after, capability_key, idempotency_key_digest,
                intent_digest, correlation_id
            ) VALUES (
                gen_random_uuid(), p_membership_id, v_target_id,
                'replace_authority', v_actor_id, v_actor_method,
                v_target_revision, v_target_revision, v_new_revision,
                'platform.owner.manage_authority', p_idempotency_key_digest,
                p_intent_digest, v_correlation_id
            );

            RETURN QUERY SELECT p_membership_id, v_target_id, v_new_revision;
        END
        $$;
        """
    )

    op.execute(f"ALTER FUNCTION {_INVITE} OWNER TO {_CONTROL_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_INVITE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_INVITE} TO {_RUNTIME}")
    op.execute(f"ALTER FUNCTION {_ACCEPT} OWNER TO {_CONTROL_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_ACCEPT} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_ACCEPT} TO {_RUNTIME}")
    op.execute(f"ALTER FUNCTION {_TRANSITION} OWNER TO {_CONTROL_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_TRANSITION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_TRANSITION} TO {_RUNTIME}")
    op.execute(f"ALTER FUNCTION {_REPLACE} OWNER TO {_CONTROL_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_REPLACE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_REPLACE} TO {_RUNTIME}")

    # 9. Immutable platform-owner-v2 catalog: v1 plus the owner-administration
    # capabilities. Owners may delegate them to peer owners (delegable).
    op.execute(
        f"""
        INSERT INTO request_engine.platform_owner_policies (policy_key, revision, grants)
        SELECT 'platform-owner-v2', 2,
               grants || '{_V2_DELTA.replace(chr(10), " ")}'::jsonb
          FROM request_engine.platform_owner_policies
         WHERE policy_key = 'platform-owner-v1'
        """
    )

    # 10. Grant the v2 capabilities on new claims (finalize still applies v1; the
    # trigger adds the delta) and backfill existing claim owners.
    op.execute(
        f"""
        CREATE FUNCTION request_engine.seed_platform_owner_capabilities()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        BEGIN
            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT NEW.owner_principal_id, 'platform', 'platform',
                   grant_item.capability_key, grant_item.delegable,
                   'trust_bootstrap',
                   'platform-owner-policy-v2:' || NEW.instance_id::text
              FROM request_engine.platform_owner_policies AS policy
              CROSS JOIN LATERAL jsonb_to_recordset(policy.grants)
                  AS grant_item(capability_key text, delegable boolean)
             WHERE policy.policy_key = 'platform-owner-v2'
               AND NOT EXISTS (
                   SELECT 1
                     FROM request_engine.principal_authority_grants AS existing
                    WHERE existing.principal_id = NEW.owner_principal_id
                      AND existing.capability_key = grant_item.capability_key
                      AND existing.status = 'active'
               );
            RETURN NEW;
        END
        $$;
        ALTER FUNCTION request_engine.seed_platform_owner_capabilities()
            OWNER TO {_CONTROL_DEFINER};
        REVOKE ALL ON FUNCTION request_engine.seed_platform_owner_capabilities()
            FROM PUBLIC;
        CREATE TRIGGER platform_installation_claim_seed_owner_capabilities
            AFTER INSERT ON request_engine.platform_installation_claim_facts
            FOR EACH ROW EXECUTE FUNCTION
                request_engine.seed_platform_owner_capabilities();
        """
    )
    op.execute(
        """
        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        )
        SELECT owner.id, 'platform', 'platform',
               grant_item.capability_key, grant_item.delegable,
               'trust_bootstrap',
               'platform-owner-policy-v2-backfill:' || owner.id::text
          FROM request_engine.principals AS owner
          JOIN request_engine.principal_authority_grants AS control_grant
            ON control_grant.principal_id = owner.id
           AND control_grant.principal_plane = 'platform'
           AND control_grant.authority_plane = 'platform'
           AND control_grant.capability_key = 'platform.tenant_provisioner.provision'
           AND control_grant.status = 'active'
           AND control_grant.provenance_kind = 'trust_bootstrap'
          CROSS JOIN LATERAL (
              SELECT grant_item.capability_key, grant_item.delegable
                FROM request_engine.platform_owner_policies AS policy
                CROSS JOIN LATERAL jsonb_to_recordset(policy.grants)
                    AS grant_item(capability_key text, delegable boolean)
               WHERE policy.policy_key = 'platform-owner-v2'
          ) AS grant_item
         WHERE owner.principal_plane = 'platform'
           AND owner.active
           AND NOT EXISTS (
               SELECT 1
                 FROM request_engine.principal_authority_grants AS existing
                WHERE existing.principal_id = owner.id
                  AND existing.capability_key = grant_item.capability_key
                  AND existing.status = 'active'
           );
        """
    )


def downgrade() -> None:
    raise RuntimeError("Platform owner lifecycle is append-preserving; roll forward")
