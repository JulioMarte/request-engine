BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- V3-I42: even historical retries may not record two accepted winners.
CREATE UNIQUE INDEX slot_offers_one_accepted_per_opportunity_uq
    ON request_engine.slot_offers (organization_id, slot_opportunity_id)
    WHERE status = 'accepted';

-- The candidate scan is deterministic FIFO after the Offering/location/time predicates.
CREATE INDEX waitlist_entries_offer_candidate_idx
    ON request_engine.waitlist_entries (
        organization_id,
        offering_id,
        status,
        created_at,
        id
    )
    INCLUDE (subject_party_id, location_id, preferred_resource_id, earliest_start, latest_start);

-- Validate the complete local SlotOffer graph at commit. This is deferred because
-- accept/decline/expiry intentionally update Hold and Offer in one transaction.
CREATE FUNCTION request_engine.assert_slot_offer_consistency()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    offer_row request_engine.slot_offers%ROWTYPE;
    hold_row request_engine.capacity_holds%ROWTYPE;
    opportunity_row request_engine.slot_opportunities%ROWTYPE;
    waitlist_row request_engine.waitlist_entries%ROWTYPE;
    opportunity_offering_id uuid;
    expected_hold_status text;
BEGIN
    IF TG_TABLE_NAME = 'slot_offers' THEN
        offer_row := NEW;
    ELSE
        SELECT so
          INTO offer_row
          FROM request_engine.slot_offers so
         WHERE so.organization_id = NEW.organization_id
           AND so.capacity_hold_id = NEW.id;

        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
    END IF;

    SELECT h
      INTO STRICT hold_row
      FROM request_engine.capacity_holds h
     WHERE h.organization_id = offer_row.organization_id
       AND h.id = offer_row.capacity_hold_id;

    SELECT o, ov.offering_id
      INTO STRICT opportunity_row, opportunity_offering_id
      FROM request_engine.slot_opportunities o
      JOIN request_engine.offering_versions ov
        ON ov.organization_id = o.organization_id
       AND ov.id = o.offering_version_id
     WHERE o.organization_id = offer_row.organization_id
       AND o.id = offer_row.slot_opportunity_id;

    SELECT w
      INTO STRICT waitlist_row
      FROM request_engine.waitlist_entries w
     WHERE w.organization_id = offer_row.organization_id
       AND w.id = offer_row.waitlist_entry_id;

    IF waitlist_row.offering_id <> opportunity_offering_id THEN
        RAISE EXCEPTION 'SlotOffer % candidate does not match Opportunity Offering',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF hold_row.subject_party_id <> waitlist_row.subject_party_id THEN
        RAISE EXCEPTION 'SlotOffer % Hold subject does not match WaitlistEntry subject',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF hold_row.offering_version_id <> opportunity_row.offering_version_id
       OR hold_row.location_id IS DISTINCT FROM opportunity_row.location_id
       OR hold_row.during <> opportunity_row.during THEN
        RAISE EXCEPTION 'SlotOffer % Hold does not cover its SlotOpportunity',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF hold_row.expires_at <> offer_row.expires_at THEN
        RAISE EXCEPTION 'SlotOffer % expiration differs from its CapacityHold',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    expected_hold_status := CASE offer_row.status
        WHEN 'offered' THEN 'active'
        WHEN 'accepted' THEN 'consumed'
        WHEN 'declined' THEN 'released'
        WHEN 'cancelled' THEN 'released'
        WHEN 'expired' THEN 'expired'
        ELSE NULL
    END;

    IF expected_hold_status IS NULL OR hold_row.status <> expected_hold_status THEN
        RAISE EXCEPTION 'SlotOffer % status % requires Hold status %, found %',
            offer_row.id, offer_row.status, expected_hold_status, hold_row.status
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE CONSTRAINT TRIGGER slot_offers_consistency_guard
AFTER INSERT OR UPDATE ON request_engine.slot_offers
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_slot_offer_consistency();

CREATE CONSTRAINT TRIGGER slot_offer_holds_consistency_guard
AFTER UPDATE OF status, expires_at, during, offering_version_id, subject_party_id, location_id
ON request_engine.capacity_holds
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_slot_offer_consistency();

RESET ROLE;
COMMIT;
