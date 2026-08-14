BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- Phase 3: keep commitment state and attendance execution outcome orthogonal.
CREATE TABLE request_engine.reservation_attendance (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    checked_in_at timestamptz,
    no_show_at timestamptz,
    source_key text,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, reservation_id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    CHECK (status IN ('pending', 'checked_in', 'no_show')),
    CHECK (revision > 0),
    CHECK (
        (status = 'pending' AND checked_in_at IS NULL AND no_show_at IS NULL)
        OR (status = 'checked_in' AND checked_in_at IS NOT NULL AND no_show_at IS NULL)
        OR (status = 'no_show' AND checked_in_at IS NULL AND no_show_at IS NOT NULL)
    )
);

CREATE TRIGGER reservation_attendance_revision_step
BEFORE UPDATE ON request_engine.reservation_attendance
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER reservation_attendance_touch
BEFORE UPDATE ON request_engine.reservation_attendance
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE INDEX reservation_attendance_status_idx
    ON request_engine.reservation_attendance (organization_id, status, reservation_id);

ALTER TABLE request_engine.reservation_attendance ENABLE ROW LEVEL SECURITY;
CREATE POLICY reservation_attendance_tenant_isolation
    ON request_engine.reservation_attendance
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

RESET ROLE;

-- 005-read-access ran before this pre-baseline table existed, so grant the
-- same runtime surface explicitly here. DELETE remains deliberately absent.
REVOKE ALL ON request_engine.reservation_attendance FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON request_engine.reservation_attendance
    TO request_engine_app, request_engine_worker;
GRANT ALL PRIVILEGES ON request_engine.reservation_attendance
    TO request_engine_admin;

COMMIT;
