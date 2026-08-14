BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- A Party may express only one active waitlist intent for one Offering.
-- Preferences belong to that intent; they must not create duplicate FIFO candidates.
CREATE UNIQUE INDEX waitlist_entries_one_active_subject_offering_uq
    ON request_engine.waitlist_entries (
        organization_id,
        offering_id,
        subject_party_id
    )
    WHERE status = 'active';

COMMIT;
