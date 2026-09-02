"""Add the F7 operator day-board read projection.

Revision ID: 0027_f7_operator_day_board
Revises: 0026_s3_escalation_lineage
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_f7_operator_day_board"
down_revision: str | Sequence[str] | None = "0026_s3_escalation_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE VIEW request_read.reservation_day_v1
WITH (security_invoker = true) AS
SELECT
    r.id AS reservation_id,
    r.organization_id,
    r.subject_party_id,
    p.display_name AS subject_display_name,
    r.offering_version_id,
    r.location_id,
    r.during,
    r.status,
    r.revision,
    COALESCE(ar.response, 'pending') AS attendance_status,
    ar.responded_at AS attendance_responded_at,
    COALESCE(ra.status, 'pending') AS attendance_outcome_status,
    ra.checked_in_at,
    ra.no_show_at,
    ae.estimated_arrival_at AS reported_arrival_estimate_at,
    CASE
        WHEN r.status = 'confirmed'
         AND COALESCE(ra.status, 'pending') = 'pending'
        THEN ae.estimated_arrival_at
        ELSE NULL
    END AS effective_arrival_estimate_at,
    ae.source_kind AS arrival_estimate_source_kind
FROM request_engine.reservations r
JOIN request_engine.parties p
  ON p.organization_id = r.organization_id
 AND p.id = r.subject_party_id
LEFT JOIN LATERAL (
    SELECT a.response, a.responded_at
      FROM request_engine.attendance_responses a
     WHERE a.organization_id = r.organization_id
       AND a.reservation_id = r.id
     ORDER BY a.responded_at DESC, a.id DESC
     LIMIT 1
) ar ON true
LEFT JOIN request_engine.reservation_attendance ra
  ON ra.organization_id = r.organization_id
 AND ra.reservation_id = r.id
LEFT JOIN LATERAL (
    SELECT e.estimated_arrival_at, e.source_kind
      FROM request_engine.reservation_arrival_estimates e
     WHERE e.organization_id = r.organization_id
       AND e.reservation_id = r.id
       AND e.superseded_at IS NULL
     LIMIT 1
) ae ON true;

GRANT SELECT ON request_read.reservation_day_v1 TO request_engine_app;
GRANT SELECT ON request_read.reservation_day_v1 TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0027 adds the F7 operator day-board read projection and is not reversible")
