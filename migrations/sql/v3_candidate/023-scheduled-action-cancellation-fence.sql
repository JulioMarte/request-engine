BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- A tenant-scoped cancellation competes on the ScheduledAction row itself.
-- If cancellation wins, a later claim cannot discover the row. If a claim wins,
-- cancellation invalidates the token so stale completion/retry is fenced.
CREATE FUNCTION request_cmd.cancel_scheduled_action(
    p_organization_id uuid,
    p_action_id uuid
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_status text;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    UPDATE request_engine.scheduled_actions
       SET status = 'cancelled',
           claim_token = NULL,
           lease_until = NULL,
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_action_id
       AND status IN ('pending', 'leased')
    RETURNING status INTO v_status;

    IF FOUND THEN
        RETURN v_status;
    END IF;

    SELECT status
      INTO v_status
      FROM request_engine.scheduled_actions
     WHERE organization_id = p_organization_id
       AND id = p_action_id;

    RETURN COALESCE(v_status, 'not_found');
END
$function$;

-- Handlers that create authoritative DB state can call this at the start of the
-- same transaction and keep the row lock until their state change commits.
-- This makes cancellation and authoritative execution linearize on one row.
CREATE FUNCTION request_cmd.lock_scheduled_action_claim(
    p_action_id uuid,
    p_claim_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_found boolean;
BEGIN
    SELECT true
      INTO v_found
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    RETURN COALESCE(v_found, false);
END
$function$;

REVOKE ALL ON FUNCTION request_cmd.cancel_scheduled_action(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.lock_scheduled_action_claim(uuid, uuid) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION request_cmd.cancel_scheduled_action(uuid, uuid)
    TO request_engine_app, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.lock_scheduled_action_claim(uuid, uuid)
    TO request_engine_app, request_engine_worker;

RESET ROLE;
COMMIT;
