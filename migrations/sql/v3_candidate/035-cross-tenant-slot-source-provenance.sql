BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- SlotOffer keeps stable foreign keys to a Hold, WaitlistEntry and
-- SlotOpportunity.  Those ids are not sufficient historical provenance if the
-- semantic fields underneath them remain rewritable.  Production commands
-- create these booking-intent rows once and subsequently advance only lifecycle
-- state/revision/timestamps, so freeze their material identity at the database
-- boundary as well.

CREATE FUNCTION request_engine.guard_capacity_hold_provenance_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.offering_version_id IS DISTINCT FROM NEW.offering_version_id
       OR OLD.subject_party_id IS DISTINCT FROM NEW.subject_party_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id
       OR OLD.during IS DISTINCT FROM NEW.during
       OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'CapacityHold booking provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_holds_guard_provenance
BEFORE UPDATE ON request_engine.capacity_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_hold_provenance_update();

CREATE FUNCTION request_engine.guard_waitlist_entry_provenance_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.offering_id IS DISTINCT FROM NEW.offering_id
       OR OLD.subject_party_id IS DISTINCT FROM NEW.subject_party_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id
       OR OLD.preferred_resource_id IS DISTINCT FROM NEW.preferred_resource_id
       OR OLD.earliest_start IS DISTINCT FROM NEW.earliest_start
       OR OLD.latest_start IS DISTINCT FROM NEW.latest_start
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'WaitlistEntry booking provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER waitlist_entries_guard_provenance
BEFORE UPDATE ON request_engine.waitlist_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_waitlist_entry_provenance_update();

CREATE FUNCTION request_engine.guard_slot_opportunity_provenance_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.offering_version_id IS DISTINCT FROM NEW.offering_version_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id
       OR OLD.source_reservation_id IS DISTINCT FROM NEW.source_reservation_id
       OR OLD.source_event_id IS DISTINCT FROM NEW.source_event_id
       OR OLD.during IS DISTINCT FROM NEW.during
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'SlotOpportunity booking provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER slot_opportunities_guard_provenance
BEFORE UPDATE ON request_engine.slot_opportunities
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_opportunity_provenance_update();

REVOKE ALL ON FUNCTION request_engine.guard_capacity_hold_provenance_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_waitlist_entry_provenance_update() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_slot_opportunity_provenance_update() FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
