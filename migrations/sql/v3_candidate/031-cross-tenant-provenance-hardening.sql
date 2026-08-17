BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- authority_ref is a control-plane/business reference supplied by the caller;
-- it must not be the only evidence of who actually executed an authority
-- mutation. Stamp every append-only authority event with non-spoofable database
-- session identity plus trusted request context when the caller supplied it.
CREATE FUNCTION request_engine.stamp_shared_capacity_authority_event_context()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    NEW.details := COALESCE(NEW.details, '{}'::jsonb) || pg_catalog.jsonb_strip_nulls(
        pg_catalog.jsonb_build_object(
            'database_session_user', session_user,
            'authenticated_principal_id',
                NULLIF(current_setting('request_engine.authenticated_principal_id', true), ''),
            'correlation_id',
                NULLIF(current_setting('request_engine.correlation_id', true), ''),
            'principal_kind',
                NULLIF(current_setting('request_engine.principal_kind', true), ''),
            'authentication_method',
                NULLIF(current_setting('request_engine.authentication_method', true), '')
        )
    );
    RETURN NEW;
END
$function$;

CREATE TRIGGER shared_capacity_authority_events_00_stamp_context
BEFORE INSERT ON request_engine.shared_capacity_authority_events
FOR EACH ROW EXECUTE FUNCTION request_engine.stamp_shared_capacity_authority_event_context();

-- CapacityClaim replacement is historical provenance, not a free-form graph.
-- Claims are created live; cancellation/release transitions them to released;
-- Reschedule may then wire a released Reservation claim to the new live claim
-- for the same Reservation and requirement. Requiring the target to be active
-- while locked makes self-links and cycles impossible and preserves a forward
-- replacement chain under concurrency.
CREATE FUNCTION request_engine.guard_capacity_claim_replacement_provenance()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_target_status text;
    v_target_requirement_id uuid;
    v_target_reservation_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'active' OR NEW.replaced_by_claim_id IS NOT NULL THEN
            RAISE EXCEPTION 'CapacityClaim must be created as active without replacement provenance'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status <> 'replaced' THEN
        IF NEW.replaced_by_claim_id IS NOT NULL THEN
            RAISE EXCEPTION 'CapacityClaim replacement edge requires replaced status'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'replaced' THEN
        RETURN NEW;
    END IF;

    IF OLD.status <> 'released' THEN
        RAISE EXCEPTION 'CapacityClaim must be released before replacement is recorded'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reservation_id IS NULL OR NEW.replaced_by_claim_id = NEW.id THEN
        RAISE EXCEPTION 'CapacityClaim replacement provenance is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT target.status, target.requirement_id, target.reservation_id
      INTO v_target_status, v_target_requirement_id, v_target_reservation_id
      FROM request_engine.capacity_claims target
     WHERE target.organization_id = NEW.organization_id
       AND target.id = NEW.replaced_by_claim_id
     FOR UPDATE;

    IF NOT FOUND
       OR v_target_status <> 'active'
       OR v_target_requirement_id <> NEW.requirement_id
       OR v_target_reservation_id IS DISTINCT FROM NEW.reservation_id
    THEN
        RAISE EXCEPTION 'CapacityClaim replacement must target the live successor for the same owner and requirement'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_claims_guard_replacement_provenance
BEFORE INSERT OR UPDATE OF status, replaced_by_claim_id
ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_replacement_provenance();

REVOKE ALL ON FUNCTION request_engine.stamp_shared_capacity_authority_event_context()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_replacement_provenance()
    FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
