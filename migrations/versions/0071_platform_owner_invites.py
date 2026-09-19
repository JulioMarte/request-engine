"""Governed additional Platform Owner invitation and lifecycle.

Revision ID: 0071_platform_owner_invites
Revises: 0070_offline_recovery_lock_order

P5 extends the one-time Instance Claim trust root without reopening setup:

- an existing strongly authenticated Platform Owner may mint one opaque invitation;
- only the invitation digest/fingerprint are durable;
- invitation acceptance creates a Native identity/password but no Principal authority;
- finalization requires a verified active WebAuthn credential and an active
  recovery-code set for that identity;
- finalization atomically creates the Platform Principal/binding and materializes
  immutable platform-owner-v2 grants;
- owner suspension/reactivation/revocation is revisioned, idempotent and cannot
  remove the last effective Platform Owner.

Raw invitation proofs never enter business/audit tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0071_platform_owner_invites"
down_revision: str | Sequence[str] | None = "0070_offline_recovery_lock_order"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL = "request_platform_control_definer"
_READ = "request_platform_definer"

_CREATE_INVITE = (
    "request_platform.create_platform_owner_invitation("
    "uuid,bytea,text,timestamptz,text,text,text)"
)
_READ_INVITE = "request_platform.read_platform_owner_invitation(uuid,bytea)"
_ENROLL_INVITE = (
    "request_platform.enroll_platform_owner_invitation("
    "uuid,bytea,uuid,text,uuid,text)"
)
_FINALIZE_INVITE = (
    "request_platform.finalize_platform_owner_invitation(uuid,bytea,uuid,uuid)"
)
_REVOKE_INVITE = (
    "request_platform.revoke_platform_owner_invitation("
    "uuid,bigint,text,text,text)"
)
_READ_OWNERS = "request_platform.read_platform_owners(uuid,uuid,integer)"
_TRANSITION_OWNER = (
    "request_platform.transition_platform_owner("
    "uuid,text,bigint,text,text,text,text)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        """
        CREATE TABLE request_engine.platform_owner_invitations (
            id uuid PRIMARY KEY,
            token_digest bytea NOT NULL UNIQUE,
            token_fingerprint text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            invited_by_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            native_identity_id uuid
                REFERENCES request_engine.native_identities(id),
            policy_key text NOT NULL DEFAULT 'platform-owner-v2',
            provenance_reference text NOT NULL,
            idempotency_key_digest text NOT NULL,
            intent_digest text NOT NULL,
            expires_at timestamptz NOT NULL,
            revision bigint NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            identity_bound_at timestamptz,
            consumed_at timestamptz,
            revoked_at timestamptz,
            revoke_reason_code text,
            CONSTRAINT platform_owner_invitation_digest_check
                CHECK (octet_length(token_digest) = 32),
            CONSTRAINT platform_owner_invitation_fingerprint_check
                CHECK (token_fingerprint ~ '^[0-9a-f]{16}$'),
            CONSTRAINT platform_owner_invitation_status_check
                CHECK (status IN ('pending', 'enrolling', 'consumed', 'revoked')),
            CONSTRAINT platform_owner_invitation_provenance_check
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            CONSTRAINT platform_owner_invitation_idempotency_check
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_owner_invitation_intent_check
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_owner_invitation_revision_check CHECK (revision > 0),
            CONSTRAINT platform_owner_invitation_lifecycle_check CHECK (
                (status = 'pending'
                    AND native_identity_id IS NULL
                    AND identity_bound_at IS NULL
                    AND consumed_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'enrolling'
                    AND native_identity_id IS NOT NULL
                    AND identity_bound_at IS NOT NULL
                    AND consumed_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'consumed'
                    AND native_identity_id IS NOT NULL
                    AND identity_bound_at IS NOT NULL
                    AND consumed_at IS NOT NULL
                    AND revoked_at IS NULL)
                OR (status = 'revoked'
                    AND consumed_at IS NULL
                    AND revoked_at IS NOT NULL
                    AND revoke_reason_code IS NOT NULL)
            ),
            UNIQUE (invited_by_principal_id, idempotency_key_digest)
        );
        ALTER TABLE request_engine.platform_owner_invitations
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_owner_invitations
            FROM PUBLIC, request_engine_app, request_engine_worker;

        CREATE TABLE request_engine.platform_owner_invitation_facts (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            invitation_id uuid NOT NULL
                REFERENCES request_engine.platform_owner_invitations(id),
            action text NOT NULL,
            actor_principal_id uuid REFERENCES request_engine.principals(id),
            native_identity_id uuid REFERENCES request_engine.native_identities(id),
            owner_principal_id uuid REFERENCES request_engine.principals(id),
            reason_code text,
            revision_before bigint NOT NULL,
            revision_after bigint NOT NULL,
            correlation_id uuid,
            idempotency_key_digest text,
            intent_digest text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_owner_invitation_fact_action_check
                CHECK (action IN ('invite', 'bind_identity', 'finalize', 'revoke')),
            CONSTRAINT platform_owner_invitation_fact_revision_check
                CHECK (revision_before > 0 AND revision_after >= revision_before),
            CONSTRAINT platform_owner_invitation_fact_reason_check
                CHECK (reason_code IS NULL
                       OR length(btrim(reason_code)) BETWEEN 1 AND 200),
            CONSTRAINT platform_owner_invitation_fact_key_check
                CHECK (idempotency_key_digest IS NULL
                       OR idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT platform_owner_invitation_fact_intent_check
                CHECK (intent_digest IS NULL OR intent_digest ~ '^[0-9a-f]{64}$')
        );
        ALTER TABLE request_engine.platform_owner_invitation_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_owner_invitation_facts
            FROM PUBLIC, request_engine_app, request_engine_worker;
        CREATE TRIGGER platform_owner_invitation_facts_append_only
            BEFORE UPDATE OR DELETE ON request_engine.platform_owner_invitation_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    # Version the immutable policy instead of rewriting the historical v1 policy.
    op.execute(
        """
        INSERT INTO request_engine.platform_owner_policies (policy_key, revision, grants)
        SELECT
            'platform-owner-v2',
            2,
            grants || '[
                {"capability_key": "platform.owner.invite", "delegable": false},
                {"capability_key": "platform.owner.read", "delegable": false},
                {"capability_key": "platform.owner.manage_lifecycle", "delegable": false}
            ]'::jsonb
          FROM request_engine.platform_owner_policies
         WHERE policy_key = 'platform-owner-v1';

        INSERT INTO request_engine.principal_authority_grants (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, provenance_kind, provenance_reference
        )
        SELECT owner.id, 'platform', 'platform', capability.capability_key, false,
               'owner_policy_upgrade',
               'platform-owner-v2:' || owner.id::text
          FROM request_engine.principals AS owner
          CROSS JOIN (
              VALUES ('platform.owner.invite'),
                     ('platform.owner.read'),
                     ('platform.owner.manage_lifecycle')
          ) AS capability(capability_key)
         WHERE owner.principal_plane = 'platform'
           AND owner.principal_kind = 'human'
           AND owner.active
           AND EXISTS (
               SELECT 1
                 FROM request_engine.principal_authority_grants AS grant_row
                WHERE grant_row.principal_id = owner.id
                  AND grant_row.principal_plane = 'platform'
                  AND grant_row.authority_plane = 'platform'
                  AND grant_row.capability_key = 'platform.tenant_provisioner.provision'
                  AND grant_row.status = 'active'
                  AND grant_row.provenance_kind = 'trust_bootstrap'
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM request_engine.principal_authority_grants AS existing
                WHERE existing.principal_id = owner.id
                  AND existing.capability_key = capability.capability_key
                  AND existing.status = 'active'
           );
        """
    )

    op.execute(
        f"""
        GRANT SELECT (id, principal_kind, principal_plane, active, authority_revision)
            ON request_engine.principals TO {_CONTROL}, {_READ};
        GRANT SELECT (
            id, principal_id, principal_plane, identity_authority_id, subject_id,
            status, revision
        ), INSERT (
            id, principal_id, principal_plane, identity_authority_id, subject_id, status
        ), UPDATE (status, revision, revoked_at)
            ON request_engine.identity_bindings TO {_CONTROL};
        GRANT SELECT (
            id, principal_id, principal_plane, authority_plane, capability_key,
            status, revision, provenance_kind, provenance_reference
        ), INSERT (
            principal_id, principal_plane, authority_plane, capability_key,
            delegable, granted_by_principal_id, provenance_kind, provenance_reference
        ), UPDATE (status, revision, revoked_at, revoked_by_principal_id)
            ON request_engine.principal_authority_grants TO {_CONTROL}, {_READ};
        GRANT SELECT (policy_key, revision, grants)
            ON request_engine.platform_owner_policies TO {_CONTROL};
        GRANT SELECT (
            id, token_digest, token_fingerprint, status, invited_by_principal_id,
            native_identity_id, policy_key, provenance_reference,
            idempotency_key_digest, intent_digest, expires_at, revision,
            created_at, identity_bound_at, consumed_at, revoked_at, revoke_reason_code
        ), INSERT (
            id, token_digest, token_fingerprint, status, invited_by_principal_id,
            policy_key, provenance_reference, idempotency_key_digest, intent_digest,
            expires_at
        ), UPDATE (
            status, native_identity_id, revision, identity_bound_at, consumed_at,
            revoked_at, revoke_reason_code
        ) ON request_engine.platform_owner_invitations TO {_CONTROL};
        GRANT SELECT (
            id, invitation_id, action, actor_principal_id, native_identity_id,
            owner_principal_id, revision_before, revision_after,
            idempotency_key_digest, intent_digest
        ), INSERT (
            invitation_id, action, actor_principal_id, native_identity_id,
            owner_principal_id, reason_code, revision_before, revision_after,
            correlation_id, idempotency_key_digest, intent_digest
        ) ON request_engine.platform_owner_invitation_facts TO {_CONTROL};
        GRANT SELECT (id, identity_authority_id, status)
            ON request_engine.native_identities TO {_CONTROL};
        GRANT INSERT (id, identity_authority_id, login_handle)
            ON request_engine.native_identities TO {_CONTROL};
        GRANT INSERT (id, native_identity_id, verifier)
            ON request_engine.native_credentials TO {_CONTROL};
        GRANT SELECT (
            id, native_identity_id, status, user_verified
        ) ON request_engine.webauthn_credentials TO {_CONTROL};
        GRANT SELECT (
            id, native_identity_id, status
        ) ON request_engine.recovery_code_sets TO {_CONTROL};
        GRANT SELECT (
            id, set_id, used_at
        ) ON request_engine.recovery_codes TO {_CONTROL};
        GRANT SELECT (
            singleton_key, built_in_native_authority_id
        ) ON request_engine.platform_instance TO {_CONTROL};
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.create_platform_owner_invitation(
            p_invitation_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_expires_at timestamptz,
            p_provenance_reference text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            invitation_id uuid,
            status text,
            expires_at timestamptz,
            revision bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_replay record;
        BEGIN
            IF p_invitation_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '7 days'
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner invitation input is invalid'
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

            SELECT principal.authority_revision
              INTO v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.active
             FOR UPDATE;
            IF NOT FOUND OR v_actor_revision IS NULL
               OR v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform Owner actor is unavailable or stale'
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
                RAISE EXCEPTION 'Platform actor cannot invite owners'
                    USING ERRCODE = '42501';
            END IF;

            SELECT invitation.id, invitation.status, invitation.expires_at,
                   invitation.revision, invitation.intent_digest
              INTO v_replay
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.invited_by_principal_id = v_actor_id
               AND invitation.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Invitation idempotency key conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT v_replay.id, v_replay.status,
                                    v_replay.expires_at, v_replay.revision;
                RETURN;
            END IF;

            INSERT INTO request_engine.platform_owner_invitations (
                id, token_digest, token_fingerprint, status,
                invited_by_principal_id, policy_key, provenance_reference,
                idempotency_key_digest, intent_digest, expires_at
            ) VALUES (
                p_invitation_id, p_token_digest, p_token_fingerprint, 'pending',
                v_actor_id, 'platform-owner-v2', btrim(p_provenance_reference),
                p_idempotency_key_digest, p_intent_digest, p_expires_at
            );

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, reason_code,
                revision_before, revision_after, correlation_id,
                idempotency_key_digest, intent_digest
            ) VALUES (
                p_invitation_id, 'invite', v_actor_id, 'owner_invited',
                1, 1, v_correlation_id, p_idempotency_key_digest, p_intent_digest
            );

            RETURN QUERY SELECT p_invitation_id, 'pending'::text, p_expires_at, 1::bigint;
        END
        $function$;

        CREATE FUNCTION request_platform.read_platform_owner_invitation(
            p_invitation_id uuid,
            p_token_digest bytea
        )
        RETURNS TABLE (
            invitation_id uuid,
            status text,
            native_identity_id uuid,
            expires_at timestamptz,
            policy_key text,
            revision bigint
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
            SELECT invitation.id,
                   invitation.status,
                   invitation.native_identity_id,
                   invitation.expires_at,
                   invitation.policy_key,
                   invitation.revision
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
               AND invitation.token_digest = p_token_digest
               AND invitation.status IN ('pending', 'enrolling')
               AND invitation.expires_at > clock_timestamp()
        $function$;

        CREATE FUNCTION request_platform.enroll_platform_owner_invitation(
            p_invitation_id uuid,
            p_token_digest bytea,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_password_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_invitation request_engine.platform_owner_invitations%ROWTYPE;
            v_authority_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();

            IF p_invitation_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_native_identity_id IS NULL
               OR p_login_handle IS NULL
               OR length(btrim(p_login_handle)) NOT BETWEEN 1 AND 320
               OR p_credential_id IS NULL
               OR p_password_verifier IS NULL
               OR length(p_password_verifier) <= 32
               OR NOT (
                   p_password_verifier LIKE 'scrypt$%'
                   OR p_password_verifier LIKE '$argon2id$%'
               )
            THEN
                RETURN NULL;
            END IF;

            SELECT invitation.* INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
               AND invitation.token_digest = p_token_digest
             FOR UPDATE;
            IF NOT FOUND
               OR v_invitation.status NOT IN ('pending', 'enrolling')
               OR v_invitation.expires_at <= clock_timestamp()
            THEN
                RETURN NULL;
            END IF;

            IF v_invitation.status = 'enrolling' THEN
                IF v_invitation.native_identity_id = p_native_identity_id THEN
                    RETURN p_native_identity_id;
                END IF;
                RAISE EXCEPTION 'Invitation is already bound to another identity'
                    USING ERRCODE = '23505';
            END IF;

            SELECT instance.built_in_native_authority_id
              INTO v_authority_id
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1;
            IF v_authority_id IS NULL THEN
                RAISE EXCEPTION 'Built-in native authority is unavailable'
                    USING ERRCODE = '23514';
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = v_authority_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Built-in native authority is unavailable'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, v_authority_id, btrim(p_login_handle)
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_password_verifier
            );

            UPDATE request_engine.platform_owner_invitations
               SET status = 'enrolling',
                   native_identity_id = p_native_identity_id,
                   revision = revision + 1,
                   identity_bound_at = clock_timestamp()
             WHERE id = p_invitation_id;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, native_identity_id, reason_code,
                revision_before, revision_after
            ) VALUES (
                p_invitation_id, 'bind_identity', p_native_identity_id,
                'invitee_identity_enrolled', v_invitation.revision,
                v_invitation.revision + 1
            );

            RETURN p_native_identity_id;
        END
        $function$;

        CREATE FUNCTION request_platform.finalize_platform_owner_invitation(
            p_invitation_id uuid,
            p_token_digest bytea,
            p_principal_id uuid,
            p_binding_id uuid
        )
        RETURNS TABLE (
            owner_principal_id uuid,
            binding_id uuid,
            native_identity_id uuid,
            policy_key text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_invitation request_engine.platform_owner_invitations%ROWTYPE;
            v_identity request_engine.native_identities%ROWTYPE;
            v_policy request_engine.platform_owner_policies%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();

            IF p_invitation_id IS NULL OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_principal_id IS NULL OR p_binding_id IS NULL
            THEN
                RAISE EXCEPTION 'Platform Owner finalization input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT invitation.* INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
               AND invitation.token_digest = p_token_digest
             FOR UPDATE;
            IF NOT FOUND
               OR v_invitation.status <> 'enrolling'
               OR v_invitation.expires_at <= clock_timestamp()
               OR v_invitation.native_identity_id IS NULL
            THEN
                RAISE EXCEPTION 'Platform Owner invitation is not finalizable'
                    USING ERRCODE = '55000';
            END IF;

            SELECT identity.* INTO v_identity
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_invitation.native_identity_id
               AND identity.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Invited native identity is unavailable'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.webauthn_credentials AS credential
                 WHERE credential.native_identity_id = v_identity.id
                   AND credential.status = 'active'
                   AND credential.user_verified
            ) THEN
                RAISE EXCEPTION 'Platform Owner requires verified WebAuthn'
                    USING ERRCODE = '23514';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.native_identity_id = v_identity.id
                   AND code_set.status = 'active'
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.recovery_codes AS code
                        WHERE code.set_id = code_set.id
                          AND code.used_at IS NULL
                   )
            ) THEN
                RAISE EXCEPTION 'Platform Owner requires unused recovery codes'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.identity_authority_id = v_identity.identity_authority_id
                   AND binding.subject_id = v_identity.id::text
                   AND binding.principal_plane = 'platform'
            ) THEN
                RAISE EXCEPTION 'Invited identity already has platform authority history'
                    USING ERRCODE = '23505';
            END IF;

            SELECT policy.* INTO v_policy
              FROM request_engine.platform_owner_policies AS policy
             WHERE policy.policy_key = v_invitation.policy_key;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner policy is unavailable'
                    USING ERRCODE = '55000';
            END IF;

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id, 'platform', 'human',
                'platform-owner:' || v_identity.id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                p_binding_id, p_principal_id, 'platform',
                v_identity.identity_authority_id, v_identity.id::text, 'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, granted_by_principal_id, provenance_kind, provenance_reference
            )
            SELECT p_principal_id,
                   'platform',
                   'platform',
                   grant_item ->> 'capability_key',
                   coalesce((grant_item ->> 'delegable')::boolean, false),
                   v_invitation.invited_by_principal_id,
                   'owner_invitation',
                   'platform-owner-invitation:' || v_invitation.id::text
              FROM jsonb_array_elements(v_policy.grants) AS grant_item;

            UPDATE request_engine.platform_owner_invitations
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_invitation_id;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                owner_principal_id, reason_code, revision_before, revision_after
            ) VALUES (
                p_invitation_id, 'finalize', v_invitation.invited_by_principal_id,
                v_identity.id, p_principal_id, 'owner_authority_activated',
                v_invitation.revision, v_invitation.revision + 1
            );

            RETURN QUERY SELECT p_principal_id, p_binding_id, v_identity.id,
                                v_policy.policy_key;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.revoke_platform_owner_invitation(
            p_invitation_id uuid,
            p_expected_revision bigint,
            p_reason_code text,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS bigint
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_invitation request_engine.platform_owner_invitations%ROWTYPE;
            v_replay record;
        BEGIN
            IF p_invitation_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 200
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Invitation revoke input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;

            SELECT principal.authority_revision
              INTO v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.active
             FOR UPDATE;
            IF NOT FOUND OR v_actor_revision IS NULL
               OR v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform Owner actor is unavailable or stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.capability_key = 'platform.owner.invite'
                   AND grant_row.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Platform actor cannot revoke owner invitations'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.revision_after, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_owner_invitation_facts AS fact
             WHERE fact.invitation_id = p_invitation_id
               AND fact.action = 'revoke'
               AND fact.actor_principal_id = v_actor_id
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Invitation revoke idempotency key conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_replay.revision_after;
            END IF;

            SELECT invitation.* INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner invitation does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_invitation.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Platform Owner invitation revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_invitation.status NOT IN ('pending', 'enrolling') THEN
                RAISE EXCEPTION 'Platform Owner invitation is already terminal'
                    USING ERRCODE = '55000';
            END IF;

            UPDATE request_engine.platform_owner_invitations
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoke_reason_code = btrim(p_reason_code)
             WHERE id = p_invitation_id;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                reason_code, revision_before, revision_after, correlation_id,
                idempotency_key_digest, intent_digest
            ) VALUES (
                p_invitation_id, 'revoke', v_actor_id,
                v_invitation.native_identity_id, btrim(p_reason_code),
                v_invitation.revision, v_invitation.revision + 1,
                v_correlation_id, p_idempotency_key_digest, p_intent_digest
            );
            RETURN v_invitation.revision + 1;
        END
        $function$;

        CREATE FUNCTION request_platform.principal_is_effective_platform_owner(
            p_principal_id uuid
        ) RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.principals AS principal
                  JOIN request_engine.identity_bindings AS binding
                    ON binding.principal_id = principal.id
                   AND binding.principal_plane = 'platform'
                   AND binding.organization_id IS NULL
                   AND binding.status = 'active'
                  JOIN request_engine.native_identities AS identity
                    ON identity.identity_authority_id = binding.identity_authority_id
                   AND identity.id::text = binding.subject_id
                   AND identity.status = 'active'
                 WHERE principal.id = p_principal_id
                   AND principal.principal_plane = 'platform'
                   AND principal.principal_kind = 'human'
                   AND principal.active
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = principal.id
                          AND grant_row.principal_plane = 'platform'
                          AND grant_row.authority_plane = 'platform'
                          AND grant_row.capability_key = 'platform.owner.invite'
                          AND grant_row.status = 'active'
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.native_credentials AS credential
                        WHERE credential.native_identity_id = identity.id
                          AND credential.kind = 'password'
                          AND credential.status = 'active'
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = identity.id
                          AND credential.status = 'active'
                          AND credential.user_verified
                   )
            )
        $function$;

        CREATE FUNCTION request_platform.assert_other_platform_owner(
            p_excluded_principal_id uuid
        ) RETURNS void
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principals AS principal
                 WHERE principal.principal_plane = 'platform'
                   AND principal.id <> p_excluded_principal_id
                   AND request_platform.principal_is_effective_platform_owner(
                       principal.id
                   )
            ) THEN
                RAISE EXCEPTION 'Platform must retain an effective Platform Owner'
                    USING ERRCODE = '23514';
            END IF;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.read_platform_owners(
            p_principal_id uuid,
            p_after uuid,
            p_limit integer
        )
        RETURNS TABLE (
            principal_id uuid,
            active boolean,
            authority_revision bigint,
            binding_id uuid,
            binding_status text,
            native_identity_id uuid,
            policy_version text,
            capabilities text[]
        )
        LANGUAGE plpgsql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Owner page limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;

            RETURN QUERY
            SELECT principal.id,
                   principal.active,
                   principal.authority_revision,
                   binding.id,
                   binding.status,
                   identity.id,
                   CASE
                       WHEN EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS owner_grant
                            WHERE owner_grant.principal_id = principal.id
                              AND owner_grant.status = 'active'
                              AND owner_grant.capability_key = 'platform.owner.invite'
                       ) THEN 'platform-owner-v2'
                       ELSE 'platform-owner-v1'
                   END,
                   COALESCE((
                       SELECT array_agg(DISTINCT grant_row.capability_key
                                        ORDER BY grant_row.capability_key)
                         FROM request_engine.principal_authority_grants AS grant_row
                        WHERE grant_row.principal_id = principal.id
                          AND grant_row.status = 'active'
                          AND grant_row.authority_plane = 'platform'
                   ), ARRAY[]::text[])
              FROM request_engine.principals AS principal
              JOIN request_engine.identity_bindings AS binding
                ON binding.principal_id = principal.id
               AND binding.principal_plane = 'platform'
               AND binding.organization_id IS NULL
              JOIN request_engine.native_identities AS identity
                ON identity.identity_authority_id = binding.identity_authority_id
               AND identity.id::text = binding.subject_id
             WHERE principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND (p_principal_id IS NULL OR principal.id = p_principal_id)
               AND (p_after IS NULL OR principal.id > p_after)
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.principal_authority_grants AS grant_row
                    WHERE grant_row.principal_id = principal.id
                      AND grant_row.authority_plane = 'platform'
                      AND grant_row.capability_key = 'platform.tenant_provisioner.provision'
                      AND grant_row.provenance_kind IN (
                          'trust_bootstrap', 'owner_invitation', 'owner_policy_upgrade'
                      )
               )
             ORDER BY principal.id
             LIMIT p_limit;
        END
        $function$;

        CREATE FUNCTION request_platform.transition_platform_owner(
            p_principal_id uuid,
            p_action text,
            p_expected_revision bigint,
            p_reason_code text,
            p_external_case_reference text,
            p_idempotency_key_digest text,
            p_intent_digest text
        )
        RETURNS TABLE (
            fact_id uuid,
            principal_id uuid,
            action text,
            authority_revision bigint,
            binding_id uuid,
            binding_status text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_target_revision bigint;
            v_binding_id uuid;
            v_binding_status text;
            v_binding_authority uuid;
            v_binding_subject text;
            v_subject_uuid uuid;
            v_replay record;
            v_fact_id uuid;
        BEGIN
            IF p_principal_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_action NOT IN ('suspend', 'reactivate', 'revoke')
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR (p_external_case_reference IS NOT NULL
                   AND length(btrim(p_external_case_reference)) NOT BETWEEN 1 AND 200)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner lifecycle input is invalid'
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

            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.authority_revision
              INTO v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.active;
            IF NOT FOUND OR v_actor_revision IS NULL
               OR v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform Owner actor is unavailable or stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.capability_key = 'platform.owner.manage_lifecycle'
                   AND grant_row.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Platform actor cannot manage owners'
                    USING ERRCODE = '42501';
            END IF;

            SELECT fact.id, fact.principal_id, fact.action,
                   fact.intent_digest, fact.revision_after
              INTO v_replay
              FROM request_engine.platform_authority_lifecycle_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.owner.manage_lifecycle'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.principal_id <> p_principal_id
                   OR v_replay.action <> p_action
                   OR v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Owner lifecycle idempotency key conflicts'
                        USING ERRCODE = '23505';
                END IF;
                SELECT binding.id, binding.status
                  INTO v_binding_id, v_binding_status
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_id = p_principal_id
                   AND binding.principal_plane = 'platform'
                 ORDER BY (binding.status <> 'revoked') DESC, binding.id
                 LIMIT 1;
                RETURN QUERY SELECT v_replay.id, v_replay.principal_id,
                                    v_replay.action, v_replay.revision_after,
                                    v_binding_id, v_binding_status;
                RETURN;
            END IF;

            SELECT principal.authority_revision
              INTO v_target_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'platform'
               AND principal.principal_kind = 'human'
               AND principal.active;
            IF NOT FOUND OR v_target_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Target owner is unavailable or stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.capability_key = 'platform.owner.invite'
                   AND grant_row.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Target is not a Platform Owner'
                    USING ERRCODE = '22023';
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
                RAISE EXCEPTION 'Platform Owner has no live identity binding'
                    USING ERRCODE = '55000';
            END IF;

            IF p_action IN ('suspend', 'revoke') THEN
                PERFORM request_platform.assert_other_platform_owner(p_principal_id);
            END IF;

            IF p_action = 'suspend' THEN
                IF v_binding_status <> 'active' THEN
                    RAISE EXCEPTION 'Only an active owner can be suspended'
                        USING ERRCODE = '55000';
                END IF;
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended', revision = revision + 1
                 WHERE id = v_binding_id;
            ELSIF p_action = 'reactivate' THEN
                IF v_binding_status <> 'suspended' THEN
                    RAISE EXCEPTION 'Only a suspended owner can be reactivated'
                        USING ERRCODE = '55000';
                END IF;
                BEGIN
                    v_subject_uuid := v_binding_subject::uuid;
                EXCEPTION WHEN invalid_text_representation THEN
                    RAISE EXCEPTION 'Owner native identity is not addressable'
                        USING ERRCODE = '23514';
                END;
                IF NOT request_auth.lock_credentialed_native_identity(
                    v_binding_authority, v_subject_uuid
                ) OR NOT EXISTS (
                    SELECT 1
                      FROM request_engine.webauthn_credentials AS credential
                     WHERE credential.native_identity_id = v_subject_uuid
                       AND credential.status = 'active'
                       AND credential.user_verified
                ) THEN
                    RAISE EXCEPTION 'Owner reactivation requires a live strong auth path'
                        USING ERRCODE = '23514';
                END IF;
                UPDATE request_engine.identity_bindings
                   SET status = 'active', revision = revision + 1
                 WHERE id = v_binding_id;
            ELSE
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked', revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE id = v_binding_id;
                UPDATE request_engine.principal_authority_grants AS grant_row
                   SET status = 'revoked', revision = revision + 1,
                       revoked_at = clock_timestamp(),
                       revoked_by_principal_id = v_actor_id
                 WHERE grant_row.principal_id = p_principal_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.status = 'active';
            END IF;

            SELECT principal.authority_revision INTO v_target_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id;

            v_fact_id := uuidv7();
            INSERT INTO request_engine.platform_authority_lifecycle_facts (
                id, principal_id, action, actor_principal_id,
                actor_authentication_method, reason_code, external_case_reference,
                revision_before, revision_after, correlation_id, capability_key,
                idempotency_key_digest, intent_digest
            ) VALUES (
                v_fact_id, p_principal_id, p_action, v_actor_id,
                v_actor_method, btrim(p_reason_code),
                NULLIF(btrim(p_external_case_reference), ''),
                p_expected_revision, v_target_revision, v_correlation_id,
                'platform.owner.manage_lifecycle',
                p_idempotency_key_digest, p_intent_digest
            );

            SELECT binding.status INTO v_binding_status
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_binding_id;

            RETURN QUERY SELECT v_fact_id, p_principal_id, p_action,
                                v_target_revision, v_binding_id, v_binding_status;
        END
        $function$;
        """
    )

    for signature in (
        _CREATE_INVITE,
        _READ_INVITE,
        _ENROLL_INVITE,
        _FINALIZE_INVITE,
        _REVOKE_INVITE,
        "request_platform.principal_is_effective_platform_owner(uuid)",
        "request_platform.assert_other_platform_owner(uuid)",
        _READ_OWNERS,
        _TRANSITION_OWNER,
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")

    for signature in (
        _CREATE_INVITE,
        _READ_INVITE,
        _ENROLL_INVITE,
        _FINALIZE_INVITE,
        _REVOKE_INVITE,
        _TRANSITION_OWNER,
    ):
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO request_platform_control")

    op.execute(f"ALTER FUNCTION {_READ_OWNERS} OWNER TO {_READ}")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_READ_OWNERS} TO request_platform_read")


def downgrade() -> None:
    raise RuntimeError("Platform Owner invitation/lifecycle facts are durable; roll forward")
