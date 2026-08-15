BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, request_admin, pg_catalog;

-- Phase 4: production worker semantics. Preserve lifetime attempt counters,
-- make operator replay explicit, and give ProviderEvent the same fenced
-- crash-recovery model as ScheduledAction and OutboxMessage.
ALTER TABLE request_engine.scheduled_actions
    ADD COLUMN replay_count integer NOT NULL DEFAULT 0,
    ADD COLUMN last_replayed_at timestamptz,
    ADD CONSTRAINT scheduled_actions_replay_count_check CHECK (replay_count >= 0);

ALTER TABLE request_engine.outbox_messages
    ADD COLUMN replay_count integer NOT NULL DEFAULT 0,
    ADD COLUMN last_replayed_at timestamptz,
    ADD CONSTRAINT outbox_messages_replay_count_check CHECK (replay_count >= 0);

ALTER TABLE request_engine.provider_events
    ADD COLUMN claim_token uuid,
    ADD COLUMN lease_until timestamptz,
    ADD COLUMN attempt_count integer NOT NULL DEFAULT 0,
    ADD COLUMN max_attempts integer NOT NULL DEFAULT 8,
    ADD COLUMN next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    ADD COLUMN last_error_class text,
    ADD COLUMN replay_count integer NOT NULL DEFAULT 0,
    ADD COLUMN last_replayed_at timestamptz,
    ADD COLUMN updated_at timestamptz NOT NULL DEFAULT clock_timestamp();

ALTER TABLE request_engine.provider_events
    DROP CONSTRAINT IF EXISTS provider_events_status_check;
ALTER TABLE request_engine.provider_events
    ADD CONSTRAINT provider_events_status_v4_check
        CHECK (status IN ('received', 'leased', 'processed', 'rejected', 'dead')),
    ADD CONSTRAINT provider_events_attempt_count_check CHECK (attempt_count >= 0),
    ADD CONSTRAINT provider_events_max_attempts_check CHECK (max_attempts > 0),
    ADD CONSTRAINT provider_events_replay_count_check CHECK (replay_count >= 0),
    ADD CONSTRAINT provider_events_lease_shape_check
        CHECK ((status = 'leased') = (claim_token IS NOT NULL AND lease_until IS NOT NULL)),
    ADD CONSTRAINT provider_events_terminal_timestamp_check
        CHECK (
            (status IN ('processed', 'rejected') AND processed_at IS NOT NULL)
            OR (status NOT IN ('processed', 'rejected') AND processed_at IS NULL)
        );

CREATE INDEX provider_events_due_idx
    ON request_engine.provider_events (next_attempt_at, id)
    WHERE status = 'received';
CREATE INDEX provider_events_reclaim_idx
    ON request_engine.provider_events (lease_until, id)
    WHERE status = 'leased';

CREATE TRIGGER provider_events_touch
BEFORE UPDATE ON request_engine.provider_events
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

-- Fair cross-tenant claiming: first due item from every tenant is considered
-- before a second item from one tenant. This prevents one hot tenant from
-- monopolizing bounded worker batches while retaining due-time ordering.
CREATE OR REPLACE FUNCTION request_cmd.claim_scheduled_actions(
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
    WITH ranked AS MATERIALIZED (
        SELECT s.id,
               s.organization_id,
               CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY s.organization_id
                   ORDER BY
                       CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END,
                       s.id
               ) AS tenant_rank
          FROM request_engine.scheduled_actions s
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
    ), candidates AS (
        SELECT s.id
          FROM ranked r
          JOIN request_engine.scheduled_actions s ON s.id = r.id
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF s SKIP LOCKED
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
    SELECT c.id,
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
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$function$;

CREATE OR REPLACE FUNCTION request_cmd.claim_outbox_messages(
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
    WITH ranked AS MATERIALIZED (
        SELECT o.id,
               o.organization_id,
               CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY o.organization_id
                   ORDER BY
                       CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END,
                       o.id
               ) AS tenant_rank
          FROM request_engine.outbox_messages o
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
    ), candidates AS (
        SELECT o.id
          FROM ranked r
          JOIN request_engine.outbox_messages o ON o.id = r.id
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF o SKIP LOCKED
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
    SELECT c.id,
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
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$function$;

CREATE FUNCTION request_cmd.renew_scheduled_action_lease(
    p_action_id uuid,
    p_claim_token uuid,
    p_extension interval DEFAULT interval '60 seconds'
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.scheduled_actions
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.renew_outbox_message_lease(
    p_message_id uuid,
    p_claim_token uuid,
    p_extension interval DEFAULT interval '60 seconds'
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.outbox_messages
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.retry_scheduled_action_after(
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
       AND claim_token = p_claim_token;
    RETURN v_status;
END
$function$;

CREATE FUNCTION request_cmd.retry_outbox_message_after(
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
       AND claim_token = p_claim_token;
    RETURN v_status;
END
$function$;

CREATE FUNCTION request_cmd.claim_provider_events(
    p_limit integer,
    p_lease interval DEFAULT interval '60 seconds'
)
RETURNS TABLE (
    provider_event_row_id uuid,
    organization_id uuid,
    claim_token uuid,
    provider_key text,
    connection_key text,
    provider_event_id text,
    payload_hash text,
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

    UPDATE request_engine.provider_events e
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE e.attempt_count >= e.max_attempts
       AND (
           (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
           (e.status = 'leased' AND e.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT e.id,
               e.organization_id,
               CASE WHEN e.status = 'received' THEN e.next_attempt_at ELSE e.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY e.organization_id
                   ORDER BY
                       CASE WHEN e.status = 'received' THEN e.next_attempt_at ELSE e.lease_until END,
                       e.id
               ) AS tenant_rank
          FROM request_engine.provider_events e
         WHERE e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
    ), candidates AS (
        SELECT e.id
          FROM ranked r
          JOIN request_engine.provider_events e ON e.id = r.id
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF e SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.provider_events e
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = e.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE e.id = c.id
        RETURNING e.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.provider_key,
           c.connection_key,
           c.provider_event_id,
           c.payload_hash,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$function$;

CREATE FUNCTION request_cmd.renew_provider_event_lease(
    p_provider_event_row_id uuid,
    p_claim_token uuid,
    p_extension interval DEFAULT interval '60 seconds'
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.provider_events
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.complete_provider_event(
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
       AND claim_token = p_claim_token;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_cmd.retry_provider_event_after(
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
       AND claim_token = p_claim_token;
    RETURN v_status;
END
$function$;

CREATE FUNCTION request_cmd.reject_provider_event(
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
       AND claim_token = p_claim_token;
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_admin.replay_dead_scheduled_action(
    p_organization_id uuid,
    p_action_id uuid,
    p_actor_principal_id uuid,
    p_additional_attempts integer,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_actor_principal_id IS NULL OR p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'actor principal and replay reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF p_additional_attempts <= 0 OR p_additional_attempts > 100 THEN
        RAISE EXCEPTION 'additional attempts must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.scheduled_actions
       SET status = 'pending',
           claim_token = NULL,
           lease_until = NULL,
           max_attempts = max_attempts + p_additional_attempts,
           next_attempt_at = clock_timestamp(),
           last_error_class = NULL,
           replay_count = replay_count + 1,
           last_replayed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_action_id
       AND status = 'dead';
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 1 THEN
        INSERT INTO request_engine.audit_records (
            organization_id, actor_principal_id, command_name,
            aggregate_kind, aggregate_id, details
        ) VALUES (
            p_organization_id, p_actor_principal_id,
            'admin.replay_scheduled_action', 'ScheduledAction', p_action_id,
            jsonb_build_object('reason', p_reason, 'additional_attempts', p_additional_attempts)
        );
    END IF;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_admin.replay_dead_outbox_message(
    p_organization_id uuid,
    p_message_id uuid,
    p_actor_principal_id uuid,
    p_additional_attempts integer,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_actor_principal_id IS NULL OR p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'actor principal and replay reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF p_additional_attempts <= 0 OR p_additional_attempts > 100 THEN
        RAISE EXCEPTION 'additional attempts must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.outbox_messages
       SET status = 'pending',
           claim_token = NULL,
           lease_until = NULL,
           max_attempts = max_attempts + p_additional_attempts,
           next_attempt_at = clock_timestamp(),
           last_error_class = NULL,
           replay_count = replay_count + 1,
           last_replayed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_message_id
       AND status = 'dead';
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 1 THEN
        INSERT INTO request_engine.audit_records (
            organization_id, actor_principal_id, command_name,
            aggregate_kind, aggregate_id, details
        ) VALUES (
            p_organization_id, p_actor_principal_id,
            'admin.replay_outbox_message', 'OutboxMessage', p_message_id,
            jsonb_build_object('reason', p_reason, 'additional_attempts', p_additional_attempts)
        );
    END IF;
    RETURN v_updated = 1;
END
$function$;

CREATE FUNCTION request_admin.replay_provider_event(
    p_organization_id uuid,
    p_provider_event_row_id uuid,
    p_actor_principal_id uuid,
    p_additional_attempts integer,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_updated bigint;
BEGIN
    IF p_actor_principal_id IS NULL OR p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'actor principal and replay reason are required'
            USING ERRCODE = '22023';
    END IF;
    IF p_additional_attempts <= 0 OR p_additional_attempts > 100 THEN
        RAISE EXCEPTION 'additional attempts must be between 1 and 100'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.provider_events
       SET status = 'received',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = NULL,
           max_attempts = max_attempts + p_additional_attempts,
           next_attempt_at = clock_timestamp(),
           last_error_class = NULL,
           replay_count = replay_count + 1,
           last_replayed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_provider_event_row_id
       AND status IN ('dead', 'rejected');
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 1 THEN
        INSERT INTO request_engine.audit_records (
            organization_id, actor_principal_id, command_name,
            aggregate_kind, aggregate_id, details
        ) VALUES (
            p_organization_id, p_actor_principal_id,
            'admin.replay_provider_event', 'ProviderEvent', p_provider_event_row_id,
            jsonb_build_object('reason', p_reason, 'additional_attempts', p_additional_attempts)
        );
    END IF;
    RETURN v_updated = 1;
END
$function$;

CREATE OR REPLACE VIEW request_admin.worker_dead_letters_v1 AS
SELECT organization_id,
       'scheduled_action'::text AS work_kind,
       id AS work_id,
       attempt_count,
       max_attempts,
       replay_count,
       last_error_class,
       updated_at
  FROM request_engine.scheduled_actions
 WHERE status = 'dead'
UNION ALL
SELECT organization_id,
       'outbox_message'::text,
       id,
       attempt_count,
       max_attempts,
       replay_count,
       last_error_class,
       updated_at
  FROM request_engine.outbox_messages
 WHERE status = 'dead'
UNION ALL
SELECT organization_id,
       'provider_event'::text,
       id,
       attempt_count,
       max_attempts,
       replay_count,
       last_error_class,
       updated_at
  FROM request_engine.provider_events
 WHERE status IN ('dead', 'rejected');

RESET ROLE;

REVOKE ALL ON FUNCTION request_cmd.renew_scheduled_action_lease(uuid, uuid, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.renew_outbox_message_lease(uuid, uuid, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.retry_scheduled_action_after(uuid, uuid, interval, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.retry_outbox_message_after(uuid, uuid, interval, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.claim_provider_events(integer, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.renew_provider_event_lease(uuid, uuid, interval) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.complete_provider_event(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.retry_provider_event_after(uuid, uuid, interval, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.reject_provider_event(uuid, uuid, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.replay_dead_scheduled_action(uuid, uuid, uuid, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.replay_dead_outbox_message(uuid, uuid, uuid, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.replay_provider_event(uuid, uuid, uuid, integer, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION request_cmd.renew_scheduled_action_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.renew_outbox_message_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_scheduled_action_after(uuid, uuid, interval, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_outbox_message_after(uuid, uuid, interval, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.claim_provider_events(integer, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.renew_provider_event_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.complete_provider_event(uuid, uuid)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_provider_event_after(uuid, uuid, interval, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.reject_provider_event(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;

GRANT EXECUTE ON FUNCTION request_admin.replay_dead_scheduled_action(uuid, uuid, uuid, integer, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.replay_dead_outbox_message(uuid, uuid, uuid, integer, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.replay_provider_event(uuid, uuid, uuid, integer, text)
    TO request_engine_admin;
GRANT SELECT ON request_admin.worker_dead_letters_v1 TO request_engine_admin;

COMMIT;
