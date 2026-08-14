BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- A claim token is authoritative only while its lease is live. Before this
-- hardening, an expired worker could still complete/retry/dead-letter work in
-- the interval after lease expiry but before another worker reclaimed it.
-- Every worker-side terminal/retry mutation now fences on the PostgreSQL clock.
-- Retry paths validate the live lease with SELECT ... FOR UPDATE. That row lock
-- is the linearization point; after it succeeds, no reclaimer can become owner
-- until the retry transition commits, so the UPDATE must not re-read the clock.

CREATE OR REPLACE FUNCTION request_cmd.complete_scheduled_action(
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
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.retry_scheduled_action(
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
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;

    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN p_next_attempt_at
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.retry_scheduled_action_after(
    p_action_id uuid,
    p_claim_token uuid,
    p_delay interval,
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
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.dead_letter_scheduled_action(
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
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.complete_outbox_message(
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
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.retry_outbox_message(
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
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN p_next_attempt_at
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.retry_outbox_message_after(
    p_message_id uuid,
    p_claim_token uuid,
    p_delay interval,
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
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.outbox_messages
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.dead_letter_outbox_message(
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
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.complete_provider_event(
    p_provider_event_row_id uuid,
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
    UPDATE request_engine.provider_events
       SET status = 'processed',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = clock_timestamp(),
           last_error_class = NULL,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.retry_provider_event_after(
    p_provider_event_row_id uuid,
    p_claim_token uuid,
    p_delay interval,
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
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.provider_events
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'received' END;
    UPDATE request_engine.provider_events
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'received' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token;

    RETURN v_status;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.reject_provider_event(
    p_provider_event_row_id uuid,
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
    UPDATE request_engine.provider_events
       SET status = 'rejected',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = clock_timestamp(),
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.dead_letter_provider_event(
    p_provider_event_row_id uuid,
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
    UPDATE request_engine.provider_events
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

RESET ROLE;
COMMIT;
