"""Add the appointment calendar read contract ``request_read.reservation_calendar_v1``.

Defect: a week/month calendar with doctor/room columns could not be built. The
only operator reservation read, ``request_read.reservation_day_v1``, is consumed
through a 36-hour window and none of its rows say which Resource the
appointment consumes.

Change (expand-only): one new ``security_invoker`` view plus one partial index.
No existing object changes.

Row semantics (one row per Reservation, ``organization_id`` + ``reservation_id``):

``claimed_resources`` / ``claimed_resource_ids``
    the Reservation's *current claim set*: its ``capacity_claims`` that are not
    ``replaced``. CapacityClaim is the accepted consumption truth for a
    Reservation (root AGENTS.md product language). While the Reservation is
    confirmed these claims are ``active``; cancellation, attendance decline and
    no-show release them in place (``status='released'``) and a reschedule
    marks the previous set ``replaced`` and inserts a new one
    (``replaced_by_claim_id``). Excluding ``replaced`` therefore yields exactly
    the Resources the appointment is (or, once released, was last) planned on;
    ``claim_active`` tells the two apart. A Reservation may hold several claims
    (one per offering requirement, e.g. doctor and room), so this is a list,
    ordered by display name then id.
``offering_display_name``
    ``offerings.display_name`` of the Reservation's OfferingVersion.
attendance / served-visit columns
    the same expressions as ``reservation_day_v1`` (0001 + 0045):
    ``attendance_status`` (latest attendance response), ``attendance_outcome``,
    ``checked_in_at``, ``no_show_at``, ``served_queue_entry_id``/``served_at``
    (latest completed ServiceSession whose QueueEntry is completed) and
    ``visit_arrived_at`` (earliest arrival of a waiting/called/serving/completed
    QueueEntry). Recall/skip/arrival-estimate columns are intentionally absent:
    they are same-day front-desk controls served by the day board.

Schema-change checklist (migrations/AGENTS.md):

- Business owner: booking (operation ``appointments_calendar``, capability
  ``appointments.day_board``). Facts read: booking (reservations,
  capacity_claims, reservation_attendance, attendance_responses), catalog
  (offerings/offering_versions names), supply (resources), tenancy (parties
  display name, as the day board already exposes), queue (queue_entries) and
  delivery (service_sessions). All read only.
- Current guarantees affected: tenant Organization equality / RLS foreign-row
  opacity of ``request_read`` views and the read-only nature of
  ``request_read``. No command, constraint, capacity or lock guarantee changes.
- Change class: additive read contract (expand-only); no data migration or
  backfill; nothing to contract later.
- Authoritative objects: none modified. New view only; new partial index
  ``capacity_claims_reservation_current_idx`` on
  ``(organization_id, reservation_id) WHERE reservation_id IS NOT NULL AND
  status <> 'replaced'`` so the per-row claim-set lookup does not depend on the
  active-only unique index (released claims of cancelled/no-show rows are read
  too). The window scan reuses the existing GiST
  ``reservations_org_during_gist (organization_id, during)``; rows are ordered
  ``lower(during), reservation_id`` for keyset pagination by the caller.
- READ/PLAN/LOCK/VALIDATE/WRITE/EMIT: not applicable (read surface only).
- Serialization root / lock order: none; the view takes no row locks. The
  index is built ``CONCURRENTLY`` (SHARE UPDATE EXCLUSIVE; writers to
  ``capacity_claims`` are not blocked). ``IF NOT EXISTS`` keeps a retried
  upgrade convergent; an INVALID leftover index from an interrupted build must
  be dropped by the operator before retrying (standard CONCURRENTLY caveat).
- Tenant/RLS/role: view owned by ``request_engine_schema_owner`` with
  ``security_invoker=true``, so the caller's RLS on every source table applies
  (identical posture to ``reservation_day_v1`` / ``change_feed_v1``).
  ``REVOKE ALL FROM PUBLIC``; ``GRANT SELECT`` to ``request_engine_app`` and
  ``request_engine_admin`` only. The app role already holds SELECT on every
  source table. No SECURITY DEFINER.
- Failure/concurrency: ordinary MVCC snapshot reads; a page may observe a
  reschedule between pages (keyset on ``(start, id)`` never repeats or skips a
  row that did not move).
- Migration/roll-forward: roll-forward only; downgrade refused.
- Falsification proof: tests/e2e/test_appointment_calendar.py (two-week window
  with the claimed resource and name, stable keyset paging, resource filter,
  >42-day window 422, missing capability 403, cross-tenant opacity,
  ``security_invoker`` and grants) and the tenant isolation matrix probe.
"""

from alembic import op

revision: str = "0047_reservation_calendar_read"
down_revision: str | None = "0046_change_feed_signal"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
CREATE VIEW request_read.reservation_calendar_v1
    WITH (security_invoker = 'true') AS
SELECT r.id AS reservation_id,
       r.organization_id,
       r.offering_version_id,
       o.display_name AS offering_display_name,
       r.subject_party_id,
       p.display_name AS subject_display_name,
       r.location_id,
       r.during,
       r.status,
       r.revision,
       COALESCE(ar.response, 'pending'::text) AS attendance_status,
       COALESCE(ra.status, 'pending'::text) AS attendance_outcome,
       ra.checked_in_at,
       ra.no_show_at,
       sv.queue_entry_id AS served_queue_entry_id,
       sv.completed_at AS served_at,
       va.visit_arrived_at,
       COALESCE(cl.claimed_resources, '[]'::jsonb) AS claimed_resources,
       COALESCE(cl.claimed_resource_ids, ARRAY[]::uuid[]) AS claimed_resource_ids
  FROM request_engine.reservations r
  JOIN request_engine.parties p
    ON p.organization_id = r.organization_id AND p.id = r.subject_party_id
  JOIN request_engine.offering_versions ov
    ON ov.organization_id = r.organization_id AND ov.id = r.offering_version_id
  JOIN request_engine.offerings o
    ON o.organization_id = ov.organization_id AND o.id = ov.offering_id
  LEFT JOIN LATERAL (
        SELECT a.response
          FROM request_engine.attendance_responses a
         WHERE a.organization_id = r.organization_id AND a.reservation_id = r.id
         ORDER BY a.responded_at DESC, a.id DESC
         LIMIT 1
       ) ar ON true
  LEFT JOIN request_engine.reservation_attendance ra
    ON ra.organization_id = r.organization_id AND ra.reservation_id = r.id
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
       ) va ON true
  LEFT JOIN LATERAL (
        SELECT jsonb_agg(
                   jsonb_build_object(
                       'resource_id', c.resource_id,
                       'display_name', res.display_name,
                       'claim_active', c.status = 'active'::text
                   )
                   ORDER BY res.display_name, c.resource_id
               ) AS claimed_resources,
               array_agg(c.resource_id ORDER BY c.resource_id) AS claimed_resource_ids
          FROM request_engine.capacity_claims c
          JOIN request_engine.resources res
            ON res.organization_id = c.organization_id AND res.id = c.resource_id
         WHERE c.organization_id = r.organization_id
           AND c.reservation_id = r.id
           AND c.status <> 'replaced'::text
       ) cl ON true;
ALTER VIEW request_read.reservation_calendar_v1 OWNER TO request_engine_schema_owner;
REVOKE ALL ON request_read.reservation_calendar_v1 FROM PUBLIC;
GRANT SELECT ON request_read.reservation_calendar_v1 TO request_engine_app;
GRANT SELECT ON request_read.reservation_calendar_v1 TO request_engine_admin;
""")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS capacity_claims_reservation_current_idx "
            "ON request_engine.capacity_claims (organization_id, reservation_id) "
            "WHERE reservation_id IS NOT NULL AND status <> 'replaced'"
        )


def downgrade() -> None:
    raise RuntimeError("reservation calendar read contract is roll-forward only")
