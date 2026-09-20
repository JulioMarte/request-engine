"""Durable asynchronous delivery for verified Native HUMAN recovery.

Revision ID: 0078_native_recovery_delivery
Revises: 0077_recovery_addr_throttle

Public recovery requests enqueue database-only work. A fenced worker later
creates the one-time proof, stages plaintext in the configured technical secret
store and publishes through the delivery provider. PostgreSQL retains only
digest/reference metadata and never the raw proof.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0078_native_recovery_delivery"
down_revision: str | Sequence[str] | None = "0077_recovery_addr_throttle"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        r"""
        CREATE TABLE request_engine.native_recovery_delivery_requests (
            id uuid PRIMARY KEY,
            native_identity_id uuid NOT NULL
                REFERENCES request_engine.native_identities(id),
            recovery_address_id uuid NOT NULL
                REFERENCES request_engine.native_recovery_addresses(id),
            destination_reference text NOT NULL,
            status text NOT NULL DEFAULT 'pending',
            generation integer NOT NULL DEFAULT 0,
            recovery_intent_id uuid
                REFERENCES request_engine.native_recovery_intents(id),
            secret_reference text,
            secret_digest text,
            proof_expires_at timestamptz,
            request_expires_at timestamptz NOT NULL,
            claim_token uuid,
            lease_until timestamptz,
            attempt_count integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 8,
            next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            last_error_class text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            delivered_at timestamptz,
            CONSTRAINT native_recovery_delivery_requests_status_check
                CHECK (status IN (
                    'pending', 'sending', 'delivered',
                    'unknown', 'failed', 'cancelled'
                )),
            CONSTRAINT native_recovery_delivery_requests_generation_check
                CHECK (generation >= 0),
            CONSTRAINT native_recovery_delivery_requests_destination_check
                CHECK (length(btrim(destination_reference)) BETWEEN 3 AND 320),
            CONSTRAINT native_recovery_delivery_requests_expiry_check
                CHECK (request_expires_at > created_at),
            CONSTRAINT native_recovery_delivery_requests_attempts_check
                CHECK (attempt_count >= 0 AND max_attempts BETWEEN 1 AND 100),
            CONSTRAINT native_recovery_delivery_requests_lease_check CHECK (
                (status = 'sending' AND claim_token IS NOT NULL AND lease_until IS NOT NULL)
                OR (status <> 'sending' AND claim_token IS NULL AND lease_until IS NULL)
            ),
            CONSTRAINT native_recovery_delivery_requests_secret_check CHECK (
                (
                    secret_reference IS NULL
                    AND secret_digest IS NULL
                    AND recovery_intent_id IS NULL
                    AND proof_expires_at IS NULL
                )
                OR (
                    secret_reference IS NOT NULL
                    AND length(btrim(secret_reference)) BETWEEN 1 AND 400
                    AND secret_digest ~ '^[0-9a-f]{64}$'
                    AND recovery_intent_id IS NOT NULL
                    AND proof_expires_at IS NOT NULL
                )
            )
        );
        ALTER TABLE request_engine.native_recovery_delivery_requests
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_recovery_delivery_requests
            FROM PUBLIC, request_engine_app, request_engine_worker;
        CREATE INDEX native_recovery_delivery_requests_claim_idx
            ON request_engine.native_recovery_delivery_requests
            (next_attempt_at, id)
            WHERE status = 'pending';
        CREATE INDEX native_recovery_delivery_requests_identity_idx
            ON request_engine.native_recovery_delivery_requests
            (native_identity_id, created_at DESC);

        CREATE TABLE request_engine.native_recovery_delivery_facts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            request_id uuid NOT NULL
                REFERENCES request_engine.native_recovery_delivery_requests(id),
            native_identity_id uuid NOT NULL,
            recovery_address_id uuid NOT NULL,
            generation integer NOT NULL,
            event_kind text NOT NULL,
            error_class text,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            CONSTRAINT native_recovery_delivery_facts_generation_check
                CHECK (generation >= 0),
            CONSTRAINT native_recovery_delivery_facts_kind_check CHECK (
                event_kind IN (
                    'staged', 'retry_scheduled', 'delivered',
                    'delivery_unknown', 'delivery_failed'
                )
            ),
            CONSTRAINT native_recovery_delivery_facts_error_check
                CHECK (
                    error_class IS NULL
                    OR length(btrim(error_class)) BETWEEN 1 AND 80
                )
        );
        ALTER TABLE request_engine.native_recovery_delivery_facts
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON request_engine.native_recovery_delivery_facts
            FROM PUBLIC, request_engine_app, request_engine_worker;
        CREATE TRIGGER native_recovery_delivery_facts_append_only
            BEFORE DELETE OR UPDATE ON request_engine.native_recovery_delivery_facts
            FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.queue_native_verified_recovery(
            p_identity_authority_id uuid,
            p_login_handle text,
            p_request_id uuid
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_identity_id uuid;
            v_address record;
        BEGIN
            IF p_identity_authority_id IS NULL
               OR p_login_handle IS NULL
               OR length(p_login_handle) NOT BETWEEN 1 AND 320
               OR p_request_id IS NULL
            THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = p_identity_authority_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT identity.id
              INTO v_identity_id
              FROM request_engine.native_identities AS identity
             WHERE identity.identity_authority_id = p_identity_authority_id
               AND identity.login_handle = p_login_handle
               AND identity.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT address.id, address.normalized_address
              INTO v_address
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = v_identity_id
               AND address.kind = 'email'
               AND address.status = 'verified'
             ORDER BY address.verified_at DESC, address.id
             LIMIT 1
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'cancelled',
                   updated_at = clock_timestamp(),
                   last_error_class = 'request_expired'
             WHERE request.native_identity_id = v_identity_id
               AND request.status = 'pending'
               AND request.request_expires_at <= clock_timestamp();

            IF EXISTS (
                SELECT 1
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.native_identity_id = v_identity_id
                   AND request.status IN ('pending', 'sending')
            ) THEN
                RETURN false;
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.native_recovery_address_facts AS fact
                 WHERE fact.native_identity_id = v_identity_id
                   AND fact.recovery_address_id = v_address.id
                   AND fact.event_kind = 'recovery_requested'
                   AND fact.created_at > clock_timestamp() - interval '1 minute'
            ) THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_requests (
                id,
                native_identity_id,
                recovery_address_id,
                destination_reference,
                request_expires_at
            ) VALUES (
                p_request_id,
                v_identity_id,
                v_address.id,
                v_address.normalized_address,
                clock_timestamp() + interval '30 minutes'
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address.id,
                'recovery_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;
        ALTER FUNCTION request_auth.queue_native_verified_recovery(uuid, text, uuid)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
            request_auth.queue_native_verified_recovery(uuid, text, uuid)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            request_auth.queue_native_verified_recovery(uuid, text, uuid)
            TO request_engine_app;

        REVOKE EXECUTE ON FUNCTION
            request_auth.create_native_recovery_intent_for_verified_address(
                uuid, text, uuid, bytea, text, timestamptz
            ) FROM request_engine_app;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.claim_native_recovery_delivery_requests(
            p_limit integer,
            p_lease_seconds integer
        )
        RETURNS TABLE (
            request_id uuid,
            native_identity_id uuid,
            recovery_address_id uuid,
            generation integer,
            recovery_intent_id uuid,
            secret_reference text,
            secret_digest text,
            destination_reference text,
            proof_expires_at timestamptz,
            attempt_count integer,
            claim_token uuid
        )
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_expired record;
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Native recovery delivery claim limit is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF p_lease_seconds IS NULL OR p_lease_seconds < 1 OR p_lease_seconds > 900 THEN
                RAISE EXCEPTION 'Native recovery delivery lease is invalid'
                    USING ERRCODE = '22023';
            END IF;

            -- A process may disappear after claiming but before it can retry or
            -- finalize. Expired leases are therefore made claimable again under a
            -- new fencing token; staged proof metadata, when present, is retained so
            -- the next worker reconciles/publishes the same proof rather than minting
            -- another one.
            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'pending',
                   claim_token = NULL,
                   lease_until = NULL,
                   next_attempt_at = clock_timestamp(),
                   last_error_class = 'lease_expired',
                   updated_at = clock_timestamp()
             WHERE request.status = 'sending'
               AND request.lease_until <= clock_timestamp();

            FOR v_expired IN
                SELECT request.id,
                       request.native_identity_id,
                       request.recovery_address_id,
                       request.generation,
                       request.recovery_intent_id,
                       CASE
                           WHEN request.request_expires_at <= clock_timestamp()
                           THEN 'request_expired'
                           ELSE 'attempts_exhausted'
                       END AS error_class
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.status = 'pending'
                   AND (
                       request.request_expires_at <= clock_timestamp()
                       OR request.attempt_count >= request.max_attempts
                   )
                 ORDER BY request.id
                 FOR UPDATE SKIP LOCKED
            LOOP
                IF v_expired.recovery_intent_id IS NOT NULL THEN
                    UPDATE request_engine.native_recovery_intents AS intent
                       SET status = 'revoked',
                           revoked_at = clock_timestamp()
                     WHERE intent.id = v_expired.recovery_intent_id
                       AND intent.status = 'pending';
                END IF;
                UPDATE request_engine.native_recovery_delivery_requests AS request
                   SET status = 'failed',
                       last_error_class = v_expired.error_class,
                       updated_at = clock_timestamp()
                 WHERE request.id = v_expired.id;
                INSERT INTO request_engine.native_recovery_delivery_facts (
                    request_id,
                    native_identity_id,
                    recovery_address_id,
                    generation,
                    event_kind,
                    error_class
                ) VALUES (
                    v_expired.id,
                    v_expired.native_identity_id,
                    v_expired.recovery_address_id,
                    v_expired.generation,
                    'delivery_failed',
                    v_expired.error_class
                );
            END LOOP;

            RETURN QUERY
            WITH candidate AS (
                SELECT request.id
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.status = 'pending'
                   AND request.next_attempt_at <= clock_timestamp()
                   AND request.request_expires_at > clock_timestamp()
                   AND request.attempt_count < request.max_attempts
                 ORDER BY request.next_attempt_at, request.id
                 LIMIT p_limit
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'sending',
                   generation = CASE
                       WHEN request.secret_reference IS NULL
                       THEN request.generation + 1
                       ELSE request.generation
                   END,
                   claim_token = uuidv7(),
                   lease_until = clock_timestamp()
                       + make_interval(secs => p_lease_seconds),
                   attempt_count = request.attempt_count + 1,
                   updated_at = clock_timestamp()
              FROM candidate
             WHERE request.id = candidate.id
            RETURNING request.id,
                      request.native_identity_id,
                      request.recovery_address_id,
                      request.generation,
                      request.recovery_intent_id,
                      request.secret_reference,
                      request.secret_digest,
                      request.destination_reference,
                      request.proof_expires_at,
                      request.attempt_count,
                      request.claim_token;
        END
        $$;
        ALTER FUNCTION request_auth.claim_native_recovery_delivery_requests(integer, integer)
            OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION
            request_auth.claim_native_recovery_delivery_requests(integer, integer)
            FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION
            request_auth.claim_native_recovery_delivery_requests(integer, integer)
            TO request_engine_worker;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.activate_native_recovery_delivery_request(
            p_request_id uuid,
            p_claim_token uuid,
            p_generation integer,
            p_recovery_id uuid,
            p_token_digest bytea,
            p_token_fingerprint text,
            p_proof_expires_at timestamptz,
            p_secret_reference text,
            p_secret_digest text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_identity_id uuid;
            v_address_id uuid;
            v_destination text;
            v_identity_status text;
        BEGIN
            IF p_request_id IS NULL
               OR p_claim_token IS NULL
               OR p_generation IS NULL OR p_generation < 1
               OR p_recovery_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_proof_expires_at IS NULL
               OR p_proof_expires_at <= clock_timestamp()
               OR p_proof_expires_at > clock_timestamp() + interval '30 minutes'
               OR p_secret_reference IS NULL
               OR length(btrim(p_secret_reference)) NOT BETWEEN 1 AND 400
               OR p_secret_digest !~ '^[0-9a-f]{64}$'
            THEN
                RETURN false;
            END IF;

            SELECT request.native_identity_id
              INTO v_identity_id
              FROM request_engine.native_recovery_delivery_requests AS request
             WHERE request.id = p_request_id;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT request.recovery_address_id,
                   request.destination_reference
              INTO v_address_id, v_destination
              FROM request_engine.native_recovery_delivery_requests AS request
             WHERE request.id = p_request_id
               AND request.native_identity_id = v_identity_id
               AND request.status = 'sending'
               AND request.claim_token = p_claim_token
               AND request.generation = p_generation
               AND request.secret_reference IS NULL
               AND request.request_expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.id = v_address_id
               AND address.native_identity_id = v_identity_id
               AND address.status = 'verified'
               AND address.normalized_address = v_destination
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF NOT request_auth.create_native_recovery_intent(
                v_identity_id,
                p_recovery_id,
                p_token_digest,
                p_token_fingerprint,
                p_proof_expires_at
            ) THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET recovery_intent_id = p_recovery_id,
                   secret_reference = btrim(p_secret_reference),
                   secret_digest = p_secret_digest,
                   proof_expires_at = p_proof_expires_at,
                   updated_at = clock_timestamp()
             WHERE request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending';

            INSERT INTO request_engine.native_recovery_delivery_facts (
                request_id,
                native_identity_id,
                recovery_address_id,
                generation,
                event_kind
            ) VALUES (
                p_request_id,
                v_identity_id,
                v_address_id,
                p_generation,
                'staged'
            );
            RETURN true;
        END
        $$;
        ALTER FUNCTION request_auth.activate_native_recovery_delivery_request(
            uuid, uuid, integer, uuid, bytea, text, timestamptz, text, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.activate_native_recovery_delivery_request(
            uuid, uuid, integer, uuid, bytea, text, timestamptz, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.activate_native_recovery_delivery_request(
            uuid, uuid, integer, uuid, bytea, text, timestamptz, text, text
        ) TO request_engine_worker;
        """
    )

    op.execute(
        r"""
        CREATE FUNCTION request_auth.complete_native_recovery_delivery_request(
            p_request_id uuid,
            p_claim_token uuid,
            p_outcome text,
            p_error_class text
        ) RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_row record;
        BEGIN
            IF p_request_id IS NULL
               OR p_claim_token IS NULL
               OR p_outcome NOT IN ('delivered', 'unknown', 'failed')
               OR (
                   p_error_class IS NOT NULL
                   AND length(btrim(p_error_class)) NOT BETWEEN 1 AND 80
               )
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = p_outcome,
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = CASE
                       WHEN p_outcome = 'delivered' THEN NULL
                       ELSE btrim(p_error_class)
                   END,
                   delivered_at = CASE
                       WHEN p_outcome = 'delivered' THEN clock_timestamp()
                       ELSE request.delivered_at
                   END,
                   updated_at = clock_timestamp()
             WHERE request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending'
            RETURNING request.native_identity_id,
                      request.recovery_address_id,
                      request.generation,
                      request.recovery_intent_id
                 INTO v_row;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF p_outcome = 'failed' AND v_row.recovery_intent_id IS NOT NULL THEN
                UPDATE request_engine.native_recovery_intents AS intent
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE intent.id = v_row.recovery_intent_id
                   AND intent.status = 'pending';
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_facts (
                request_id,
                native_identity_id,
                recovery_address_id,
                generation,
                event_kind,
                error_class
            ) VALUES (
                p_request_id,
                v_row.native_identity_id,
                v_row.recovery_address_id,
                v_row.generation,
                CASE p_outcome
                    WHEN 'delivered' THEN 'delivered'
                    WHEN 'unknown' THEN 'delivery_unknown'
                    ELSE 'delivery_failed'
                END,
                CASE WHEN p_outcome = 'delivered' THEN NULL ELSE btrim(p_error_class) END
            );
            RETURN true;
        END
        $$;
        ALTER FUNCTION request_auth.complete_native_recovery_delivery_request(
            uuid, uuid, text, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.complete_native_recovery_delivery_request(
            uuid, uuid, text, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.complete_native_recovery_delivery_request(
            uuid, uuid, text, text
        ) TO request_engine_worker;

        CREATE FUNCTION request_auth.retry_native_recovery_delivery_request(
            p_request_id uuid,
            p_claim_token uuid,
            p_delay_seconds integer,
            p_error_class text
        ) RETURNS text
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
        DECLARE
            v_row record;
            v_next_status text;
        BEGIN
            IF p_request_id IS NULL
               OR p_claim_token IS NULL
               OR p_delay_seconds IS NULL
               OR p_delay_seconds < 0 OR p_delay_seconds > 86400
               OR p_error_class IS NULL
               OR length(btrim(p_error_class)) NOT BETWEEN 1 AND 80
            THEN
                RETURN 'stale';
            END IF;

            SELECT request.native_identity_id,
                   request.recovery_address_id,
                   request.generation,
                   request.recovery_intent_id,
                   request.attempt_count,
                   request.max_attempts,
                   request.request_expires_at
              INTO v_row
              FROM request_engine.native_recovery_delivery_requests AS request
             WHERE request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN 'stale';
            END IF;

            v_next_status := CASE
                WHEN v_row.attempt_count >= v_row.max_attempts
                  OR v_row.request_expires_at <= clock_timestamp()
                THEN 'failed'
                ELSE 'pending'
            END;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = v_next_status,
                   next_attempt_at = clock_timestamp()
                       + make_interval(secs => p_delay_seconds),
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = btrim(p_error_class),
                   updated_at = clock_timestamp()
             WHERE request.id = p_request_id;

            IF v_next_status = 'failed' AND v_row.recovery_intent_id IS NOT NULL THEN
                UPDATE request_engine.native_recovery_intents AS intent
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE intent.id = v_row.recovery_intent_id
                   AND intent.status = 'pending';
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_facts (
                request_id,
                native_identity_id,
                recovery_address_id,
                generation,
                event_kind,
                error_class
            ) VALUES (
                p_request_id,
                v_row.native_identity_id,
                v_row.recovery_address_id,
                v_row.generation,
                CASE
                    WHEN v_next_status = 'failed' THEN 'delivery_failed'
                    ELSE 'retry_scheduled'
                END,
                btrim(p_error_class)
            );
            RETURN CASE WHEN v_next_status = 'failed' THEN 'dead' ELSE 'retry' END;
        END
        $$;
        ALTER FUNCTION request_auth.retry_native_recovery_delivery_request(
            uuid, uuid, integer, text
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.retry_native_recovery_delivery_request(
            uuid, uuid, integer, text
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.retry_native_recovery_delivery_request(
            uuid, uuid, integer, text
        ) TO request_engine_worker;

        CREATE FUNCTION request_auth.renew_native_recovery_delivery_request_lease(
            p_request_id uuid,
            p_claim_token uuid,
            p_extension_seconds integer
        ) RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path TO 'pg_catalog', 'request_engine'
        AS $$
            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET lease_until = clock_timestamp()
                   + make_interval(secs => p_extension_seconds),
                   updated_at = clock_timestamp()
             WHERE p_request_id IS NOT NULL
               AND p_claim_token IS NOT NULL
               AND p_extension_seconds BETWEEN 1 AND 900
               AND request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending'
            RETURNING true
        $$;
        ALTER FUNCTION request_auth.renew_native_recovery_delivery_request_lease(
            uuid, uuid, integer
        ) OWNER TO request_engine_schema_owner;
        REVOKE ALL ON FUNCTION request_auth.renew_native_recovery_delivery_request_lease(
            uuid, uuid, integer
        ) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION request_auth.renew_native_recovery_delivery_request_lease(
            uuid, uuid, integer
        ) TO request_engine_worker;

        GRANT USAGE ON SCHEMA request_auth TO request_engine_worker;
        """
    )


def downgrade() -> None:
    raise RuntimeError("Native recovery delivery history is roll-forward only")
