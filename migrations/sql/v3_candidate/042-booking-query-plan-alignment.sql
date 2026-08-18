BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- G15 measured evidence showed the availability reader walking every
-- historical/inactive row for a Resource before retaining the active schedule.
-- Keep the read path bounded by active schedule state and preserve its stable
-- output order for the common single-/multi-Resource lookup.
CREATE INDEX availability_schedules_active_lookup_idx
    ON request_engine.availability_schedules (
        organization_id, resource_id, weekday, local_start, id
    )
    WHERE active;

-- Availability exceptions are selected by Resource and range overlap. Without
-- a range-capable index PostgreSQL walks the Resource's exception history and
-- filters old windows. btree_gist is declared by 001-foundation.sql.
CREATE INDEX schedule_exceptions_resource_during_idx
    ON request_engine.schedule_exceptions USING gist (resource_id, during);

-- Booking and the authoritative capacity guard only need live claims when
-- checking overlap. The historical GiST remains available for history-oriented
-- access, while this partial index prevents released/replaced claims from
-- scaling the hot availability/capacity path.
CREATE INDEX capacity_claims_active_resource_during_idx
    ON request_engine.capacity_claims USING gist (resource_id, during)
    WHERE status = 'active';

RESET search_path;
RESET ROLE;
COMMIT;
