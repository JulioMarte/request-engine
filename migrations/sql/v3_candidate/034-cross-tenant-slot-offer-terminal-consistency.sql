BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- Migration 030 intentionally allows a SlotOffer to expire before its backing
-- CapacityHold, provided the offer never outlives either the Hold or the
-- SlotOpportunity start.  The older deferred consistency function from 013
-- required exact expiry equality, which contradicted that stronger policy and
-- rejected otherwise valid offers at COMMIT.  Replace the deferred invariant
-- with the actual contract and, while doing so, close the accepted-state gap:
-- an accepted offer must commit together with the Queue terminal state and a
-- real Hold->Reservation promotion.

-- Preserve both the broad provenance classification introduced by 030 and the
-- long-standing precise subject-mismatch diagnostic on creation. Retargeting an
-- existing SlotOffer remains owned by the immutable-provenance guard and keeps
-- its 55000 contract. This check is tenant-local and exposes no hidden
-- shared-capacity metadata.
CREATE FUNCTION request_engine.guard_slot_offer_subject_match()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_hold_subject_party_id uuid;
    v_waitlist_subject_party_id uuid;
BEGIN
    IF NEW.status <> 'offered' THEN
        RETURN NEW;
    END IF;

    SELECT h.subject_party_id, w.subject_party_id
      INTO v_hold_subject_party_id, v_waitlist_subject_party_id
      FROM request_engine.capacity_holds h
      JOIN request_engine.waitlist_entries w
        ON w.organization_id = h.organization_id
       AND w.id = NEW.waitlist_entry_id
     WHERE h.organization_id = NEW.organization_id
       AND h.id = NEW.capacity_hold_id;

    IF FOUND AND v_hold_subject_party_id <> v_waitlist_subject_party_id THEN
        RAISE EXCEPTION 'SlotOffer provenance mismatch: Hold subject does not match WaitlistEntry subject'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER slot_offers_00_guard_subject_match
BEFORE INSERT ON request_engine.slot_offers
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_subject_match();

CREATE OR REPLACE FUNCTION request_engine.assert_slot_offer_consistency()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    offer_row request_engine.slot_offers%ROWTYPE;
    hold_row request_engine.capacity_holds%ROWTYPE;
    opportunity_row request_engine.slot_opportunities%ROWTYPE;
    waitlist_row request_engine.waitlist_entries%ROWTYPE;
    opportunity_offering_id uuid;
    expected_hold_status text;
    v_claim_count bigint;
    v_promoted_claim_count bigint;
    v_reservation_count bigint;
    v_reservation_id uuid;
    v_reservation_status text;
BEGIN
    IF TG_TABLE_NAME = 'slot_offers' THEN
        offer_row := NEW;
    ELSE
        SELECT so.*
          INTO offer_row
          FROM request_engine.slot_offers so
         WHERE so.organization_id = NEW.organization_id
           AND so.capacity_hold_id = NEW.id;

        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
    END IF;

    SELECT h.*
      INTO STRICT hold_row
      FROM request_engine.capacity_holds h
     WHERE h.organization_id = offer_row.organization_id
       AND h.id = offer_row.capacity_hold_id;

    SELECT o.*
      INTO STRICT opportunity_row
      FROM request_engine.slot_opportunities o
     WHERE o.organization_id = offer_row.organization_id
       AND o.id = offer_row.slot_opportunity_id;

    SELECT ov.offering_id
      INTO STRICT opportunity_offering_id
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = opportunity_row.organization_id
       AND ov.id = opportunity_row.offering_version_id;

    SELECT w.*
      INTO STRICT waitlist_row
      FROM request_engine.waitlist_entries w
     WHERE w.organization_id = offer_row.organization_id
       AND w.id = offer_row.waitlist_entry_id;

    IF waitlist_row.offering_id <> opportunity_offering_id THEN
        RAISE EXCEPTION 'SlotOffer % candidate does not match Opportunity Offering',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF hold_row.subject_party_id <> waitlist_row.subject_party_id THEN
        RAISE EXCEPTION 'SlotOffer provenance mismatch: Hold subject does not match WaitlistEntry subject'
            USING ERRCODE = '23514';
    END IF;

    IF hold_row.offering_version_id <> opportunity_row.offering_version_id
       OR hold_row.location_id IS DISTINCT FROM opportunity_row.location_id
       OR hold_row.during <> opportunity_row.during THEN
        RAISE EXCEPTION 'SlotOffer % Hold does not cover its SlotOpportunity',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF offer_row.expires_at > hold_row.expires_at
       OR offer_row.expires_at > lower(opportunity_row.during) THEN
        RAISE EXCEPTION 'SlotOffer % cannot outlive its CapacityHold or SlotOpportunity start',
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

    IF offer_row.status = 'accepted' THEN
        IF opportunity_row.status <> 'filled' OR waitlist_row.status <> 'fulfilled' THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires filled Opportunity and fulfilled WaitlistEntry',
                offer_row.id USING ERRCODE = '23514';
        END IF;

        SELECT count(*),
               count(*) FILTER (
                   WHERE c.status = 'active' AND c.reservation_id IS NOT NULL
               ),
               count(DISTINCT c.reservation_id) FILTER (
                   WHERE c.status = 'active' AND c.reservation_id IS NOT NULL
               )
          INTO v_claim_count,
               v_promoted_claim_count,
               v_reservation_count
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = offer_row.organization_id
           AND c.hold_id = offer_row.capacity_hold_id;

        SELECT c.reservation_id
          INTO v_reservation_id
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = offer_row.organization_id
           AND c.hold_id = offer_row.capacity_hold_id
           AND c.status = 'active'
           AND c.reservation_id IS NOT NULL
         LIMIT 1;

        IF v_claim_count = 0
           OR v_promoted_claim_count <> v_claim_count
           OR v_reservation_count <> 1
           OR v_reservation_id IS NULL THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires complete Hold-to-Reservation claim promotion',
                offer_row.id USING ERRCODE = '23514';
        END IF;

        SELECT r.status
          INTO v_reservation_status
          FROM request_engine.reservations r
         WHERE r.organization_id = offer_row.organization_id
           AND r.id = v_reservation_id;

        IF NOT FOUND OR v_reservation_status <> 'confirmed' THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires a confirmed Reservation',
                offer_row.id USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION request_engine.guard_slot_offer_subject_match() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.assert_slot_offer_consistency() FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
