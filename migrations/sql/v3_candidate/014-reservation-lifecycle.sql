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

CREATE INDEX reservation_attendance_status_idx
    ON request_engine.reservation_attendance (organization_id, status, reservation_id);

-- Current response history is append-oriented. This index keeps the current
-- projection deterministic and makes response/no-show races cheap to inspect.
CREATE INDEX attendance_responses_reservation_current_idx
    ON request_engine.attendance_responses (
        organization_id,
        reservation_id,
        responded_at DESC,
        id DESC
    );

RESET ROLE;
COMMIT;
