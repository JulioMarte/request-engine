BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- Tenant-scoped idempotency remains SECURITY INVOKER so RLS and the caller's
-- tenant context continue to apply.
CREATE FUNCTION request_cmd.acquire_idempotency(
    p_organization_id uuid,
    p_principal_id uuid,
    p_capability text,
    p_idempotency_key text,
    p_request_fingerprint text
)
RETURNS TABLE (
    idempotency_id uuid,
    status text,
    result_data jsonb,
    replay boolean
)
LANGUAGE plpgsql
AS $function$
DECLARE
    v_record request_engine.idempotency_records%ROWTYPE;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    INSERT INTO request_engine.idempotency_records (
        organization_id,
        principal_id,
        capability,
        idempotency_key,
        request_fingerprint
    )
    VALUES (
        p_organization_id,
        p_principal_id,
        p_capability,
        p_idempotency_key,
        p_request_fingerprint
    )
    ON CONFLICT (organization_id, principal_id, capability, idempotency_key)
    DO NOTHING;

    SELECT *
      INTO v_record
      FROM request_engine.idempotency_records i
     WHERE i.organization_id = p_organization_id
       AND i.principal_id = p_principal_id
       AND i.capability = p_capability
       AND i.idempotency_key = p_idempotency_key
     FOR UPDATE;

    IF v_record.request_fingerprint <> p_request_fingerprint THEN
        RAISE EXCEPTION 'idempotency key reused with different request fingerprint'
            USING ERRCODE = '23505';
    END IF;

    RETURN QUERY SELECT
        v_record.id,
        v_record.status,
        v_record.result_data,
        v_record.status = 'completed';
END
$function$;

CREATE FUNCTION request_cmd.complete_idempotency(
    p_idempotency_id uuid,
    p_result_data jsonb
)
RETURNS boolean
LANGUAGE plpgsql
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.idempotency_records
       SET status = 'completed',
           result_data = p_result_data,
           completed_at = clock_timestamp()
     WHERE id = p_idempotency_id
       AND organization_id = request_engine.current_organization_id()
       AND status = 'in_progress';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

-- Cross-tenant work discovery is intentionally limited to this claim surface.
-- SECURITY DEFINER functions are owned by the NOLOGIN schema owner and pin
-- search_path to trusted schemas only.
CREATE FUNCTION request_cmd.claim_scheduled_actions(
    p_limit integer,
    p_lease interval DEFAULT interval '60 seconds'
)
RETURNS TABLE (
    action_id uuid,
    organization_id uuid,
    claim_token uuid,
    owner_module text,
    action_type text,
    action_version integer,
    subject_kind text,
    subject_id uuid,
    payload jsonb,
    attempt_count integer,
    lease_until timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.scheduled_actions s
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE s.attempt_count >= s.max_attempts
       AND (
           (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
           (s.status = 'leased' AND s.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH candidates AS (
        SELECT s.id
          FROM request_engine.scheduled_actions s
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
         ORDER BY
             CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END,
             s.id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.scheduled_actions s
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = s.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE s.id = c.id
        RETURNING s.*
    )
    SELECT
        c.id,
        c.organization_id,
        c.claim_token,
        c.owner_module,
        c.action_type,
        c.action_version,
        c.subject_kind,
        c.subject_id,
        c.payload,
        c.attempt_count,
        c.lease_until
      FROM claimed c
     ORDER BY c.next_attempt_at, c.id;
END
$function$;

CREATE FUNCTION request_cmd.complete_scheduled_action(
    p_action_id uuid,
    p_claim_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.scheduled_actions
       SET status = 'completed',
           claim_token = NULL,
           lease_until = NULL,
           completed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.retry_scheduled_action(
    p_action_id uuid,
    p_claim_token uuid,
    p_next_attempt_at timestamptz,
    p_error_class text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
BEGIN
    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;

    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE WHEN v_status = 'pending' THEN p_next_attempt_at ELSE next_attempt_at END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE FUNCTION request_cmd.dead_letter_scheduled_action(
    p_action_id uuid,
    p_claim_token uuid,
    p_error_class text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.scheduled_actions
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.claim_outbox_messages(
    p_limit integer,
    p_lease interval DEFAULT interval '60 seconds'
)
RETURNS TABLE (
    message_id uuid,
    organization_id uuid,
    claim_token uuid,
    event_type text,
    schema_version integer,
    aggregate_kind text,
    aggregate_id uuid,
    payload jsonb,
    attempt_count integer,
    lease_until timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages o
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE o.attempt_count >= o.max_attempts
       AND (
           (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
           (o.status = 'leased' AND o.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH candidates AS (
        SELECT o.id
          FROM request_engine.outbox_messages o
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
         ORDER BY
             CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END,
             o.id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.outbox_messages o
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = o.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE o.id = c.id
        RETURNING o.*
    )
    SELECT
        c.id,
        c.organization_id,
        c.claim_token,
        c.event_type,
        c.schema_version,
        c.aggregate_kind,
        c.aggregate_id,
        c.payload,
        c.attempt_count,
        c.lease_until
      FROM claimed c
     ORDER BY c.next_attempt_at, c.id;
END
$function$;

CREATE FUNCTION request_cmd.complete_outbox_message(
    p_message_id uuid,
    p_claim_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.outbox_messages
       SET status = 'delivered',
           claim_token = NULL,
           lease_until = NULL,
           delivered_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.retry_outbox_message(
    p_message_id uuid,
    p_claim_token uuid,
    p_next_attempt_at timestamptz,
    p_error_class text
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
BEGIN
    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.outbox_messages
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;

    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE WHEN v_status = 'pending' THEN p_next_attempt_at ELSE next_attempt_at END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE FUNCTION request_cmd.dead_letter_outbox_message(
    p_message_id uuid,
    p_claim_token uuid,
    p_error_class text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.outbox_messages
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

RESET ROLE;
COMMIT;
