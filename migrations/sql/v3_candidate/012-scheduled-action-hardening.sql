BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_cmd, request_engine, pg_catalog;

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
        SELECT
            s.id,
            s.organization_id,
            CASE
                WHEN s.status = 'pending' THEN s.next_attempt_at
                ELSE s.lease_until
            END AS due_at,
            row_number() OVER (
                PARTITION BY s.organization_id
                ORDER BY
                    CASE
                        WHEN s.status = 'pending' THEN s.next_attempt_at
                        ELSE s.lease_until
                    END,
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
    JOIN ranked r ON r.id = c.id
    ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$function$;

CREATE FUNCTION request_cmd.renew_scheduled_action_lease(
    p_action_id uuid,
    p_claim_token uuid,
    p_lease interval DEFAULT interval '60 seconds'
)
RETURNS timestamptz
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_lease_until timestamptz;
BEGIN
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.scheduled_actions
       SET lease_until = clock_timestamp() + p_lease,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
    RETURNING lease_until INTO v_lease_until;

    RETURN v_lease_until;
END
$function$;

REVOKE ALL ON FUNCTION request_cmd.renew_scheduled_action_lease(uuid, uuid, interval)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_cmd.renew_scheduled_action_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;

RESET ROLE;
COMMIT;
