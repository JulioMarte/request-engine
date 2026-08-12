BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_admin, pg_catalog;

CREATE VIEW request_read.business_info_v1
WITH (security_invoker = true)
AS
SELECT
    o.id AS organization_id,
    o.organization_key,
    o.display_name,
    o.public_profile
FROM request_engine.organizations o;

CREATE VIEW request_read.locations_v1
WITH (security_invoker = true)
AS
SELECT
    l.id,
    l.organization_id,
    l.location_key,
    l.display_name,
    l.timezone,
    l.public_data,
    l.active
FROM request_engine.locations l;

CREATE VIEW request_read.offering_summary_v1
WITH (security_invoker = true)
AS
SELECT DISTINCT ON (o.id)
    o.id AS offering_id,
    o.organization_id,
    o.offering_key,
    o.display_name,
    o.description,
    ov.id AS offering_version_id,
    ov.version,
    ov.duration_minutes,
    ov.bookable,
    ov.requestable,
    ov.public_data
FROM request_engine.offerings o
JOIN request_engine.offering_versions ov
  ON ov.organization_id = o.organization_id
 AND ov.offering_id = o.id
WHERE o.active
ORDER BY o.id, ov.version DESC;

CREATE VIEW request_read.reservation_status_v1
WITH (security_invoker = true)
AS
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
    ar.responded_at AS attendance_responded_at
FROM request_engine.reservations r
LEFT JOIN LATERAL (
    SELECT a.response, a.responded_at
      FROM request_engine.attendance_responses a
     WHERE a.organization_id = r.organization_id
       AND a.reservation_id = r.id
     ORDER BY a.responded_at DESC, a.id DESC
     LIMIT 1
) ar ON true;

CREATE VIEW request_read.service_queue_status_v1
WITH (security_invoker = true)
AS
SELECT
    q.id AS queue_id,
    q.organization_id,
    q.queue_key,
    q.display_name,
    e.id AS queue_entry_id,
    e.subject_party_id,
    e.status,
    e.admitted_at,
    e.called_at,
    e.service_started_at,
    e.completed_at,
    e.revision
FROM request_engine.service_queues q
LEFT JOIN request_engine.queue_entries e
  ON e.organization_id = q.organization_id
 AND e.service_queue_id = q.id;

CREATE VIEW request_read.waitlist_status_v1
WITH (security_invoker = true)
AS
SELECT
    w.id AS waitlist_entry_id,
    w.organization_id,
    w.offering_id,
    w.subject_party_id,
    w.location_id,
    w.status,
    w.created_at,
    w.revision,
    so.id AS active_slot_offer_id,
    so.slot_opportunity_id,
    so.expires_at AS slot_offer_expires_at
FROM request_engine.waitlist_entries w
LEFT JOIN request_engine.slot_offers so
  ON so.organization_id = w.organization_id
 AND so.waitlist_entry_id = w.id
 AND so.status = 'offered'
 AND so.expires_at > clock_timestamp();

CREATE VIEW request_read.request_status_v1
WITH (security_invoker = true)
AS
SELECT
    r.id AS request_id,
    r.organization_id,
    rd.request_key,
    rdv.version AS definition_version,
    r.requester_party_id,
    r.recipient_party_id,
    r.status,
    r.result_payload,
    r.revision,
    r.created_at,
    r.completed_at,
    r.updated_at
FROM request_engine.requests r
JOIN request_engine.request_definition_versions rdv
  ON rdv.organization_id = r.organization_id
 AND rdv.id = r.request_definition_version_id
JOIN request_engine.request_definitions rd
  ON rd.organization_id = rdv.organization_id
 AND rd.id = rdv.request_definition_id;

CREATE VIEW request_admin.scheduled_action_health_v1
AS
SELECT
    organization_id,
    status,
    count(*) AS action_count,
    min(next_attempt_at) FILTER (WHERE status = 'pending') AS oldest_pending_at,
    min(lease_until) FILTER (WHERE status = 'leased') AS oldest_lease_until,
    max(attempt_count) AS max_attempt_count
FROM request_engine.scheduled_actions
GROUP BY organization_id, status;

CREATE VIEW request_admin.outbox_health_v1
AS
SELECT
    organization_id,
    status,
    count(*) AS message_count,
    min(next_attempt_at) FILTER (WHERE status = 'pending') AS oldest_pending_at,
    min(lease_until) FILTER (WHERE status = 'leased') AS oldest_lease_until,
    max(attempt_count) AS max_attempt_count
FROM request_engine.outbox_messages
GROUP BY organization_id, status;

RESET ROLE;

REVOKE ALL ON ALL TABLES IN SCHEMA request_engine FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA request_read FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA request_admin FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA request_cmd FROM PUBLIC;

-- Runtime roles use RLS-protected tenant tables. DELETE is deliberately absent;
-- lifecycle removal is expressed through semantic UPDATE commands.
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA request_engine
    TO request_engine_app, request_engine_worker;

GRANT SELECT ON ALL TABLES IN SCHEMA request_read
    TO request_engine_app, request_engine_worker, request_engine_admin;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA request_engine
    TO request_engine_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA request_admin
    TO request_engine_admin;

GRANT EXECUTE ON FUNCTION request_cmd.acquire_idempotency(uuid, uuid, text, text, text)
    TO request_engine_app, request_engine_worker;
GRANT EXECUTE ON FUNCTION request_cmd.complete_idempotency(uuid, jsonb)
    TO request_engine_app, request_engine_worker;

GRANT EXECUTE ON FUNCTION request_cmd.claim_scheduled_actions(integer, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.complete_scheduled_action(uuid, uuid)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_scheduled_action(uuid, uuid, timestamptz, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.dead_letter_scheduled_action(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;

GRANT EXECUTE ON FUNCTION request_cmd.claim_outbox_messages(integer, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.complete_outbox_message(uuid, uuid)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_outbox_message(uuid, uuid, timestamptz, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.dead_letter_outbox_message(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;

COMMIT;
