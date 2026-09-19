"""One-time Platform Owner invitation and governed activation.

Revision ID: 0072_owner_invitation
Revises: 0071_platform_owner_lifecycle

The inviter never chooses the invitee password. The invitation bearer is returned
once, only its digest is durable, and enrollment creates no platform authority.
Activation is a separate owner-authorized operation after passkey and recovery
readiness have been proven.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072_owner_invitation"
down_revision: str | Sequence[str] | None = "0071_platform_owner_lifecycle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL = "request_platform_control"
_DEFINER = "request_platform_control_definer"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE TABLE request_engine.platform_owner_invitations (
            id uuid PRIMARY KEY,
            token_digest bytea NOT NULL UNIQUE
                CHECK (octet_length(token_digest) = 32),
            token_fingerprint text NOT NULL
                CHECK (token_fingerprint ~ '^[0-9a-f]{16}$'),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'enrolled', 'consumed', 'revoked')),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
            invited_by_principal_id uuid NOT NULL
                REFERENCES request_engine.principals(id),
            native_identity_id uuid REFERENCES request_engine.native_identities(id),
            provenance_reference text NOT NULL
                CHECK (length(btrim(provenance_reference)) BETWEEN 1 AND 500),
            idempotency_key_digest text NOT NULL
                CHECK (idempotency_key_digest ~ '^[0-9a-f]{64}$'),
            intent_digest text NOT NULL
                CHECK (intent_digest ~ '^[0-9a-f]{64}$'),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL,
            enrolled_at timestamptz,
            consumed_at timestamptz,
            revoked_at timestamptz,
            CONSTRAINT platform_owner_invitation_actor_key_uq
                UNIQUE (invited_by_principal_id, idempotency_key_digest),
            CONSTRAINT platform_owner_invitation_expiry_check
                CHECK (expires_at > created_at),
            CONSTRAINT platform_owner_invitation_state_check CHECK (
                (status = 'pending'
                    AND native_identity_id IS NULL
                    AND enrolled_at IS NULL
                    AND consumed_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'enrolled'
                    AND native_identity_id IS NOT NULL
                    AND enrolled_at IS NOT NULL
                    AND consumed_at IS NULL
                    AND revoked_at IS NULL)
                OR (status = 'consumed'
                    AND native_identity_id IS NOT NULL
                    AND enrolled_at IS NOT NULL
                    AND consumed_at IS NOT NULL
                    AND revoked_at IS NULL)
                OR (status = 'revoked'
                    AND consumed_at IS NULL
                    AND revoked_at IS NOT NULL)
            )
        );
        ALTER TABLE request_engine.platform_owner_invitations
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_owner_invitations
            FROM PUBLIC, request_engine_app, request_engine_worker;

        CREATE TABLE request_engine.platform_owner_invitation_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            invitation_id uuid NOT NULL,
            action text NOT NULL CHECK (action IN ('create', 'enroll', 'activate', 'revoke')),
            actor_principal_id uuid,
            native_identity_id uuid,
            revision_before bigint NOT NULL CHECK (revision_before >= 0),
            revision_after bigint NOT NULL CHECK (revision_after >= revision_before),
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp()
        );
        ALTER TABLE request_engine.platform_owner_invitation_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_owner_invitation_facts FROM PUBLIC;
        CREATE TRIGGER platform_owner_invitation_facts_append_only
            BEFORE UPDATE OR DELETE ON request_engine.platform_owner_invitation_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

        GRANT SELECT (id, token_digest, token_fingerprint, status, revision,
                      invited_by_principal_id, native_identity_id, provenance_reference,
                      idempotency_key_digest, intent_digest, expires_at),
              INSERT (id, token_digest, token_fingerprint, invited_by_principal_id,
                      provenance_reference, idempotency_key_digest, intent_digest, expires_at),
              UPDATE (status, revision, native_identity_id, enrolled_at, consumed_at, revoked_at)
        ON request_engine.platform_owner_invitations TO request_platform_control_definer;
        GRANT INSERT (invitation_id, action, actor_principal_id, native_identity_id,
                      revision_before, revision_after, correlation_id)
        ON request_engine.platform_owner_invitation_facts TO request_platform_control_definer;
        GRANT SELECT (id, built_in_native_authority_id, state)
        ON request_engine.platform_instance TO request_platform_control_definer;
        GRANT INSERT (id, identity_authority_id, login_handle)
        ON request_engine.native_identities TO request_platform_control_definer;
        GRANT INSERT (id, native_identity_id, verifier)
        ON request_engine.native_credentials TO request_platform_control_definer;
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
        ) RETURNS TABLE (invitation_id uuid, created boolean, status text, expires_at timestamptz)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_current_revision bigint;
            v_actor_active boolean;
            v_actor_kind text;
            v_correlation_id uuid;
            v_existing record;
        BEGIN
            IF p_invitation_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '7 days'
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
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
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT principal.active, principal.principal_kind, principal.authority_revision
              INTO v_actor_active, v_actor_kind, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform'
             FOR UPDATE;
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human'
               OR v_actor_current_revision <> v_actor_revision
            THEN
                RAISE EXCEPTION 'Current Platform Owner is unavailable or stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.provision'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal cannot invite owners'
                    USING ERRCODE = '42501';
            END IF;

            SELECT invitation.id, invitation.status, invitation.expires_at,
                   invitation.intent_digest
              INTO v_existing
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.invited_by_principal_id = v_actor_id
               AND invitation.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another invitation'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT v_existing.id, false, v_existing.status,
                                    v_existing.expires_at;
                RETURN;
            END IF;

            INSERT INTO request_engine.platform_owner_invitations (
                id, token_digest, token_fingerprint, invited_by_principal_id,
                provenance_reference, idempotency_key_digest, intent_digest, expires_at
            ) VALUES (
                p_invitation_id, p_token_digest, p_token_fingerprint, v_actor_id,
                btrim(p_provenance_reference), p_idempotency_key_digest,
                p_intent_digest, p_expires_at
            );

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, revision_before,
                revision_after, correlation_id
            ) VALUES (
                p_invitation_id, 'create', v_actor_id, 0, 1, v_correlation_id
            );

            RETURN QUERY SELECT p_invitation_id, true, 'pending'::text, p_expires_at;
        END
        $$;

        CREATE FUNCTION request_platform.enroll_platform_owner_invitation(
            p_token_digest bytea,
            p_native_identity_id uuid,
            p_credential_id uuid,
            p_login_handle text,
            p_password_verifier text
        ) RETURNS TABLE (invitation_id uuid, native_identity_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_invitation request_engine.platform_owner_invitations%ROWTYPE;
            v_instance record;
        BEGIN
            IF p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_native_identity_id IS NULL OR p_credential_id IS NULL
               OR p_login_handle IS NULL
               OR length(btrim(p_login_handle)) NOT BETWEEN 1 AND 320
               OR p_password_verifier IS NULL
               OR NOT (p_password_verifier LIKE '$argon2id$%'
                       OR p_password_verifier LIKE 'scrypt$%')
            THEN
                RETURN;
            END IF;

            SELECT invitation.* INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.token_digest = p_token_digest
             FOR UPDATE;
            IF NOT FOUND
               OR v_invitation.status <> 'pending'
               OR v_invitation.expires_at <= clock_timestamp()
            THEN
                RETURN;
            END IF;

            SELECT instance.id, instance.built_in_native_authority_id, instance.state
              INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1
             FOR SHARE;
            IF NOT FOUND OR v_instance.state <> 'claimed' THEN
                RETURN;
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, v_instance.built_in_native_authority_id,
                btrim(p_login_handle)
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_password_verifier
            );

            UPDATE request_engine.platform_owner_invitations
               SET status = 'enrolled',
                   revision = revision + 1,
                   native_identity_id = p_native_identity_id,
                   enrolled_at = clock_timestamp()
             WHERE id = v_invitation.id;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, native_identity_id, revision_before, revision_after
            ) VALUES (
                v_invitation.id, 'enroll', p_native_identity_id,
                v_invitation.revision, v_invitation.revision + 1
            );

            RETURN QUERY SELECT v_invitation.id, p_native_identity_id;
        EXCEPTION WHEN unique_violation THEN
            RETURN;
        END
        $$;

        CREATE FUNCTION request_platform.activate_platform_owner_invitation(
            p_invitation_id uuid,
            p_principal_id uuid,
            p_binding_id uuid,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (principal_id uuid, binding_id uuid, invitation_revision bigint)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_invitation request_engine.platform_owner_invitations%ROWTYPE;
            v_instance record;
            v_created uuid;
            v_revision_before bigint;
        BEGIN
            PERFORM actor_id
              FROM request_platform.assert_platform_identity_actor(
                  'platform.owner.provision'
              );

            SELECT invitation.* INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND OR v_invitation.status NOT IN ('enrolled', 'consumed') THEN
                RAISE EXCEPTION 'Platform Owner invitation is not activatable'
                    USING ERRCODE = '22023';
            END IF;

            IF v_invitation.status = 'consumed' THEN
                SELECT fact.principal_id INTO v_created
                  FROM request_engine.platform_owner_provisioning_facts AS fact
                 WHERE fact.native_identity_id = v_invitation.native_identity_id
                 ORDER BY fact.created_at DESC LIMIT 1;
                IF v_created IS NULL THEN
                    RAISE EXCEPTION 'Consumed invitation has no owner authority fact'
                        USING ERRCODE = '55000';
                END IF;
                SELECT binding.id
                  INTO p_binding_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_id = v_created
                   AND binding.principal_plane = 'platform'
                 ORDER BY binding.id LIMIT 1;
                RETURN QUERY SELECT v_created, p_binding_id, v_invitation.revision;
                RETURN;
            END IF;

            SELECT instance.built_in_native_authority_id INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1 AND instance.state = 'claimed';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform instance is unavailable'
                    USING ERRCODE = '55000';
            END IF;

            v_created := request_platform.provision_native_platform_owner(
                p_principal_id,
                p_binding_id,
                v_instance.built_in_native_authority_id,
                v_invitation.native_identity_id,
                'owner-invitation:' || v_invitation.id::text || ':'
                    || v_invitation.provenance_reference,
                p_idempotency_key_digest,
                p_intent_digest
            );

            v_revision_before := v_invitation.revision;
            UPDATE request_engine.platform_owner_invitations
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = v_invitation.id
            RETURNING revision INTO v_invitation.revision;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                revision_before, revision_after, correlation_id
            ) VALUES (
                v_invitation.id,
                'activate',
                NULLIF(current_setting('request_engine.authenticated_principal_id', true), '')::uuid,
                v_invitation.native_identity_id,
                v_revision_before,
                v_invitation.revision,
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_created, p_binding_id, v_invitation.revision;
        END
        $$;
        """
    )

    for signature in (
        "request_platform.create_platform_owner_invitation("
        "uuid,bytea,text,timestamp with time zone,text,text,text)",
        "request_platform.activate_platform_owner_invitation(uuid,uuid,uuid,text,text)",
    ):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_CONTROL}")

    enroll = (
        "request_platform.enroll_platform_owner_invitation("
        "bytea,uuid,uuid,text,text)"
    )
    op.execute(f"ALTER FUNCTION {enroll} OWNER TO {_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {enroll} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {enroll} TO {_CONTROL}")

    # Direct owner promotion is now an internal implementation primitive. The
    # supported product path is invitation activation.
    op.execute(
        "REVOKE EXECUTE ON FUNCTION "
        "request_platform.provision_native_platform_owner("
        "uuid,uuid,uuid,uuid,text,text,text) FROM request_platform_control"
    )


def downgrade() -> None:
    raise RuntimeError("Platform Owner invitation history is append-preserving; roll forward")
