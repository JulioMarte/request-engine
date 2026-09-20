"""Close Platform Owner compatibility and invitation authority gaps.

Revision ID: 0073_platform_owner_compat
Revises: 0072_owner_invitation

This revision keeps the retired anonymous native enrollment route closed while
repairing three post-P5 boundaries:

* owner invitation transitions read only the invitation columns they need;
* owner invitation activation/revocation use an owner-specific actor assertion,
  not the identity-recovery assertion;
* the supported legacy bootstrap CLI, when used after all migrations have run,
  materializes the same P5 administrative capabilities that 0071 backfills for
  pre-existing trust-bootstrap roots.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0073_platform_owner_compat"
down_revision: str | Sequence[str] | None = "0072_owner_invitation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTROL_DEFINER = "request_platform_control_definer"
_BOOTSTRAP_DEFINER = "request_bootstrap_definer"

_ESTABLISH_ROOT = "request_platform.establish_root(uuid,bytea,uuid,uuid,text,uuid,text,uuid,uuid)"
_ENROLL = "request_platform.enroll_platform_owner_invitation(bytea,uuid,uuid,text,text)"
_REVOKE = "request_platform.revoke_platform_owner_invitation(uuid,text,text,text)"
_ACTIVATE = "request_platform.activate_platform_owner_invitation(uuid,uuid,uuid,text,text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        r"""
        CREATE FUNCTION request_platform.assert_platform_owner_actor(
            p_capability text
        )
        RETURNS TABLE (actor_id uuid, actor_method text, correlation_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
        BEGIN
            IF p_capability NOT IN (
                'platform.owner.provision',
                'platform.owner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Unknown Platform Owner capability'
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

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot administer owners'
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
                   AND actor_grant.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks Platform Owner authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN QUERY SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $function$;

        ALTER FUNCTION request_platform.assert_platform_owner_actor(text)
            OWNER TO request_platform_control_definer;
        REVOKE ALL ON FUNCTION request_platform.assert_platform_owner_actor(text)
            FROM PUBLIC;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.enroll_platform_owner_invitation(
            p_token_digest bytea,
            p_native_identity_id uuid,
            p_credential_id uuid,
            p_login_handle text,
            p_password_verifier text
        ) RETURNS TABLE (invitation_id uuid, native_identity_id uuid)
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_invitation record;
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

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.expires_at
              INTO v_invitation
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
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.revoke_platform_owner_invitation(
            p_invitation_id uuid,
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
            v_correlation_id uuid;
            v_invitation record;
            v_replay record;
            v_revision_before bigint;
        BEGIN
            SELECT actor_id, correlation_id
              INTO v_actor_id, v_correlation_id
              FROM request_platform.assert_platform_owner_actor(
                  'platform.owner.provision'
              );

            IF p_invitation_id IS NULL
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner invitation revocation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT fact.revision_after, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_owner_invitation_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'revoke'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another revocation'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_replay.revision_after;
            END IF;

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.native_identity_id
              INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform Owner invitation does not exist'
                    USING ERRCODE = '22023';
            END IF;
            IF v_invitation.status = 'consumed' THEN
                RAISE EXCEPTION 'Activated Platform Owner invitation cannot be revoked'
                    USING ERRCODE = '22023';
            END IF;
            IF v_invitation.status = 'revoked' THEN
                RETURN v_invitation.revision;
            END IF;

            v_revision_before := v_invitation.revision;
            UPDATE request_engine.platform_owner_invitations
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE id = v_invitation.id
            RETURNING revision INTO v_invitation.revision;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                revision_before, revision_after, correlation_id, reason_code,
                idempotency_key_digest, intent_digest
            ) VALUES (
                v_invitation.id, 'revoke', v_actor_id, v_invitation.native_identity_id,
                v_revision_before, v_invitation.revision, v_correlation_id,
                btrim(p_reason_code), p_idempotency_key_digest, p_intent_digest
            );
            RETURN v_invitation.revision;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.activate_platform_owner_invitation(
            p_invitation_id uuid,
            p_principal_id uuid,
            p_binding_id uuid,
            p_idempotency_key_digest text,
            p_intent_digest text
        ) RETURNS TABLE (
            principal_id uuid,
            binding_id uuid,
            invitation_revision bigint
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $function$
        DECLARE
            v_actor_id uuid;
            v_invitation record;
            v_instance record;
            v_created uuid;
            v_revision_before bigint;
        BEGIN
            SELECT actor_id
              INTO v_actor_id
              FROM request_platform.assert_platform_owner_actor(
                  'platform.owner.provision'
              );

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.native_identity_id, invitation.provenance_reference
              INTO v_invitation
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
                 ORDER BY fact.created_at DESC
                 LIMIT 1;
                IF v_created IS NULL THEN
                    RAISE EXCEPTION 'Consumed invitation has no owner authority fact'
                        USING ERRCODE = '55000';
                END IF;
                SELECT binding.id
                  INTO p_binding_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_id = v_created
                   AND binding.principal_plane = 'platform'
                 ORDER BY binding.id
                 LIMIT 1;
                RETURN QUERY SELECT v_created, p_binding_id, v_invitation.revision;
                RETURN;
            END IF;

            SELECT instance.built_in_native_authority_id
              INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1
               AND instance.state = 'claimed';
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
                v_actor_id,
                v_invitation.native_identity_id,
                v_revision_before,
                v_invitation.revision,
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_created, p_binding_id, v_invitation.revision;
        END
        $function$;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_platform.establish_root(
            p_intent_id uuid,
            p_token_digest bytea,
            p_identity_authority_id uuid,
            p_native_identity_id uuid,
            p_login_handle text,
            p_credential_id uuid,
            p_password_verifier text,
            p_principal_id uuid,
            p_binding_id uuid
        ) RETURNS uuid
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

            PERFORM 1
              FROM request_engine.principals
             WHERE principal_plane = 'platform'
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Platform root already exists'
                    USING ERRCODE = '55000';
            END IF;

            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native'
               OR v_authority_status <> 'active'
            THEN
                RAISE EXCEPTION 'Platform root requires an active Native identity authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, p_identity_authority_id, p_login_handle
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_password_verifier
            );
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
                  ('platform.provisioner.manage_lifecycle', false),
                  ('platform.owner.read', false),
                  ('platform.owner.provision', false),
                  ('platform.owner.manage_lifecycle', false),
                  ('platform.identity.provision', false)
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

    for signature in (_ENROLL, _REVOKE, _ACTIVATE):
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_CONTROL_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
    op.execute(f"ALTER FUNCTION {_ESTABLISH_ROOT} OWNER TO {_BOOTSTRAP_DEFINER}")
    op.execute(f"REVOKE ALL ON FUNCTION {_ESTABLISH_ROOT} FROM PUBLIC")


def downgrade() -> None:
    raise RuntimeError("Platform Owner compatibility fixes are roll-forward only")
