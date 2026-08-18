BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- G15 representative-cardinality EXPLAIN evidence showed that historical
-- SlotOffer provenance lookups were using the unrelated
-- (organization_id, capacity_hold_id) unique index, reading every SlotOffer
-- for the tenant and filtering almost all rows. These two indexes align the
-- physical access paths with the authoritative provenance dimensions used by
-- the source-immutability guards and Waitlist candidate anti-joins.
CREATE INDEX slot_offers_waitlist_history_idx
    ON request_engine.slot_offers (organization_id, waitlist_entry_id);

CREATE INDEX slot_offers_opportunity_waitlist_history_idx
    ON request_engine.slot_offers (
        organization_id,
        slot_opportunity_id,
        waitlist_entry_id
    );

RESET search_path;
RESET ROLE;
COMMIT;
