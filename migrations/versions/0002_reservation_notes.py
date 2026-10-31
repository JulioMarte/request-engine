"""Append-only staff notes on a Reservation (``request_engine.reservation_notes``).

Product need: front-desk staff (and AI agents acting for staff) document an
appointment ("Viene con su hijo", "Pidió factura con RNC", "Llamó: llega 10 min
tarde"). A note is an immutable, attributed fact. A correction is a new note
that may name ``supersedes_note_id``; nothing is edited or deleted. Tags are
deliberately out of scope (a later per-business vocabulary).

Change (expand-only):

* new table ``request_engine.reservation_notes`` (FORCE RLS, tenant policy,
  app role SELECT/INSERT only, immutable-history trigger, author-kind trigger);
* new read contract ``request_read.reservation_notes_v1`` (note rows with the
  author's staff/agent display name resolved at read time);
* ``request_read.reservation_day_v1`` gains, at the end, ``note_count``,
  ``latest_note_excerpt``, ``latest_note_author_kind`` and
  ``latest_note_created_at``; ``request_read.reservation_calendar_v1`` gains
  ``note_count``. Existing columns, order, types and row semantics are
  unchanged (``CREATE OR REPLACE VIEW`` only appends columns).

Schema-change checklist (migrations/AGENTS.md):

* Business owner: Booking (Reservation owner). Command ``appointments_note_add``
  (capability ``appointments.annotate``), query ``appointments_notes_list``
  (capability ``appointments.day_board``).
* Guarantees: tenant Organization equality and RLS foreign-row opacity;
  immutable/append-only business provenance; idempotent commands; read-only
  ``request_read``. No capacity, lifecycle, revision or lock-order guarantee
  changes: a note never advances ``reservations.revision`` and takes no
  Resource lock.
* Change class: CONTROLLED additive. New table/views/functions/index only; no
  backfill; nothing to contract later.
* Authoritative objects: ``reservation_notes``. Structural backstops:
  composite FK ``(organization_id, reservation_id)`` -> reservations (tenant
  equality; any Reservation status is accepted, cancelled included);
  composite FK ``(organization_id, author_principal_id)`` -> principals;
  composite self FK ``(organization_id, reservation_id, supersedes_note_id)``
  -> ``(organization_id, reservation_id, id)`` so a correction can only point at
  an earlier note of the *same* Reservation and tenant; body CHECK (trimmed,
  1..1000 characters, no control characters except tab/newline); author-kind
  CHECK plus a BEFORE INSERT trigger requiring it to equal the author
  Principal's ``principal_kind``; BEFORE UPDATE/DELETE trigger rejecting any
  mutation (23514) even for roles that could write.
* READ/PLAN/LOCK/VALIDATE/WRITE/EMIT (Python command): READ idempotency;
  LOCK the Reservation row ``FOR KEY SHARE`` (the same lock the FK takes; it
  keeps the parent visible without conflicting with lifecycle ``FOR UPDATE``
  writers' row updates of non-key columns); VALIDATE supersedes target;
  WRITE note; EMIT audit + ``reservation.note_added.v1`` outbox fact (no note
  text: PII-free change signal routed to the ``day_board`` change topic).
* Serialization root / lock order: none beyond the Reservation key-share
  lock; notes are independent facts, ordered by ``(created_at, id)``.
* Tenant/RLS/role: table owned by ``request_engine_schema_owner``, ENABLE +
  FORCE RLS with the standard ``current_organization_id()`` policy.
  ``request_engine_app``: SELECT, INSERT (no UPDATE/DELETE/TRUNCATE);
  ``request_engine_admin``: ALL (as for every booking table). Views are
  ``security_invoker`` so callers' RLS applies to every source table; they
  grant SELECT to app/admin only and REVOKE PUBLIC.
* Failure/concurrency: concurrent notes on one Reservation both succeed
  (independent rows); idempotent replay returns the first receipt.
* Migration/roll-forward: roll-forward only; downgrade refused.
* Falsification: tests/modules/booking/test_appointment_notes_domain.py
  (validation), tests/e2e/test_appointment_notes.py (HTTP add/list/replay,
  capability denial, cross-tenant opacity, day board/calendar/read counts,
  immutability, grants, security_invoker).
"""

from alembic import op

revision: str = "0002_reservation_notes"
down_revision: str | None = "0001_initial"
branch_labels: str | None = None
depends_on: str | None = None

_TABLE = """
CREATE TABLE request_engine.reservation_notes (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    body text NOT NULL,
    author_principal_id uuid NOT NULL,
    author_principal_kind text NOT NULL,
    supersedes_note_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reservation_notes_pkey PRIMARY KEY (id),
    CONSTRAINT reservation_notes_organization_id_id_key UNIQUE (organization_id, id),
    CONSTRAINT reservation_notes_reservation_note_key
        UNIQUE (organization_id, reservation_id, id),
    CONSTRAINT reservation_notes_body_check CHECK (
        body = btrim(body)
        AND char_length(body) BETWEEN 1 AND 1000
        AND body !~ '[\\x01-\\x08\\x0b-\\x1f\\x7f]'
    ),
    CONSTRAINT reservation_notes_author_principal_kind_check CHECK (
        author_principal_kind = ANY (ARRAY[
            'human'::text, 'service'::text, 'agent'::text,
            'integration'::text, 'provider'::text, 'worker'::text
        ])
    ),
    CONSTRAINT reservation_notes_supersedes_other_check
        CHECK (supersedes_note_id IS NULL OR supersedes_note_id <> id),
    CONSTRAINT reservation_notes_reservation_fkey
        FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    CONSTRAINT reservation_notes_author_fkey
        FOREIGN KEY (organization_id, author_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CONSTRAINT reservation_notes_supersedes_fkey
        FOREIGN KEY (organization_id, reservation_id, supersedes_note_id)
        REFERENCES request_engine.reservation_notes (organization_id, reservation_id, id)
);
ALTER TABLE request_engine.reservation_notes OWNER TO request_engine_schema_owner;
ALTER TABLE request_engine.reservation_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE ONLY request_engine.reservation_notes FORCE ROW LEVEL SECURITY;
CREATE POLICY reservation_notes_tenant_policy ON request_engine.reservation_notes
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());
CREATE INDEX reservation_notes_reservation_recent_idx
    ON request_engine.reservation_notes
    USING btree (organization_id, reservation_id, created_at DESC, id DESC);
CREATE INDEX reservation_notes_supersedes_idx
    ON request_engine.reservation_notes
    USING btree (organization_id, reservation_id, supersedes_note_id)
    WHERE supersedes_note_id IS NOT NULL;

CREATE FUNCTION request_engine.guard_reservation_note() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
BEGIN
    RAISE EXCEPTION 'reservation notes are append-only facts; add a correcting note'
        USING ERRCODE = '23514';
END
$$;
ALTER FUNCTION request_engine.guard_reservation_note() OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION request_engine.guard_reservation_note() FROM PUBLIC;

CREATE FUNCTION request_engine.assert_reservation_note_author_kind() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM request_engine.principals p
         WHERE p.organization_id = NEW.organization_id
           AND p.id = NEW.author_principal_id
           AND p.principal_kind = NEW.author_principal_kind
    ) THEN
        RAISE EXCEPTION 'reservation note author kind must match the author Principal'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;
ALTER FUNCTION request_engine.assert_reservation_note_author_kind()
    OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION request_engine.assert_reservation_note_author_kind() FROM PUBLIC;

CREATE TRIGGER reservation_notes_guard_immutable
    BEFORE DELETE OR UPDATE ON request_engine.reservation_notes
    FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_note();
CREATE TRIGGER reservation_notes_assert_author_kind
    BEFORE INSERT ON request_engine.reservation_notes
    FOR EACH ROW EXECUTE FUNCTION request_engine.assert_reservation_note_author_kind();
REVOKE ALL ON TABLE request_engine.reservation_notes FROM PUBLIC;
GRANT SELECT, INSERT ON TABLE request_engine.reservation_notes TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservation_notes TO request_engine_admin;
"""

_NOTES_VIEW = """
CREATE VIEW request_read.reservation_notes_v1 WITH (security_invoker = 'true') AS
SELECT n.id AS note_id,
       n.organization_id,
       n.reservation_id,
       n.body,
       n.author_principal_id,
       n.author_principal_kind,
       COALESCE(staff.display_name, agent.display_name) AS author_display_name,
       n.supersedes_note_id,
       n.created_at
  FROM request_engine.reservation_notes n
  LEFT JOIN LATERAL (
        SELECT profile.display_name
          FROM request_engine.staff_memberships membership
          JOIN request_engine.staff_member_profiles profile
            ON profile.organization_id = membership.organization_id
           AND profile.membership_id = membership.id
         WHERE membership.organization_id = n.organization_id
           AND membership.principal_id = n.author_principal_id
           AND profile.display_name IS NOT NULL
         ORDER BY membership.created_at DESC, membership.id DESC
         LIMIT 1
       ) staff ON true
  LEFT JOIN request_engine.agent_profiles agent
    ON agent.organization_id = n.organization_id
   AND agent.principal_id = n.author_principal_id;
ALTER VIEW request_read.reservation_notes_v1 OWNER TO request_engine_schema_owner;
REVOKE ALL ON request_read.reservation_notes_v1 FROM PUBLIC;
GRANT SELECT ON request_read.reservation_notes_v1 TO request_engine_app;
GRANT SELECT ON request_read.reservation_notes_v1 TO request_engine_admin;
"""

# The day board keeps every existing column, in order and type, and appends the
# note summary. The body is the accepted 0001 definition.
_DAY_BOARD_VIEW = """
CREATE OR REPLACE VIEW request_read.reservation_day_v1 WITH (security_invoker = 'true') AS
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
            WHEN (ra.status = 'checked_in'::text) THEN ra.checked_in_at
            WHEN (ra.status = 'no_show'::text) THEN ra.no_show_at
            ELSE NULL::timestamp with time zone
        END AS attendance_outcome_at,
    ra.checked_in_at,
    ra.no_show_at,
    ae.estimated_arrival_at AS reported_arrival_estimate_at,
        CASE
            WHEN ((r.status = 'confirmed'::text)
                  AND (COALESCE(ra.status, 'pending'::text) = 'pending'::text))
            THEN ae.estimated_arrival_at
            ELSE NULL::timestamp with time zone
        END AS effective_arrival_estimate_at,
    ae.estimated_arrival_at,
    ae.source_kind AS arrival_estimate_source_kind,
    COALESCE(qe.active_queue_entry_count, 0) AS active_queue_entry_count,
        CASE
            WHEN (qe.active_queue_entry_count = 1) THEN qe.id
            ELSE NULL::uuid
        END AS queue_entry_id,
        CASE
            WHEN (qe.active_queue_entry_count = 1) THEN qe.status
            ELSE NULL::text
        END AS queue_entry_status,
        CASE
            WHEN (COALESCE(qe.active_queue_entry_count, 0) <> 1) THEN NULL::boolean
            ELSE ((qe.status = 'waiting'::text) AND (h.id IS NULL) AND (s.id IS NULL))
        END AS recall_eligible,
    h.id AS recall_hold_id,
    h.condition_kind AS recall_hold_kind,
    h.until_at AS recall_hold_until_at,
    h.event_key AS recall_hold_event_key,
    h.reason AS recall_hold_reason,
    s.reason AS active_skip_reason,
    sv.queue_entry_id AS served_queue_entry_id,
    sv.completed_at AS served_at,
    va.visit_arrived_at,
    COALESCE(nc.note_count, 0) AS note_count,
    ln.excerpt AS latest_note_excerpt,
    ln.author_principal_kind AS latest_note_author_kind,
    ln.created_at AS latest_note_created_at
   FROM request_engine.reservations r
     JOIN request_engine.parties p
       ON p.organization_id = r.organization_id AND p.id = r.subject_party_id
     LEFT JOIN LATERAL ( SELECT a.response,
            a.responded_at
           FROM request_engine.attendance_responses a
          WHERE a.organization_id = r.organization_id AND a.reservation_id = r.id
          ORDER BY a.responded_at DESC, a.id DESC
         LIMIT 1) ar ON true
     LEFT JOIN request_engine.reservation_attendance ra
       ON ra.organization_id = r.organization_id AND ra.reservation_id = r.id
     LEFT JOIN LATERAL ( SELECT e.estimated_arrival_at,
            e.source_kind
           FROM request_engine.reservation_arrival_estimates e
          WHERE e.organization_id = r.organization_id AND e.reservation_id = r.id
            AND e.superseded_at IS NULL
         LIMIT 1) ae ON true
     LEFT JOIN LATERAL ( SELECT active.id,
            active.status,
            active.active_queue_entry_count
           FROM ( SELECT q.id,
                    q.status,
                    q.admitted_at,
                    (count(*) OVER ())::integer AS active_queue_entry_count
                   FROM request_engine.queue_entries q
                  WHERE q.organization_id = r.organization_id AND q.reservation_id = r.id
                    AND q.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text])
                ) active
          ORDER BY active.admitted_at DESC, active.id DESC
         LIMIT 1) qe ON true
     LEFT JOIN LATERAL ( SELECT hold.id,
            hold.condition_kind,
            hold.until_at,
            hold.event_key,
            hold.reason
           FROM request_engine.queue_entry_recall_holds hold
          WHERE qe.active_queue_entry_count = 1
            AND hold.organization_id = r.organization_id AND hold.queue_entry_id = qe.id
            AND hold.released_at IS NULL
            AND (hold.condition_kind <> 'until_time'::text OR hold.until_at > clock_timestamp())
          ORDER BY hold.created_at DESC, hold.id DESC
         LIMIT 1) h ON true
     LEFT JOIN LATERAL ( SELECT skip.id,
            skip.reason
           FROM request_engine.queue_entry_skips skip
          WHERE qe.active_queue_entry_count = 1
            AND skip.organization_id = r.organization_id AND skip.queue_entry_id = qe.id
            AND skip.consumed_at IS NULL
          ORDER BY skip.created_at DESC, skip.id DESC
         LIMIT 1) s ON true
     LEFT JOIN LATERAL ( SELECT served.id AS queue_entry_id,
            session.completed_at
           FROM request_engine.queue_entries served
             JOIN request_engine.service_sessions session
               ON session.organization_id = served.organization_id
              AND session.queue_entry_id = served.id
          WHERE served.organization_id = r.organization_id AND served.reservation_id = r.id
            AND served.status = 'completed'::text AND session.status = 'completed'::text
          ORDER BY session.completed_at DESC, served.id DESC
         LIMIT 1) sv ON true
     LEFT JOIN LATERAL ( SELECT min(visit.arrived_at) AS visit_arrived_at
           FROM request_engine.queue_entries visit
          WHERE visit.organization_id = r.organization_id AND visit.reservation_id = r.id
            AND visit.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text,
                                          'completed'::text])) va ON true
     LEFT JOIN LATERAL ( SELECT count(*)::integer AS note_count
           FROM request_engine.reservation_notes note
          WHERE note.organization_id = r.organization_id
            AND note.reservation_id = r.id) nc ON true
     LEFT JOIN LATERAL ( SELECT
            "left"(regexp_replace(note.body, '\\s+', ' ', 'g'), 140) AS excerpt,
            note.author_principal_kind,
            note.created_at
           FROM request_engine.reservation_notes note
          WHERE note.organization_id = r.organization_id AND note.reservation_id = r.id
          ORDER BY note.created_at DESC, note.id DESC
         LIMIT 1) ln ON true;
"""

# The calendar keeps every existing column and appends the note count.
_CALENDAR_VIEW = """
CREATE OR REPLACE VIEW request_read.reservation_calendar_v1
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
    COALESCE(cl.claimed_resource_ids, ARRAY[]::uuid[]) AS claimed_resource_ids,
    COALESCE(nc.note_count, 0) AS note_count
   FROM request_engine.reservations r
     JOIN request_engine.parties p
       ON p.organization_id = r.organization_id AND p.id = r.subject_party_id
     JOIN request_engine.offering_versions ov
       ON ov.organization_id = r.organization_id AND ov.id = r.offering_version_id
     JOIN request_engine.offerings o
       ON o.organization_id = ov.organization_id AND o.id = ov.offering_id
     LEFT JOIN LATERAL ( SELECT a.response
           FROM request_engine.attendance_responses a
          WHERE a.organization_id = r.organization_id AND a.reservation_id = r.id
          ORDER BY a.responded_at DESC, a.id DESC
         LIMIT 1) ar ON true
     LEFT JOIN request_engine.reservation_attendance ra
       ON ra.organization_id = r.organization_id AND ra.reservation_id = r.id
     LEFT JOIN LATERAL ( SELECT served.id AS queue_entry_id,
            session.completed_at
           FROM request_engine.queue_entries served
             JOIN request_engine.service_sessions session
               ON session.organization_id = served.organization_id
              AND session.queue_entry_id = served.id
          WHERE served.organization_id = r.organization_id AND served.reservation_id = r.id
            AND served.status = 'completed'::text AND session.status = 'completed'::text
          ORDER BY session.completed_at DESC, served.id DESC
         LIMIT 1) sv ON true
     LEFT JOIN LATERAL ( SELECT min(visit.arrived_at) AS visit_arrived_at
           FROM request_engine.queue_entries visit
          WHERE visit.organization_id = r.organization_id AND visit.reservation_id = r.id
            AND visit.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text,
                                          'completed'::text])) va ON true
     LEFT JOIN LATERAL ( SELECT jsonb_agg(jsonb_build_object(
                'resource_id', c.resource_id,
                'display_name', res.display_name,
                'claim_active', (c.status = 'active'::text))
                ORDER BY res.display_name, c.resource_id) AS claimed_resources,
            array_agg(c.resource_id ORDER BY c.resource_id) AS claimed_resource_ids
           FROM request_engine.capacity_claims c
             JOIN request_engine.resources res
               ON res.organization_id = c.organization_id AND res.id = c.resource_id
          WHERE c.organization_id = r.organization_id AND c.reservation_id = r.id
            AND c.status <> 'replaced'::text) cl ON true
     LEFT JOIN LATERAL ( SELECT count(*)::integer AS note_count
           FROM request_engine.reservation_notes note
          WHERE note.organization_id = r.organization_id
            AND note.reservation_id = r.id) nc ON true;
"""


def upgrade() -> None:
    op.execute(_TABLE)
    op.execute(_NOTES_VIEW)
    op.execute(_DAY_BOARD_VIEW)
    op.execute(_CALENDAR_VIEW)


def downgrade() -> None:
    raise RuntimeError("reservation notes are append-only history; roll forward")
