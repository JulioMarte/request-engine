BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- SlotOffer connects three independently valid tenant aggregates. Foreign keys
-- prove tenant ownership but not that the selected WaitlistEntry, the concrete
-- SlotOpportunity and the short CapacityHold describe the same booking intent.
-- Strengthen the existing guard so raw same-tenant SQL cannot fabricate an
-- offered row that later promotes another subject's or another slot's Hold.
CREATE OR REPLACE FUNCTION request_engine.guard_slot_offer_live_hold()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_hold_status text;
    v_hold_expires timestamptz;
    v_hold_offering_version_id uuid;
    v_hold_subject_party_id uuid;
    v_hold_location_id uuid;
    v_hold_during tstzrange;
    v_opportunity_status text;
    v_opportunity_offering_version_id uuid;
    v_opportunity_location_id uuid;
    v_opportunity_during tstzrange;
    v_waitlist_status text;
    v_waitlist_subject_party_id uuid;
    v_waitlist_offering_id uuid;
    v_waitlist_location_id uuid;
    v_version_offering_id uuid;
BEGIN
    IF NEW.status <> 'offered' THEN
        RETURN NEW;
    END IF;

    -- Serialize the semantic source state in the same order as Queue issuance:
    -- Opportunity -> WaitlistEntry -> Hold. FK checks alone do not prevent a
    -- concurrent status transition after this trigger has observed a live row.
    PERFORM 1
      FROM request_engine.slot_opportunities
     WHERE organization_id = NEW.organization_id
       AND id = NEW.slot_opportunity_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
      FROM request_engine.waitlist_entries
     WHERE organization_id = NEW.organization_id
       AND id = NEW.waitlist_entry_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
      FROM request_engine.capacity_holds
     WHERE organization_id = NEW.organization_id
       AND id = NEW.capacity_hold_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    SELECT h.status,
           h.expires_at,
           h.offering_version_id,
           h.subject_party_id,
           h.location_id,
           h.during,
           o.status,
           o.offering_version_id,
           o.location_id,
           o.during,
           w.status,
           w.subject_party_id,
           w.offering_id,
           w.location_id,
           ov.offering_id
      INTO v_hold_status,
           v_hold_expires,
           v_hold_offering_version_id,
           v_hold_subject_party_id,
           v_hold_location_id,
           v_hold_during,
           v_opportunity_status,
           v_opportunity_offering_version_id,
           v_opportunity_location_id,
           v_opportunity_during,
           v_waitlist_status,
           v_waitlist_subject_party_id,
           v_waitlist_offering_id,
           v_waitlist_location_id,
           v_version_offering_id
      FROM request_engine.capacity_holds h
      JOIN request_engine.slot_opportunities o
        ON o.organization_id = h.organization_id
       AND o.id = NEW.slot_opportunity_id
      JOIN request_engine.waitlist_entries w
        ON w.organization_id = h.organization_id
       AND w.id = NEW.waitlist_entry_id
      JOIN request_engine.offering_versions ov
        ON ov.organization_id = o.organization_id
       AND ov.id = o.offering_version_id
     WHERE h.organization_id = NEW.organization_id
       AND h.id = NEW.capacity_hold_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    IF v_opportunity_status <> 'open'
       OR v_waitlist_status <> 'active'
       OR v_hold_status <> 'active'
       OR v_hold_expires <= clock_timestamp()
    THEN
        RAISE EXCEPTION 'offered SlotOffer requires live source state'
            USING ERRCODE = '23514';
    END IF;

    IF v_hold_subject_party_id <> v_waitlist_subject_party_id
       OR v_hold_offering_version_id <> v_opportunity_offering_version_id
       OR v_waitlist_offering_id <> v_version_offering_id
       OR v_hold_location_id IS DISTINCT FROM v_opportunity_location_id
       OR (
           v_waitlist_location_id IS NOT NULL
           AND v_waitlist_location_id IS DISTINCT FROM v_opportunity_location_id
       )
       OR v_hold_during <> v_opportunity_during
    THEN
        RAISE EXCEPTION 'SlotOffer Hold, WaitlistEntry and SlotOpportunity provenance mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.expires_at > v_hold_expires
       OR NEW.expires_at > lower(v_opportunity_during)
    THEN
        RAISE EXCEPTION 'SlotOffer cannot outlive its Hold or opportunity start'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

-- Once an offer exists, its coordination/booking identities and expiration are
-- historical provenance. Lifecycle commands may change status/revision, but
-- must not retarget the same SlotOffer id to another candidate, opportunity or
-- Hold after notifications/audit/scheduled actions already reference it.
CREATE FUNCTION request_engine.guard_slot_offer_provenance_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.slot_opportunity_id IS DISTINCT FROM NEW.slot_opportunity_id
       OR OLD.waitlist_entry_id IS DISTINCT FROM NEW.waitlist_entry_id
       OR OLD.capacity_hold_id IS DISTINCT FROM NEW.capacity_hold_id
       OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'SlotOffer booking provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'SlotOffer revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status
       AND NEW.revision <= OLD.revision
    THEN
        RAISE EXCEPTION 'SlotOffer lifecycle transition requires revision advance'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER slot_offers_guard_provenance
BEFORE UPDATE ON request_engine.slot_offers
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_provenance_update();

REVOKE ALL ON FUNCTION request_engine.guard_slot_offer_live_hold() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_slot_offer_provenance_update() FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
