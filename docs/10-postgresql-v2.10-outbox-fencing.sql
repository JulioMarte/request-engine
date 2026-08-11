-- Request Engine V2.10 — outbox lease fencing
-- Target: PostgreSQL 18+
-- Applies after: docs/09-postgresql-v2.10-routine-hardening.sql
--
-- A worker name is diagnostic identity, not exclusive lease identity. Every
-- claim acquisition receives a fresh UUID token so a stale worker cannot ack or
-- release a message after another execution has reclaimed the lease.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog, request_engine, request_cmd, pg_temp;

ALTER TABLE request_engine.outbox_messages
    ADD COLUMN claim_token uuid;

-- Migration safety for any already-claimed rows. A token is historical/opaque;
-- workers must reacquire through claim_outbox_batch before performing a new ack.
UPDATE request_engine.outbox_messages
SET claim_token = uuidv7()
WHERE claimed_at IS NOT NULL
  AND claimed_by IS NOT NULL
  AND claim_token IS NULL;

ALTER TABLE request_engine.outbox_messages
    ADD CONSTRAINT ck_outbox_messages_claim_identity
    CHECK (
        (claimed_at IS NULL AND claimed_by IS NULL AND claim_token IS NULL)
        OR
        (claimed_at IS NOT NULL AND claimed_by IS NOT NULL AND claim_token IS NOT NULL)
    );

DROP FUNCTION request_cmd.claim_outbox_batch(text, integer, interval);

CREATE FUNCTION request_cmd.claim_outbox_batch(
    p_worker_id text,
    p_batch_size integer DEFAULT 100,
    p_lease_timeout interval DEFAULT interval '5 minutes'
)
RETURNS TABLE (
    organization_id bigint,
    outbox_message_id bigint,
    public_id uuid,
    domain_event_id bigint,
    message_type text,
    destination text,
    idempotency_key text,
    payload jsonb,
    attempt_count integer,
    available_at timestamptz,
    claimed_at timestamptz,
    claim_token uuid
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
BEGIN
    IF NULLIF(btrim(p_worker_id), '') IS NULL THEN
        RAISE EXCEPTION 'worker_id is required' USING ERRCODE = '22023';
    END IF;

    IF p_batch_size < 1 OR p_batch_size > 500 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 500' USING ERRCODE = '22023';
    END IF;

    IF p_lease_timeout IS NULL OR p_lease_timeout <= interval '0 seconds' THEN
        RAISE EXCEPTION 'lease_timeout must be positive' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH candidates AS (
        SELECT
            om.organization_id,
            om.outbox_message_id
        FROM request_engine.outbox_messages AS om
        WHERE om.delivered_at IS NULL
          AND om.available_at <= v_now
          AND (
              om.claimed_at IS NULL
              OR om.claimed_at < v_now - p_lease_timeout
          )
        ORDER BY om.available_at, om.outbox_message_id
        FOR UPDATE SKIP LOCKED
        LIMIT p_batch_size
    )
    UPDATE request_engine.outbox_messages AS om
    SET claimed_at = v_now,
        claimed_by = p_worker_id,
        claim_token = uuidv7(),
        attempt_count = om.attempt_count + 1
    FROM candidates AS c
    WHERE om.organization_id = c.organization_id
      AND om.outbox_message_id = c.outbox_message_id
    RETURNING
        om.organization_id,
        om.outbox_message_id,
        om.public_id,
        om.domain_event_id,
        om.message_type,
        om.destination,
        om.idempotency_key,
        om.payload,
        om.attempt_count,
        om.available_at,
        om.claimed_at,
        om.claim_token;
END;
$$;

COMMENT ON FUNCTION request_cmd.claim_outbox_batch(text, integer, interval) IS
'Worker-only atomic outbox lease using SKIP LOCKED. Every acquisition receives a fresh claim_token used as a fencing token.';

DROP FUNCTION request_cmd.mark_outbox_delivered(bigint, bigint, text);

CREATE FUNCTION request_cmd.mark_outbox_delivered(
    p_organization_id bigint,
    p_outbox_message_id bigint,
    p_worker_id text,
    p_claim_token uuid
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
BEGIN
    IF p_claim_token IS NULL THEN
        RAISE EXCEPTION 'claim_token is required' USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages AS om
    SET delivered_at = clock_timestamp(),
        claimed_at = NULL,
        claimed_by = NULL,
        claim_token = NULL,
        last_error = NULL
    WHERE om.organization_id = p_organization_id
      AND om.outbox_message_id = p_outbox_message_id
      AND om.delivered_at IS NULL
      AND om.claimed_by = p_worker_id
      AND om.claim_token = p_claim_token;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'outbox lease lost, message already delivered, or claim token stale'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

COMMENT ON FUNCTION request_cmd.mark_outbox_delivered(bigint, bigint, text, uuid) IS
'Acknowledges delivery only for the exact current worker lease token, fencing stale executions.';

DROP FUNCTION request_cmd.release_outbox_claim(bigint, bigint, text, text, interval);

CREATE FUNCTION request_cmd.release_outbox_claim(
    p_organization_id bigint,
    p_outbox_message_id bigint,
    p_worker_id text,
    p_claim_token uuid,
    p_error text,
    p_retry_after interval DEFAULT interval '30 seconds'
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
BEGIN
    IF p_claim_token IS NULL THEN
        RAISE EXCEPTION 'claim_token is required' USING ERRCODE = '22023';
    END IF;

    IF p_retry_after IS NULL OR p_retry_after < interval '0 seconds' THEN
        RAISE EXCEPTION 'retry_after cannot be negative' USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages AS om
    SET claimed_at = NULL,
        claimed_by = NULL,
        claim_token = NULL,
        available_at = GREATEST(om.available_at, v_now + p_retry_after),
        last_error = p_error
    WHERE om.organization_id = p_organization_id
      AND om.outbox_message_id = p_outbox_message_id
      AND om.delivered_at IS NULL
      AND om.claimed_by = p_worker_id
      AND om.claim_token = p_claim_token;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'outbox lease lost, message already delivered, or claim token stale'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

COMMENT ON FUNCTION request_cmd.release_outbox_claim(bigint, bigint, text, uuid, text, interval) IS
'Releases only the exact current outbox lease token and schedules retry, fencing stale executions.';

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA request_cmd FROM PUBLIC;

COMMIT;
