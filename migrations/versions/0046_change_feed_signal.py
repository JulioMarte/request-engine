"""Signal committed outbox facts for the invalidation-only change feed (ADR 0020).

Change (expand-only):

``request_engine.outbox_messages.change_xid xid8``
    the top-level transaction id that appended the fact, defaulted by
    ``pg_current_xact_id()`` for new rows only (``ADD COLUMN`` without a
    default plus ``SET DEFAULT`` does not rewrite the table; rows appended
    before this revision stay NULL and are simply outside the replay window).
    It is the replay cursor primitive: a feed cursor is a ``pg_snapshot`` and a
    fact is "after" a cursor exactly when ``change_xid`` is not visible in that
    snapshot. Neither a sequence nor the uuidv7 ``id`` is commit ordered, so an
    "id > n" cursor could silently skip a fact whose transaction committed
    after a later-numbered one; the snapshot cursor cannot.
``request_engine.notify_outbox_change()`` + statement-level AFTER INSERT trigger
    issues ``pg_notify('request_engine_changes', '<organization_id>:<xid8>')``
    once per organization per inserting statement (PostgreSQL also folds
    identical payloads inside one transaction). The payload carries no event
    type, aggregate, payload or personal data. NOTIFY is transactional: it is
    delivered only after COMMIT, never for a rolled-back transaction, and in
    commit order.
``request_read.change_feed_v1``
    ``security_invoker`` read contract over committed outbox facts that maps
    each fact to its feed scope only: event type, aggregate kind/id,
    ``change_xid``, ``occurred_at``, ``queue_id``, ``location_id``,
    ``business_date`` and the linked ``reservation_id`` (used only to decide
    the ``day_board`` topic of QueueEntry facts). It never exposes
    ``payload``, ``correlation_data`` or delivery state. Topic routing lives in
    one Python table (``entrypoints/http/change_topics.py``).
``outbox_messages_change_feed_idx``
    ``(organization_id, change_xid) WHERE change_xid IS NOT NULL``, built
    ``CONCURRENTLY`` so outbox producers are not blocked.

Schema-change checklist (migrations/AGENTS.md):

- Business owner: none. Technical platform mechanics (outbox/events) consumed
  by the HTTP change-feed composition; facts stay owned by their producers
  (booking, queue, delivery, requests).
- Current guarantees affected: outbox durability/after-commit semantics
  (unchanged: same row, same status machine, same claim/lease functions); tenant
  Organization equality and RLS foreign-row opacity of ``request_read``.
- Change class / compatibility: additive (new nullable column, trigger, view,
  index). Existing INSERTs keep working without naming the column; workers and
  claim functions select explicit columns.
- Authoritative objects: ``request_engine.outbox_messages`` (column + trigger);
  ``reservations``, ``queue_entries``, ``service_sessions``, ``service_queues``,
  ``locations`` read only.
- READ/PLAN/LOCK/VALIDATE/WRITE/EMIT: the trigger is EMIT-only inside the
  producer's existing WRITE; it takes no lock, reads only the statement's
  transition table and performs no I/O. The view is a READ surface only.
- Serialization root / lock order: none added. The trigger never waits.
- Tenant/RLS/role: the view is owned by ``request_engine_schema_owner`` with
  ``security_invoker=true``, so the caller's outbox/reservation/queue/session
  RLS applies; only ``request_engine_app`` and ``request_engine_admin`` get
  SELECT. The trigger function is SECURITY INVOKER with a pinned search_path.
  NOTIFY channels are not access controlled in PostgreSQL, which is why the
  payload is limited to an organization id and a transaction id.
- Failure/concurrency: ``pg_notify`` cannot fail for this bounded payload at
  call time. The only commit-time failure mode of NOTIFY is a full 8 GB
  notification queue, which requires a listener that stops consuming while
  connected; the runtime listener drains continuously and reconnects. A missed
  or delayed notification never loses a fact: the feed reads by snapshot delta,
  so the next read for that organization returns it.
- Migration/roll-forward: DDL under brief ACCESS EXCLUSIVE on outbox_messages
  (catalog-only column add, trigger create); index built CONCURRENTLY.
  Roll-forward only; downgrade refused.
- Falsification proof: ``tests/e2e/test_change_feed_stream.py`` (commit-only
  delivery, rollback produces nothing, tenant isolation, PII-free data, replay
  in commit order, reset for unknown/too-old cursors) and
  ``tests/db/test_change_feed_signal.py`` (trigger payload, no payload data,
  invoker view RLS, grants).
"""

from alembic import op

revision: str = "0046_change_feed_signal"
down_revision: str | None = "0045_day_board_served_visit"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE request_engine.outbox_messages ADD COLUMN change_xid xid8;
ALTER TABLE request_engine.outbox_messages
    ALTER COLUMN change_xid SET DEFAULT pg_current_xact_id();
COMMENT ON COLUMN request_engine.outbox_messages.change_xid IS
    'Top-level xid8 of the appending transaction; change-feed snapshot cursor primitive.';

CREATE FUNCTION request_engine.notify_outbox_change() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY INVOKER
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
BEGIN
    FOR v_organization_id IN
        SELECT DISTINCT organization_id FROM new_outbox_rows
    LOOP
        PERFORM pg_notify(
            'request_engine_changes',
            v_organization_id::text || ':' || pg_current_xact_id()::text
        );
    END LOOP;
    RETURN NULL;
END
$$;
ALTER FUNCTION request_engine.notify_outbox_change() OWNER TO request_engine_schema_owner;
REVOKE ALL ON FUNCTION request_engine.notify_outbox_change() FROM PUBLIC;

CREATE TRIGGER outbox_messages_change_notify
    AFTER INSERT ON request_engine.outbox_messages
    REFERENCING NEW TABLE AS new_outbox_rows
    FOR EACH STATEMENT
    EXECUTE FUNCTION request_engine.notify_outbox_change();

CREATE VIEW request_read.change_feed_v1
    WITH (security_invoker = 'true') AS
SELECT o.organization_id,
       o.id AS event_id,
       o.event_type,
       o.aggregate_kind,
       o.aggregate_id,
       o.change_xid,
       o.occurred_at,
       CASE o.aggregate_kind
           WHEN 'QueueEntry'::text THEN qe.service_queue_id
           WHEN 'ServiceSession'::text THEN sqe.service_queue_id
           ELSE NULL::uuid
       END AS queue_id,
       CASE o.aggregate_kind
           WHEN 'Reservation'::text THEN r.location_id
           WHEN 'QueueEntry'::text THEN q.location_id
           WHEN 'ServiceSession'::text THEN ss.location_id
           ELSE NULL::uuid
       END AS location_id,
       CASE o.aggregate_kind
           WHEN 'Reservation'::text
               THEN (lower(r.during) AT TIME ZONE rl.timezone)::date
           WHEN 'QueueEntry'::text
               THEN (o.occurred_at AT TIME ZONE el.timezone)::date
           WHEN 'ServiceSession'::text
               THEN (o.occurred_at AT TIME ZONE el.timezone)::date
           ELSE NULL::date
       END AS business_date,
       CASE o.aggregate_kind
           WHEN 'Reservation'::text THEN r.id
           WHEN 'QueueEntry'::text THEN qe.reservation_id
           WHEN 'ServiceSession'::text THEN sqe.reservation_id
           ELSE NULL::uuid
       END AS reservation_id
  FROM request_engine.outbox_messages o
  LEFT JOIN request_engine.reservations r
    ON o.aggregate_kind = 'Reservation'::text
   AND r.organization_id = o.organization_id AND r.id = o.aggregate_id
  LEFT JOIN request_engine.locations rl
    ON rl.organization_id = r.organization_id AND rl.id = r.location_id
  LEFT JOIN request_engine.queue_entries qe
    ON o.aggregate_kind = 'QueueEntry'::text
   AND qe.organization_id = o.organization_id AND qe.id = o.aggregate_id
  LEFT JOIN request_engine.service_sessions ss
    ON o.aggregate_kind = 'ServiceSession'::text
   AND ss.organization_id = o.organization_id AND ss.id = o.aggregate_id
  LEFT JOIN request_engine.queue_entries sqe
    ON sqe.organization_id = ss.organization_id AND sqe.id = ss.queue_entry_id
  LEFT JOIN request_engine.service_queues q
    ON q.organization_id = qe.organization_id AND q.id = qe.service_queue_id
  LEFT JOIN request_engine.locations el
    ON el.organization_id = o.organization_id
   AND el.id = CASE o.aggregate_kind
                   WHEN 'QueueEntry'::text THEN q.location_id
                   WHEN 'ServiceSession'::text THEN ss.location_id
                   ELSE NULL::uuid
               END
 WHERE o.change_xid IS NOT NULL;
ALTER VIEW request_read.change_feed_v1 OWNER TO request_engine_schema_owner;
REVOKE ALL ON request_read.change_feed_v1 FROM PUBLIC;
GRANT SELECT ON request_read.change_feed_v1 TO request_engine_app;
GRANT SELECT ON request_read.change_feed_v1 TO request_engine_admin;
""")
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS outbox_messages_change_feed_idx "
            "ON request_engine.outbox_messages (organization_id, change_xid) "
            "WHERE change_xid IS NOT NULL"
        )


def downgrade() -> None:
    raise RuntimeError("change feed signal is roll-forward only")
