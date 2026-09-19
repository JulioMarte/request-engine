"""Atomic HTTP Instance claim: pending setup material and finalize.

Revision ID: 0065_instance_claim
Revises: 0064_recovery_codes

Implements plan §5.3, §6, §9 and the P4 slice:

- ``platform_owner_policies`` holds the immutable versioned ``platform-owner-v1``
  platform capability set granted to the first owner;
- ``setup_pending_identity`` / ``setup_pending_webauthn_credential`` hold first-run
  enrollment material scoped to a SetupSession without creating a permanent
  native identity early;
- ``finalize_setup_webauthn_registration`` consumes a setup-scoped challenge and
  records a pending authenticator;
- ``finalize_instance_claim`` performs the whole claim in one transaction:
  instance lock, setup validation, promotion of pending identity/credential/
  authenticator, platform Principal + active binding + ``platform-owner-v1``
  grants, recovery-code promotion, installation-claim fact, SetupSession
  consumption and the one-way UNCLAIMED -> CLAIMED transition;
- ``read_claim_readiness`` exposes durable readiness facts (no client-supplied
  "complete" flag) and ``read_installation_claim`` supports exact replay.

No Principal, binding, grant or owner is created outside finalize.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0065_instance_claim"
down_revision: str | Sequence[str] | None = "0064_recovery_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFINER = "request_platform_control_definer"
_RUNTIME = "request_platform_control"

# request_platform functions owned by the control definer.
_DEFINER_FUNCTIONS = (
    "request_platform.set_setup_pending_identity(uuid, uuid, text, text)",
    "request_platform.read_setup_pending_identity(uuid)",
    "request_platform.read_claim_readiness(uuid)",
    "request_platform.read_installation_claim(text)",
    ("request_platform.finalize_instance_claim(uuid, text, text, text, text, uuid)"),
)

# request_auth functions owned by the schema owner and granted to the app runtime.
_APP_FUNCTIONS = (
    "request_auth.finalize_setup_webauthn_registration("
    "bytea, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean)",
)

# Column-level grants for the control definer: (table, privilege, columns).
_COLUMN_GRANTS = (
    (
        "platform_instance",
        "UPDATE",
        "state, revision, claimed_at, initial_owner_principal_id, claim_provenance",
    ),
    ("setup_sessions", "UPDATE", "status, revision, consumed_at"),
    ("native_identities", "INSERT", "id, identity_authority_id, login_handle"),
    ("native_credentials", "INSERT", "id, native_identity_id, verifier"),
    (
        "webauthn_credentials",
        "INSERT",
        "id, native_identity_id, credential_id, public_key, sign_count, aaguid, "
        "backup_eligible, backup_state, user_verified",
    ),
    (
        "setup_pending_identity",
        "SELECT",
        "id, setup_session_id, login_handle, verifier, status, created_at, promoted_at",
    ),
    ("setup_pending_identity", "INSERT", "id, setup_session_id, login_handle, verifier"),
    ("setup_pending_identity", "UPDATE", "login_handle, verifier, status, promoted_at"),
    (
        "setup_pending_webauthn_credential",
        "SELECT",
        "id, setup_session_id, credential_id, public_key, sign_count, aaguid, "
        "backup_eligible, backup_state, user_verified, status",
    ),
    (
        "setup_pending_webauthn_credential",
        "INSERT",
        "id, setup_session_id, credential_id, public_key, sign_count, aaguid, "
        "backup_eligible, backup_state, user_verified",
    ),
    ("setup_pending_webauthn_credential", "UPDATE", "status, promoted_at"),
    ("recovery_code_sets", "SELECT", "setup_session_id, native_identity_id, status"),
    ("recovery_code_sets", "UPDATE", "setup_session_id, native_identity_id"),
    ("platform_owner_policies", "SELECT", "policy_key, revision, grants"),
    (
        "platform_installation_claim_facts",
        "SELECT",
        "id, instance_id, setup_session_id, owner_principal_id, native_identity_id, "
        "policy_key, claim_provenance, idempotency_key_digest, intent_digest, "
        "correlation_id, created_at",
    ),
    (
        "platform_installation_claim_facts",
        "INSERT",
        "instance_id, setup_session_id, owner_principal_id, native_identity_id, "
        "policy_key, claim_provenance, idempotency_key_digest, intent_digest, correlation_id",
    ),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE TABLE request_engine.platform_owner_policies (
            policy_key text PRIMARY KEY,
            revision integer NOT NULL CHECK (revision > 0),
            grants jsonb NOT NULL CHECK (
                jsonb_typeof(grants) = 'array' AND jsonb_array_length(grants) > 0
            )
        );
        ALTER TABLE request_engine.platform_owner_policies
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_owner_policies
            FROM PUBLIC, request_engine_app, request_engine_worker;
        CREATE TRIGGER platform_owner_policy_immutable
            BEFORE UPDATE OR DELETE ON request_engine.platform_owner_policies
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        INSERT INTO request_engine.platform_owner_policies (policy_key, revision, grants)
        VALUES (
            'platform-owner-v1',
            1,
            '[
                {"capability_key": "platform.principal.provision", "delegable": true},
                {"capability_key": "platform.tenant_provisioner.provision", "delegable": true},
                {"capability_key": "platform.recovery_operator.provision", "delegable": false},
                {"capability_key": "organization.provision", "delegable": true},
                {"capability_key": "platform.identity.recover", "delegable": false},
                {"capability_key": "platform.identity.read", "delegable": false},
                {"capability_key": "platform.identity.recovery_approve", "delegable": false},
                {"capability_key": "platform.provisioner.read", "delegable": false},
                {"capability_key": "platform.provisioner.manage_lifecycle", "delegable": false}
            ]'::jsonb
        );

        CREATE TABLE request_engine.setup_pending_identity (
            id uuid PRIMARY KEY,
            setup_session_id uuid NOT NULL UNIQUE
                REFERENCES request_engine.setup_sessions(id),
            login_handle text NOT NULL,
            verifier text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            promoted_at timestamptz,
            CONSTRAINT setup_pending_identity_status_check CHECK (
                status IN ('pending', 'promoted')
            ),
            CONSTRAINT setup_pending_identity_handle_check CHECK (
                length(btrim(login_handle)) BETWEEN 1 AND 320
            ),
            CONSTRAINT setup_pending_identity_verifier_check CHECK (
                length(verifier) > 32
                AND (verifier LIKE 'scrypt$%' OR verifier LIKE '$argon2id$%')
            ),
            CONSTRAINT setup_pending_identity_terminal_check CHECK (
                (status = 'pending' AND promoted_at IS NULL)
                OR (status = 'promoted' AND promoted_at IS NOT NULL)
            )
        );
        ALTER TABLE request_engine.setup_pending_identity
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.setup_pending_identity FROM PUBLIC;

        CREATE TABLE request_engine.setup_pending_webauthn_credential (
            id uuid PRIMARY KEY,
            setup_session_id uuid NOT NULL
                REFERENCES request_engine.setup_sessions(id),
            credential_id bytea NOT NULL,
            public_key bytea NOT NULL,
            sign_count bigint NOT NULL DEFAULT 0,
            aaguid text NOT NULL,
            backup_eligible boolean NOT NULL DEFAULT false,
            backup_state boolean NOT NULL DEFAULT false,
            user_verified boolean NOT NULL DEFAULT true,
            status text NOT NULL DEFAULT 'pending',
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            promoted_at timestamptz,
            CONSTRAINT setup_pending_webauthn_status_check CHECK (
                status IN ('pending', 'promoted')
            ),
            CONSTRAINT setup_pending_webauthn_credential_check CHECK (
                octet_length(credential_id) BETWEEN 16 AND 1023
            ),
            CONSTRAINT setup_pending_webauthn_key_check CHECK (octet_length(public_key) > 0),
            CONSTRAINT setup_pending_webauthn_sign_check CHECK (sign_count >= 0),
            CONSTRAINT setup_pending_webauthn_aaguid_check CHECK (aaguid ~ '^[0-9a-f]{32}$'),
            CONSTRAINT setup_pending_webauthn_terminal_check CHECK (
                (status = 'pending' AND promoted_at IS NULL)
                OR (status = 'promoted' AND promoted_at IS NOT NULL)
            ),
            UNIQUE (credential_id)
        );
        CREATE INDEX setup_pending_webauthn_session_idx
            ON request_engine.setup_pending_webauthn_credential (setup_session_id)
            WHERE status = 'pending';
        ALTER TABLE request_engine.setup_pending_webauthn_credential
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.setup_pending_webauthn_credential FROM PUBLIC;

        CREATE TABLE request_engine.platform_installation_claim_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            instance_id uuid NOT NULL,
            setup_session_id uuid NOT NULL,
            owner_principal_id uuid NOT NULL,
            native_identity_id uuid NOT NULL,
            policy_key text NOT NULL,
            claim_provenance text NOT NULL,
            idempotency_key_digest text NOT NULL,
            intent_digest text NOT NULL,
            correlation_id uuid,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT platform_installation_claim_key_check CHECK (
                idempotency_key_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT platform_installation_claim_intent_check CHECK (
                intent_digest ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT platform_installation_claim_provenance_check CHECK (
                length(btrim(claim_provenance)) BETWEEN 1 AND 500
            ),
            UNIQUE (instance_id),
            UNIQUE (idempotency_key_digest)
        );
        ALTER TABLE request_engine.platform_installation_claim_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.platform_installation_claim_facts FROM PUBLIC;
        CREATE TRIGGER platform_installation_claim_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.platform_installation_claim_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_platform.set_setup_pending_identity(
            p_native_identity_id uuid,
            p_setup_session_id uuid,
            p_login_handle text,
            p_verifier text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_usable boolean;
        BEGIN
            IF p_native_identity_id IS NULL
               OR p_setup_session_id IS NULL
               OR p_login_handle IS NULL
               OR length(btrim(p_login_handle)) NOT BETWEEN 1 AND 320
               OR p_verifier IS NULL
               OR length(p_verifier) <= 32
               OR NOT (p_verifier LIKE 'scrypt$%' OR p_verifier LIKE '$argon2id$%')
            THEN
                RETURN false;
            END IF;

            SELECT (session.status = 'pending'
                    AND session.expires_at > clock_timestamp()
                    AND instance.state = 'unclaimed')
              INTO v_usable
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = p_setup_session_id;
            IF v_usable IS NOT TRUE THEN
                RETURN false;
            END IF;

            IF EXISTS (
                SELECT 1 FROM request_engine.setup_pending_identity
                 WHERE setup_session_id = p_setup_session_id
            ) THEN
                UPDATE request_engine.setup_pending_identity
                   SET login_handle = btrim(p_login_handle),
                       verifier = p_verifier
                 WHERE setup_session_id = p_setup_session_id
                   AND status = 'pending';
                RETURN FOUND;
            END IF;

            INSERT INTO request_engine.setup_pending_identity (
                id, setup_session_id, login_handle, verifier
            ) VALUES (
                p_native_identity_id, p_setup_session_id, btrim(p_login_handle), p_verifier
            );
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_platform.read_setup_pending_identity(
            p_setup_session_id uuid
        )
        RETURNS TABLE (
            native_identity_id uuid,
            login_handle text,
            status text
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT identity.id, identity.login_handle, identity.status
              FROM request_engine.setup_pending_identity AS identity
             WHERE identity.setup_session_id = p_setup_session_id
        $$;

        CREATE FUNCTION request_auth.finalize_setup_webauthn_registration(
            p_challenge_digest bytea,
            p_credential_row_id uuid,
            p_credential_id_bytes bytea,
            p_public_key bytea,
            p_sign_count bigint,
            p_aaguid text,
            p_backup_eligible boolean,
            p_backup_state boolean,
            p_user_verified boolean
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_setup_status text;
            v_instance_state text;
            v_expires_at timestamptz;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_credential_id_bytes IS NULL
               OR octet_length(p_credential_id_bytes) NOT BETWEEN 16 AND 1023
               OR p_public_key IS NULL
               OR octet_length(p_public_key) = 0
               OR p_sign_count < 0
               OR p_aaguid IS NULL
               OR p_aaguid !~ '^[0-9a-f]{32}$'
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'registration'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND OR v_challenge.setup_session_id IS NULL THEN
                RETURN false;
            END IF;

            SELECT session.status, session.expires_at, instance.state
              INTO v_setup_status, v_expires_at, v_instance_state
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = v_challenge.setup_session_id
             FOR UPDATE OF session;
            IF NOT FOUND
               OR v_setup_status <> 'pending'
               OR v_expires_at <= clock_timestamp()
               OR v_instance_state <> 'unclaimed'
            THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.setup_pending_webauthn_credential (
                id, setup_session_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            ) VALUES (
                p_credential_row_id, v_challenge.setup_session_id, p_credential_id_bytes,
                p_public_key, p_sign_count, p_aaguid, p_backup_eligible,
                p_backup_state, p_user_verified
            )
            ON CONFLICT (credential_id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $$;

        CREATE FUNCTION request_platform.read_claim_readiness(
            p_setup_session_id uuid
        )
        RETURNS TABLE (
            setup_status text,
            setup_usable boolean,
            instance_state text,
            has_identity boolean,
            verified_webauthn_count integer,
            has_recovery_codes boolean,
            policy_key text
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT session.status,
                   (session.status = 'pending'
                    AND session.expires_at > clock_timestamp()
                    AND instance.state = 'unclaimed'),
                   instance.state,
                   EXISTS (
                       SELECT 1 FROM request_engine.setup_pending_identity AS identity
                        WHERE identity.setup_session_id = session.id
                          AND identity.status = 'pending'
                   ),
                   (
                       SELECT count(*)::integer
                         FROM request_engine.setup_pending_webauthn_credential AS credential
                        WHERE credential.setup_session_id = session.id
                          AND credential.status = 'pending'
                          AND credential.user_verified
                   ),
                   EXISTS (
                       SELECT 1 FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.setup_session_id = session.id
                          AND code_set.status = 'active'
                   ),
                   'platform-owner-v1'
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = p_setup_session_id
        $$;

        CREATE FUNCTION request_platform.read_installation_claim(
            p_idempotency_key_digest text
        )
        RETURNS TABLE (
            instance_id uuid,
            owner_principal_id uuid,
            native_identity_id uuid,
            setup_session_id uuid,
            policy_key text,
            claim_provenance text,
            intent_digest text,
            claimed_at timestamptz
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
            SELECT fact.instance_id,
                   fact.owner_principal_id,
                   fact.native_identity_id,
                   fact.setup_session_id,
                   fact.policy_key,
                   fact.claim_provenance,
                   fact.intent_digest,
                   fact.created_at
              FROM request_engine.platform_installation_claim_facts AS fact
             WHERE fact.idempotency_key_digest = p_idempotency_key_digest
        $$;

        CREATE FUNCTION request_platform.finalize_instance_claim(
            p_setup_session_id uuid,
            p_idempotency_key_digest text,
            p_intent_digest text,
            p_claim_provenance text,
            p_actor_authentication_method text,
            p_correlation_id uuid
        )
        RETURNS TABLE (
            instance_id uuid,
            owner_principal_id uuid,
            native_identity_id uuid,
            setup_session_id uuid,
            policy_key text
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
        AS $$
        DECLARE
            v_instance request_engine.platform_instance%ROWTYPE;
            v_session request_engine.setup_sessions%ROWTYPE;
            v_identity request_engine.setup_pending_identity%ROWTYPE;
            v_verified_count integer;
            v_policy request_engine.platform_owner_policies%ROWTYPE;
            v_principal_id uuid;
            v_binding_id uuid;
            v_replay request_engine.platform_installation_claim_facts%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();

            IF p_setup_session_id IS NULL
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
               OR p_claim_provenance IS NULL
               OR length(btrim(p_claim_provenance)) NOT BETWEEN 1 AND 500
            THEN
                RAISE EXCEPTION 'Instance claim request is invalid' USING ERRCODE = '22023';
            END IF;

            -- Serialization root: the singleton instance row.
            SELECT instance.* INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform instance is not initialized' USING ERRCODE = '55000';
            END IF;

            IF v_instance.state = 'claimed' THEN
                SELECT fact.* INTO v_replay
                  FROM request_engine.platform_installation_claim_facts AS fact
                 WHERE fact.idempotency_key_digest = p_idempotency_key_digest;
                IF FOUND AND v_replay.intent_digest = p_intent_digest THEN
                    RETURN QUERY SELECT v_replay.instance_id, v_replay.owner_principal_id,
                                        v_replay.native_identity_id,
                                        v_replay.setup_session_id, v_replay.policy_key;
                    RETURN;
                END IF;
                RAISE EXCEPTION 'Instance is already claimed' USING ERRCODE = '55000';
            END IF;

            SELECT session.* INTO v_session
              FROM request_engine.setup_sessions AS session
             WHERE session.id = p_setup_session_id;
            IF NOT FOUND
               OR v_session.status <> 'pending'
               OR v_session.expires_at <= clock_timestamp()
               OR v_session.instance_id <> v_instance.id
            THEN
                RAISE EXCEPTION 'Setup session is not usable' USING ERRCODE = '55000';
            END IF;

            SELECT identity.* INTO v_identity
              FROM request_engine.setup_pending_identity AS identity
             WHERE identity.setup_session_id = p_setup_session_id;
            IF NOT FOUND OR v_identity.status <> 'pending' THEN
                RAISE EXCEPTION 'Setup has no pending identity' USING ERRCODE = '55000';
            END IF;

            SELECT count(*)::integer INTO v_verified_count
              FROM request_engine.setup_pending_webauthn_credential AS credential
             WHERE credential.setup_session_id = p_setup_session_id
               AND credential.status = 'pending'
               AND credential.user_verified;
            IF v_verified_count < 1 THEN
                RAISE EXCEPTION 'Setup requires a verified WebAuthn authenticator'
                    USING ERRCODE = '55000';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.setup_session_id = p_setup_session_id
                   AND code_set.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Setup requires recovery codes' USING ERRCODE = '55000';
            END IF;

            SELECT policy.* INTO v_policy
              FROM request_engine.platform_owner_policies AS policy
             WHERE policy.policy_key = 'platform-owner-v1';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform owner policy is missing' USING ERRCODE = '55000';
            END IF;

            v_principal_id := gen_random_uuid();
            v_binding_id := gen_random_uuid();

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                v_identity.id, v_instance.built_in_native_authority_id,
                v_identity.login_handle
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                gen_random_uuid(), v_identity.id, v_identity.verifier
            );
            INSERT INTO request_engine.webauthn_credentials (
                id, native_identity_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            )
            SELECT gen_random_uuid(), v_identity.id, credential.credential_id,
                   credential.public_key, credential.sign_count, credential.aaguid,
                   credential.backup_eligible, credential.backup_state,
                   credential.user_verified
              FROM request_engine.setup_pending_webauthn_credential AS credential
             WHERE credential.setup_session_id = p_setup_session_id
               AND credential.status = 'pending';

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                v_principal_id, 'platform', 'human', 'instance-claim:' || v_identity.id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id, subject_id, status
            ) VALUES (
                v_binding_id, v_principal_id, 'platform',
                v_instance.built_in_native_authority_id, v_identity.id::text, 'active'
            );
            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT v_principal_id, 'platform', 'platform',
                   grant_item ->> 'capability_key',
                   coalesce((grant_item ->> 'delegable')::boolean, false),
                   'trust_bootstrap',
                   'instance-claim:' || v_instance.id::text || ':' || btrim(p_claim_provenance)
              FROM jsonb_array_elements(v_policy.grants) AS grant_item;

            UPDATE request_engine.recovery_code_sets AS code_set
               SET setup_session_id = NULL,
                   native_identity_id = v_identity.id
             WHERE code_set.setup_session_id = p_setup_session_id
               AND code_set.status = 'active';

            UPDATE request_engine.setup_pending_identity
               SET status = 'promoted', promoted_at = clock_timestamp()
             WHERE id = v_identity.id;
            UPDATE request_engine.setup_pending_webauthn_credential AS credential
               SET status = 'promoted', promoted_at = clock_timestamp()
             WHERE credential.setup_session_id = p_setup_session_id
               AND credential.status = 'pending';

            UPDATE request_engine.setup_sessions
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_setup_session_id;

            UPDATE request_engine.platform_instance
               SET state = 'claimed',
                   revision = revision + 1,
                   claimed_at = clock_timestamp(),
                   initial_owner_principal_id = v_principal_id,
                   claim_provenance = btrim(p_claim_provenance)
             WHERE singleton_key = 1;

            INSERT INTO request_engine.platform_installation_claim_facts (
                instance_id, setup_session_id, owner_principal_id, native_identity_id,
                policy_key, claim_provenance, idempotency_key_digest, intent_digest,
                correlation_id
            ) VALUES (
                v_instance.id, p_setup_session_id, v_principal_id, v_identity.id,
                v_policy.policy_key, btrim(p_claim_provenance), p_idempotency_key_digest,
                p_intent_digest, p_correlation_id
            );

            RETURN QUERY SELECT v_instance.id, v_principal_id, v_identity.id,
                                p_setup_session_id, v_policy.policy_key;
        END
        $$;
        """
    )

    for signature in _DEFINER_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {_RUNTIME}")

    for signature in _APP_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO request_engine_schema_owner")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO request_engine_app")

    for table, privilege, columns in _COLUMN_GRANTS:
        op.execute(f"GRANT {privilege} ({columns}) ON request_engine.{table} TO {_DEFINER}")


def downgrade() -> None:
    raise RuntimeError("Instance claim state is append-preserving; roll forward")
