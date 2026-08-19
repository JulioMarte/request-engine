BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- Fairness ranking is computed from a statement snapshot. Under heavy concurrent
-- claimers, another transaction can claim and commit a ranked row before this
-- transaction reaches FOR UPDATE. Re-check eligibility on the locked base row,
-- and again in the UPDATE, so an obsolete ranked row can never be re-leased.

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
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
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
           AND s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
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
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
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
           AND o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
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

CREATE OR REPLACE FUNCTION request_cmd.claim_provider_events(
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
         WHERE e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
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
           AND e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
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

RESET ROLE;
COMMIT;
