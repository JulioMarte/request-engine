"""Expose the served visit of a reservation on the day board read contract.

Defect: ``request_read.reservation_day_v1`` only projected ACTIVE queue entries
(waiting/called/serving). A booked customer who was checked in through
``queue.check_in`` (which creates a QueueEntry and does not write
``reservation_attendance``), called, served and finished therefore looked
untouched on the day board afterwards: no arrival, no service, nothing.

Change (expand-only): ``CREATE OR REPLACE VIEW`` appends three columns at the
end of the existing column list; every existing column keeps its name, type,
position and expression.

``served_queue_entry_id``
    the QueueEntry of the most recent completed ServiceSession of this
    reservation (a QueueEntry has at most one ServiceSession:
    ``service_sessions_organization_id_queue_entry_id_key``).
``served_at``
    that ServiceSession's ``completed_at``. ServiceSession is the actual
    execution fact; ``service_session.complete`` writes the same instant to
    ``queue_entries.completed_at`` in the same transaction through
    ``request_cmd.mark_queue_entry_service_completed``, and a QueueEntry reaches
    ``completed`` only through that serving -> completed transition. Both the
    session status and the entry status are required to be ``completed``.
``visit_arrived_at``
    the earliest ``arrived_at`` of the reservation's QueueEntries that are part
    of a current or served visit (waiting/called/serving/completed). Entries that
    ended as ``cancelled`` or ``no_show`` are excluded: they are not evidence
    that the visit happened. This stays truthful after the visit completes.

Schema-change checklist (migrations/AGENTS.md):

- Business owner: booking (day board read contract ``appointments.day_board``);
  the facts read are owned by queue (QueueEntry) and delivery (ServiceSession).
- Current guarantees affected: tenant Organization equality / RLS foreign-row
  opacity of ``request_read`` views; read-only nature of ``request_read``.
  No command, constraint or capacity guarantee changes.
- Change class: additive read-contract expansion (expand-only); no data
  migration, no backfill, no contract phase required. Existing consumers that
  select named columns are unaffected.
- Authoritative objects: ``request_engine.queue_entries`` and
  ``request_engine.service_sessions`` (read only). No table/function/constraint
  changes.
- READ/PLAN/LOCK/VALIDATE/WRITE/EMIT: not applicable (read surface only).
- Serialization root / lock order: none; the view takes no row locks. The DDL
  takes an ACCESS EXCLUSIVE lock on the view relation only, for the duration
  of this short transaction; underlying tables are not rewritten or locked
  beyond the catalog dependency update.
- Tenant/RLS/role: the view stays owned by ``request_engine_schema_owner`` and
  keeps ``security_invoker=true`` (restated explicitly because CREATE OR
  REPLACE VIEW replaces reloptions). Invoker RLS on reservations, queue_entries
  and service_sessions therefore still applies. Existing table-level
  ``GRANT SELECT`` to ``request_engine_app`` / ``request_engine_admin`` is kept
  by CREATE OR REPLACE and covers the appended columns; the app role already
  holds SELECT on both source tables. No new grant, no SECURITY DEFINER.
- Failure/concurrency: none beyond ordinary MVCC snapshot reads.
- Migration/roll-forward: roll-forward only; a downgrade would drop the
  columns from consumers and is refused.
- Falsification proof: tests/e2e/test_day_board_served_visit.py drives
  book -> check in -> call -> start -> complete over HTTP and asserts the new
  columns from the owner read, unchanged existing columns, security_invoker,
  and that another organization sees neither the row nor the new values.
"""

from alembic import op

revision: str = "0045_day_board_served_visit"
down_revision: str | None = "0044_tenant_controller_v9"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Columns 1..29 and every join are the accepted 0001 definition verbatim
    # (only re-wrapped); the three served-visit columns are appended last.
    op.execute("""
CREATE OR REPLACE VIEW request_read.reservation_day_v1
    WITH (security_invoker = 'true') AS
SELECT r.id AS reservation_id,
       r.organization_id,
       r.offering_version_id,
       r.subject_party_id,
       p.display_name AS subject_display_name,
       r.location_id,
       r.during,
       r.status,
       r.revision,
       COALESCE(ar.response, 'pending'::text) AS attendance_status,
       ar.responded_at AS attendance_responded_at,
       COALESCE(ra.status, 'pending'::text) AS attendance_outcome,
       CASE
           WHEN ra.status = 'checked_in'::text THEN ra.checked_in_at
           WHEN ra.status = 'no_show'::text THEN ra.no_show_at
           ELSE NULL::timestamp with time zone
       END AS attendance_outcome_at,
       ra.checked_in_at,
       ra.no_show_at,
       ae.estimated_arrival_at AS reported_arrival_estimate_at,
       CASE
           WHEN r.status = 'confirmed'::text
                AND COALESCE(ra.status, 'pending'::text) = 'pending'::text
           THEN ae.estimated_arrival_at
           ELSE NULL::timestamp with time zone
       END AS effective_arrival_estimate_at,
       ae.estimated_arrival_at,
       ae.source_kind AS arrival_estimate_source_kind,
       COALESCE(qe.active_queue_entry_count, 0) AS active_queue_entry_count,
       CASE WHEN qe.active_queue_entry_count = 1 THEN qe.id ELSE NULL::uuid END
           AS queue_entry_id,
       CASE WHEN qe.active_queue_entry_count = 1 THEN qe.status ELSE NULL::text END
           AS queue_entry_status,
       CASE
           WHEN COALESCE(qe.active_queue_entry_count, 0) <> 1 THEN NULL::boolean
           ELSE qe.status = 'waiting'::text AND h.id IS NULL AND s.id IS NULL
       END AS recall_eligible,
       h.id AS recall_hold_id,
       h.condition_kind AS recall_hold_kind,
       h.until_at AS recall_hold_until_at,
       h.event_key AS recall_hold_event_key,
       h.reason AS recall_hold_reason,
       s.reason AS active_skip_reason,
       sv.queue_entry_id AS served_queue_entry_id,
       sv.completed_at AS served_at,
       va.visit_arrived_at
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
           AND e.reservation_id = r.id
           AND e.superseded_at IS NULL
         LIMIT 1
       ) ae ON true
  LEFT JOIN LATERAL (
        SELECT active.id, active.status, active.active_queue_entry_count
          FROM (
                SELECT q.id, q.status, q.admitted_at,
                       (count(*) OVER ())::integer AS active_queue_entry_count
                  FROM request_engine.queue_entries q
                 WHERE q.organization_id = r.organization_id
                   AND q.reservation_id = r.id
                   AND q.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text])
               ) active
         ORDER BY active.admitted_at DESC, active.id DESC
         LIMIT 1
       ) qe ON true
  LEFT JOIN LATERAL (
        SELECT hold.id, hold.condition_kind, hold.until_at, hold.event_key, hold.reason
          FROM request_engine.queue_entry_recall_holds hold
         WHERE qe.active_queue_entry_count = 1
           AND hold.organization_id = r.organization_id
           AND hold.queue_entry_id = qe.id
           AND hold.released_at IS NULL
           AND (hold.condition_kind <> 'until_time'::text
                OR hold.until_at > clock_timestamp())
         ORDER BY hold.created_at DESC, hold.id DESC
         LIMIT 1
       ) h ON true
  LEFT JOIN LATERAL (
        SELECT skip.id, skip.reason
          FROM request_engine.queue_entry_skips skip
         WHERE qe.active_queue_entry_count = 1
           AND skip.organization_id = r.organization_id
           AND skip.queue_entry_id = qe.id
           AND skip.consumed_at IS NULL
         ORDER BY skip.created_at DESC, skip.id DESC
         LIMIT 1
       ) s ON true
  LEFT JOIN LATERAL (
        SELECT served.id AS queue_entry_id, session.completed_at
          FROM request_engine.queue_entries served
          JOIN request_engine.service_sessions session
            ON session.organization_id = served.organization_id
           AND session.queue_entry_id = served.id
         WHERE served.organization_id = r.organization_id
           AND served.reservation_id = r.id
           AND served.status = 'completed'::text
           AND session.status = 'completed'::text
         ORDER BY session.completed_at DESC, served.id DESC
         LIMIT 1
       ) sv ON true
  LEFT JOIN LATERAL (
        SELECT min(visit.arrived_at) AS visit_arrived_at
          FROM request_engine.queue_entries visit
         WHERE visit.organization_id = r.organization_id
           AND visit.reservation_id = r.id
           AND visit.status = ANY (
                   ARRAY['waiting'::text, 'called'::text, 'serving'::text, 'completed'::text]
               )
       ) va ON true;
""")


def downgrade() -> None:
    raise RuntimeError("day board served-visit projection is roll-forward only")
