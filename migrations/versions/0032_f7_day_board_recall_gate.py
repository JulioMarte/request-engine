"""Project same-day Queue recall gates into the operator Day Board.

Revision ID: 0032_f7_day_board_recall_gate
Revises: 0031_queue_release_recall_hold
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0032_f7_day_board_recall_gate"
down_revision: str | Sequence[str] | None = "0031_queue_release_recall_hold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE OR REPLACE VIEW request_read.reservation_day_v1
WITH (security_invoker = true) AS
SELECT
    r.id AS reservation_id, r.organization_id, r.offering_version_id,
    r.subject_party_id, p.display_name AS subject_display_name,
    r.location_id, r.during, r.status, r.revision,
    COALESCE(ar.response, 'pending') AS attendance_status,
    ar.responded_at AS attendance_responded_at,
    COALESCE(ra.status, 'pending') AS attendance_outcome,
    CASE
        WHEN ra.status = 'checked_in' THEN ra.checked_in_at
        WHEN ra.status = 'no_show' THEN ra.no_show_at
        ELSE NULL
    END AS attendance_outcome_at,
    ra.checked_in_at, ra.no_show_at,
    ae.estimated_arrival_at AS reported_arrival_estimate_at,
    CASE
        WHEN r.status = 'confirmed' AND COALESCE(ra.status, 'pending') = 'pending'
        THEN ae.estimated_arrival_at ELSE NULL
    END AS effective_arrival_estimate_at,
    ae.estimated_arrival_at, ae.source_kind AS arrival_estimate_source_kind,
    qe.id AS queue_entry_id, qe.status AS queue_entry_status,
    CASE
        WHEN qe.id IS NULL THEN NULL
        ELSE qe.status = 'waiting' AND h.id IS NULL AND s.id IS NULL
    END AS recall_eligible,
    h.id AS recall_hold_id, h.condition_kind AS recall_hold_kind,
    h.until_at AS recall_hold_until_at, h.event_key AS recall_hold_event_key,
    h.reason AS recall_hold_reason, s.reason AS active_skip_reason
FROM request_engine.reservations r
JOIN request_engine.parties p
  ON p.organization_id = r.organization_id AND p.id = r.subject_party_id
LEFT JOIN LATERAL (
    SELECT a.response, a.responded_at
      FROM request_engine.attendance_responses a
     WHERE a.organization_id = r.organization_id AND a.reservation_id = r.id
     ORDER BY a.responded_at DESC, a.id DESC
     LIMIT 1
) ar ON true
LEFT JOIN request_engine.reservation_attendance ra
  ON ra.organization_id = r.organization_id AND ra.reservation_id = r.id
LEFT JOIN LATERAL (
    SELECT e.estimated_arrival_at, e.source_kind
      FROM request_engine.reservation_arrival_estimates e
     WHERE e.organization_id = r.organization_id
       AND e.reservation_id = r.id AND e.superseded_at IS NULL
     LIMIT 1
) ae ON true
LEFT JOIN LATERAL (
    SELECT q.id, q.status
      FROM request_engine.queue_entries q
     WHERE q.organization_id = r.organization_id AND q.reservation_id = r.id
       AND q.status IN ('waiting','called','serving')
     ORDER BY q.admitted_at DESC, q.id DESC
     LIMIT 1
) qe ON true
LEFT JOIN LATERAL (
    SELECT hold.id, hold.condition_kind, hold.until_at, hold.event_key, hold.reason
      FROM request_engine.queue_entry_recall_holds hold
     WHERE hold.organization_id = r.organization_id AND hold.queue_entry_id = qe.id
       AND hold.released_at IS NULL
       AND (hold.condition_kind <> 'until_time' OR hold.until_at > clock_timestamp())
     ORDER BY hold.created_at DESC, hold.id DESC
     LIMIT 1
) h ON true
LEFT JOIN LATERAL (
    SELECT skip.reason
      FROM request_engine.queue_entry_skips skip
     WHERE skip.organization_id = r.organization_id AND skip.queue_entry_id = qe.id
       AND skip.consumed_at IS NULL
     ORDER BY skip.created_at DESC, skip.id DESC
     LIMIT 1
) s ON true;

REVOKE ALL ON request_read.reservation_day_v1 FROM PUBLIC;
GRANT SELECT ON request_read.reservation_day_v1 TO request_engine_app;
GRANT SELECT ON request_read.reservation_day_v1 TO request_engine_admin;
RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0032 extends an authoritative operator read surface")
