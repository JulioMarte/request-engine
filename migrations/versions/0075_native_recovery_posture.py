"""Universal Native HUMAN recovery posture and strong-factor completion.

Revision ID: 0075_native_recovery_posture
Revises: 0074_owner_actor_auth

Recovery codes are NativeIdentity credentials, not Platform Owner credentials.
Offline recovery atomically restricts the identity until a recent
PHISHING_RESISTANT ceremony completes recovery. Recovery never changes
Principal, binding, membership, or grant authority.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0075_native_recovery_posture"
down_revision: str | Sequence[str] | None = "0074_owner_actor_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE TABLE request_engine.native_identity_recovery_state (
            native_identity_id uuid PRIMARY KEY
                REFERENCES request_engine.native_identities(id),
            state text NOT NULL,
            recovery_epoch bigint NOT NULL,
            revision bigint NOT NULL DEFAULT 1,
            last_recovered_at timestamptz NOT NULL,
            last_recovery_method text NOT NULL,
            completed_at timestamptz,
            CONSTRAINT native_identity_recovery_state_state_check
                CHECK (state IN ('recovery_restricted', 'normal')),
            CONSTRAINT native_identity_recovery_state_epoch_check
                CHECK (recovery_epoch > 0),
            CONSTRAINT native_identity_recovery_state_revision_check
                CHECK (revision > 0),
            CONSTRAINT native_identity_recovery_state_completion_check CHECK (
                (state = 'recovery_restricted' AND completed_at IS NULL)
                OR (state = 'normal' AND completed_at IS NOT NULL)
            )
        );
        ALTER TABLE request_engine.native_identity_recovery_state
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_identity_recovery_state FROM PUBLIC;

        CREATE TABLE request_engine.native_identity_recovery_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            native_identity_id uuid NOT NULL,
            event_kind text NOT NULL,
            recovery_epoch bigint NOT NULL,
            recovery_method text NOT NULL,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT native_identity_recovery_facts_kind_check
                CHECK (event_kind IN ('recovery_started', 'recovery_completed')),
            CONSTRAINT native_identity_recovery_facts_epoch_check
                CHECK (recovery_epoch > 0)
        );
        ALTER TABLE request_engine.native_identity_recovery_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_identity_recovery_facts FROM PUBLIC;
        CREATE INDEX native_identity_recovery_facts_identity_idx
            ON request_engine.native_identity_recovery_facts
            (native_identity_id, created_at);
        CREATE TRIGGER native_identity_recovery_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.native_identity_recovery_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.consume_recovery_code_and_rotate_password(
            p_code_digest bytea,
            p_new_credential_id uuid,
            p_new_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_code_id uuid;
            v_set_id uuid;
            v_native_identity_id uuid;
            v_authority_id uuid;
            v_identity_status text;
            v_authority_status text;
            v_recovery_epoch bigint;
        BEGIN
            IF p_code_digest IS NULL
               OR octet_length(p_code_digest) <> 32
               OR p_new_credential_id IS NULL
               OR p_new_verifier IS NULL
               OR length(p_new_verifier) <= 32
               OR NOT (
                    p_new_verifier LIKE 'scrypt$%'
                    OR p_new_verifier LIKE '$argon2id$%'
               )
            THEN
                RETURN NULL;
            END IF;

            SELECT code.id, code_set.id, code_set.native_identity_id
              INTO v_code_id, v_set_id, v_native_identity_id
              FROM request_engine.recovery_codes AS code
              JOIN request_engine.recovery_code_sets AS code_set
                ON code_set.id = code.set_id
             WHERE code.code_digest = p_code_digest
               AND code.used_at IS NULL
               AND code_set.status = 'active'
               AND code_set.native_identity_id IS NOT NULL
             FOR UPDATE OF code, code_set;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT identity.identity_authority_id
              INTO v_authority_id
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT authority.status
              INTO v_authority_status
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = v_authority_id
               AND authority.kind = 'native'
             FOR UPDATE;
            IF NOT FOUND OR v_authority_status <> 'active' THEN
                RETURN NULL;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id
               AND identity.identity_authority_id = v_authority_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.native_credentials AS credential
             WHERE credential.native_identity_id = v_native_identity_id
               AND credential.kind = 'password'
               AND credential.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.recovery_codes
               SET used_at = clock_timestamp()
             WHERE id = v_code_id;

            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   rotated_at = clock_timestamp(),
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password'
               AND status = 'active';

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_new_credential_id, v_native_identity_id, p_new_verifier
            );

            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;

            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'recovery_code_password_reset'
             WHERE native_identity_id = v_native_identity_id
               AND status = 'active';

            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND status = 'pending';

            INSERT INTO request_engine.native_identity_recovery_state (
                native_identity_id,
                state,
                recovery_epoch,
                revision,
                last_recovered_at,
                last_recovery_method,
                completed_at
            ) VALUES (
                v_native_identity_id,
                'recovery_restricted',
                1,
                1,
                clock_timestamp(),
                'offline_recovery_code',
                NULL
            )
            ON CONFLICT (native_identity_id) DO UPDATE
               SET state = 'recovery_restricted',
                   recovery_epoch =
                       request_engine.native_identity_recovery_state.recovery_epoch + 1,
                   revision =
                       request_engine.native_identity_recovery_state.revision + 1,
                   last_recovered_at = clock_timestamp(),
                   last_recovery_method = 'offline_recovery_code',
                   completed_at = NULL
            RETURNING recovery_epoch INTO v_recovery_epoch;

            INSERT INTO request_engine.native_identity_recovery_facts (
                native_identity_id,
                event_kind,
                recovery_epoch,
                recovery_method,
                correlation_id
            ) VALUES (
                v_native_identity_id,
                'recovery_started',
                v_recovery_epoch,
                'offline_recovery_code',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, code_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'code_consumed', v_set_id, v_native_identity_id, v_code_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.password_reset',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN v_native_identity_id;
        END
        $$;
        ALTER FUNCTION request_auth.consume_recovery_code_and_rotate_password(bytea, uuid, text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
            request_auth.consume_recovery_code_and_rotate_password(bytea, uuid, text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            request_auth.consume_recovery_code_and_rotate_password(bytea, uuid, text)
            TO request_engine_app;
        """
    )

    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION request_auth.consume_native_recovery_intent(
            p_recovery_id uuid,
            p_token_digest bytea,
            p_new_credential_id uuid,
            p_new_verifier text
        ) RETURNS uuid
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_native_identity_id uuid;
            v_identity_status text;
            v_recovery_epoch bigint;
        BEGIN
            SELECT intent.native_identity_id
              INTO v_native_identity_id
              FROM request_engine.native_recovery_intents AS intent
             WHERE intent.id = p_recovery_id
               AND intent.token_digest = p_token_digest
               AND intent.status = 'pending'
               AND intent.expires_at > clock_timestamp();
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.native_recovery_intents AS intent
             WHERE intent.id = p_recovery_id
               AND intent.native_identity_id = v_native_identity_id
               AND intent.token_digest = p_token_digest
               AND intent.status = 'pending'
               AND intent.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   rotated_at = clock_timestamp(),
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password'
               AND status = 'active';

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_new_credential_id, v_native_identity_id, p_new_verifier
            );

            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;

            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'credential_recovery'
             WHERE native_identity_id = v_native_identity_id
               AND status = 'active';

            UPDATE request_engine.native_recovery_intents
               SET status = 'consumed',
                   consumed_at = clock_timestamp()
             WHERE id = p_recovery_id;

            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND id <> p_recovery_id
               AND status = 'pending';

            INSERT INTO request_engine.native_identity_recovery_state (
                native_identity_id,
                state,
                recovery_epoch,
                revision,
                last_recovered_at,
                last_recovery_method,
                completed_at
            ) VALUES (
                v_native_identity_id,
                'recovery_restricted',
                1,
                1,
                clock_timestamp(),
                'delivered_recovery_proof',
                NULL
            )
            ON CONFLICT (native_identity_id) DO UPDATE
               SET state = 'recovery_restricted',
                   recovery_epoch =
                       request_engine.native_identity_recovery_state.recovery_epoch + 1,
                   revision =
                       request_engine.native_identity_recovery_state.revision + 1,
                   last_recovered_at = clock_timestamp(),
                   last_recovery_method = 'delivered_recovery_proof',
                   completed_at = NULL
            RETURNING recovery_epoch INTO v_recovery_epoch;

            INSERT INTO request_engine.native_identity_recovery_facts (
                native_identity_id,
                event_kind,
                recovery_epoch,
                recovery_method,
                correlation_id
            ) VALUES (
                v_native_identity_id,
                'recovery_started',
                v_recovery_epoch,
                'delivered_recovery_proof',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN v_native_identity_id;
        END
        $$;
        ALTER FUNCTION request_auth.consume_native_recovery_intent(uuid, bytea, uuid, text)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
            request_auth.consume_native_recovery_intent(uuid, bytea, uuid, text)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            request_auth.consume_native_recovery_intent(uuid, bytea, uuid, text)
            TO request_engine_app;
        """
    )

    op.execute("DROP FUNCTION request_auth.read_native_session(uuid)")
    op.execute(
        r"""
        CREATE FUNCTION request_auth.read_native_session(p_session_id uuid)
        RETURNS TABLE (
            session_id uuid,
            native_identity_id uuid,
            identity_authority_id uuid,
            password_credential_id uuid,
            password_credential_status text,
            webauthn_credential_id uuid,
            webauthn_credential_status text,
            token_digest bytea,
            session_epoch bigint,
            current_session_epoch bigint,
            session_status text,
            identity_status text,
            authority_status text,
            authentication_methods text[],
            authentication_assurance text,
            user_verified boolean,
            recovery_derived boolean,
            recovery_restricted boolean,
            expires_at timestamptz,
            created_at timestamptz,
            last_seen_at timestamptz,
            last_authenticated_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT s.id,
                   s.native_identity_id,
                   i.identity_authority_id,
                   s.password_credential_id,
                   pc.status,
                   s.webauthn_credential_id,
                   wc.status,
                   s.token_digest,
                   s.session_epoch,
                   i.session_epoch,
                   s.status,
                   i.status,
                   a.status,
                   s.authentication_methods,
                   s.authentication_assurance,
                   s.user_verified,
                   s.recovery_derived,
                   coalesce(rs.state = 'recovery_restricted', false),
                   s.expires_at,
                   s.created_at,
                   s.last_seen_at,
                   s.last_authenticated_at
              FROM request_engine.native_sessions AS s
              JOIN request_engine.native_identities AS i
                ON i.id = s.native_identity_id
              LEFT JOIN request_engine.native_credentials AS pc
                ON pc.id = s.password_credential_id
               AND pc.native_identity_id = s.native_identity_id
              LEFT JOIN request_engine.webauthn_credentials AS wc
                ON wc.id = s.webauthn_credential_id
               AND wc.native_identity_id = s.native_identity_id
              LEFT JOIN request_engine.native_identity_recovery_state AS rs
                ON rs.native_identity_id = s.native_identity_id
              JOIN request_engine.identity_authorities AS a
                ON a.id = i.identity_authority_id
               AND a.kind = 'native'
             WHERE s.id = p_session_id
        $$;
        ALTER FUNCTION request_auth.read_native_session(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_native_session(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_native_session(uuid)
            TO request_engine_app;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.read_native_recovery_readiness(
            p_native_identity_id uuid
        )
        RETURNS TABLE (
            recovery_state text,
            recovery_epoch bigint,
            last_recovered_at timestamptz,
            last_recovery_method text,
            completed_at timestamptz,
            active_code_set boolean,
            remaining_codes bigint,
            active_webauthn_credentials bigint
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            SELECT coalesce(rs.state, 'normal'),
                   coalesce(rs.recovery_epoch, 0),
                   rs.last_recovered_at,
                   rs.last_recovery_method,
                   rs.completed_at,
                   EXISTS (
                       SELECT 1
                         FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.native_identity_id = p_native_identity_id
                          AND code_set.status = 'active'
                   ),
                   (
                       SELECT count(*)
                         FROM request_engine.recovery_codes AS code
                         JOIN request_engine.recovery_code_sets AS code_set
                           ON code_set.id = code.set_id
                        WHERE code_set.native_identity_id = p_native_identity_id
                          AND code_set.status = 'active'
                          AND code.used_at IS NULL
                   ),
                   (
                       SELECT count(*)
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = p_native_identity_id
                          AND credential.status = 'active'
                   )
              FROM request_engine.native_identities AS identity
              LEFT JOIN request_engine.native_identity_recovery_state AS rs
                ON rs.native_identity_id = identity.id
             WHERE identity.id = p_native_identity_id
               AND identity.status = 'active'
        $$;
        ALTER FUNCTION request_auth.read_native_recovery_readiness(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.read_native_recovery_readiness(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.read_native_recovery_readiness(uuid)
            TO request_engine_app;

        CREATE FUNCTION request_auth.complete_native_recovery(
            p_native_identity_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_state text;
            v_epoch bigint;
            v_method text;
        BEGIN
            IF p_native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.native_identities AS identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE identity.id = p_native_identity_id
               AND identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT state, recovery_epoch, last_recovery_method
              INTO v_state, v_epoch, v_method
              FROM request_engine.native_identity_recovery_state
             WHERE native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_state = 'normal' THEN
                RETURN true;
            END IF;

            PERFORM 1
              FROM request_engine.webauthn_credentials AS credential
             WHERE credential.native_identity_id = p_native_identity_id
               AND credential.status = 'active';
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_identity_recovery_state
               SET state = 'normal',
                   revision = revision + 1,
                   completed_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id;

            INSERT INTO request_engine.native_identity_recovery_facts (
                native_identity_id,
                event_kind,
                recovery_epoch,
                recovery_method,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                'recovery_completed',
                v_epoch,
                v_method,
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;
        ALTER FUNCTION request_auth.complete_native_recovery(uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.complete_native_recovery(uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.complete_native_recovery(uuid)
            TO request_engine_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Native recovery posture is append-preserving; roll forward")
