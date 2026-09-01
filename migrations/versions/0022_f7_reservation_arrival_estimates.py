"""Add reservation arrival estimates (F7d).

Revision ID: 0022_f7_arrival_estimates
Revises: 0021_recovery_autonomy_policy
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022_f7_arrival_estimates"
down_revision: str | Sequence[str] | None = "0021_recovery_autonomy_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.reservation_arrival_estimates (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    estimated_arrival_at timestamptz NOT NULL,
    source_kind text NOT NULL,
    asserted_by_principal_id uuid,
    asserted_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    superseded_at timestamptz,
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    FOREIGN KEY (organization_id, asserted_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CHECK (source_kind IN ('customer', 'operator')),
    CHECK (superseded_at IS NULL OR superseded_at >= asserted_at)
);

CREATE UNIQUE INDEX reservation_arrival_estimates_one_active_uq
    ON request_engine.reservation_arrival_estimates (organization_id, reservation_id)
    WHERE superseded_at IS NULL;
CREATE INDEX reservation_arrival_estimates_history_idx
    ON request_engine.reservation_arrival_estimates
       (organization_id, reservation_id, asserted_at);

CREATE FUNCTION request_engine.guard_reservation_arrival_estimate()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'reservation arrival estimate history is append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.reservation_id IS DISTINCT FROM NEW.reservation_id
       OR OLD.estimated_arrival_at IS DISTINCT FROM NEW.estimated_arrival_at
       OR OLD.source_kind IS DISTINCT FROM NEW.source_kind
       OR OLD.asserted_by_principal_id IS DISTINCT FROM NEW.asserted_by_principal_id
       OR OLD.asserted_at IS DISTINCT FROM NEW.asserted_at THEN
        RAISE EXCEPTION 'reservation arrival estimate facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.superseded_at IS NOT NULL
       AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at THEN
        RAISE EXCEPTION 'superseded reservation arrival estimate is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER reservation_arrival_estimates_guard_transition
BEFORE UPDATE OR DELETE ON request_engine.reservation_arrival_estimates
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_arrival_estimate();

CREATE FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status
      FROM request_engine.reservations
     WHERE organization_id = NEW.organization_id
       AND id = NEW.reservation_id;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'arrival estimate reservation must exist' USING ERRCODE = '23514';
    END IF;
    IF v_status <> 'confirmed' THEN
        RAISE EXCEPTION 'arrival estimate requires a confirmed reservation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER reservation_arrival_estimates_assert_reservation_confirmed
BEFORE INSERT ON request_engine.reservation_arrival_estimates
FOR EACH ROW EXECUTE FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed();

REVOKE EXECUTE ON FUNCTION
  request_engine.guard_reservation_arrival_estimate() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION
  request_engine.assert_arrival_estimate_reservation_confirmed() FROM PUBLIC;

CREATE OR REPLACE VIEW request_read.reservation_status_v1
WITH (security_invoker = true) AS
SELECT
    r.id AS reservation_id,
    r.organization_id,
    r.offering_version_id,
    r.subject_party_id,
    r.location_id,
    r.during,
    r.status,
    r.revision,
    COALESCE(ar.response, 'pending') AS attendance_status,
    ar.responded_at AS attendance_responded_at,
    ae.estimated_arrival_at
FROM request_engine.reservations r
LEFT JOIN LATERAL (
    SELECT a.response, a.responded_at
      FROM request_engine.attendance_responses a
     WHERE a.organization_id = r.organization_id
       AND a.reservation_id = r.id
     ORDER BY a.responded_at DESC, a.id DESC
     LIMIT 1
) ar ON true
LEFT JOIN LATERAL (
    SELECT e.estimated_arrival_at
      FROM request_engine.reservation_arrival_estimates e
     WHERE e.organization_id = r.organization_id
       AND e.reservation_id = r.id
       AND e.superseded_at IS NULL
     LIMIT 1
) ae ON true;

ALTER TABLE request_engine.reservation_arrival_estimates
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.reservation_arrival_estimates
  FORCE ROW LEVEL SECURITY;
CREATE POLICY reservation_arrival_estimates_tenant_policy
  ON request_engine.reservation_arrival_estimates
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.reservation_arrival_estimates FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.reservation_arrival_estimates TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.reservation_arrival_estimates TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0022 introduces reservation arrival estimates and is not reversible")
