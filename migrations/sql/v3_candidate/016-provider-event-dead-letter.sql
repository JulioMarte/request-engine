BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, pg_catalog;

-- A semantic rejection is not the same as infrastructure exhaustion.
-- Permanent worker failures and max-attempt exhaustion terminate as dead;
-- explicit provider-payload/business rejection remains rejected.
CREATE FUNCTION request_cmd.dead_letter_provider_event(
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
       AND claim_token = p_claim_token;

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$function$;

RESET ROLE;

REVOKE ALL ON FUNCTION request_cmd.dead_letter_provider_event(uuid, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_cmd.dead_letter_provider_event(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;

COMMIT;
