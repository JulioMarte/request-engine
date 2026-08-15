BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_cmd, request_admin, pg_catalog;

-- Runtime function privileges are reconciled after the release-wide PUBLIC
-- EXECUTE revocation. Internal integrity helpers remain unreachable directly
-- from runtime roles, while deferred constraint triggers execute as the schema
-- owner and can call those helpers safely.
ALTER FUNCTION request_engine.check_capacity_owner_completeness()
    SECURITY DEFINER;
ALTER FUNCTION request_engine.check_capacity_owner_completeness()
    SET search_path = pg_catalog, request_engine;

REVOKE ALL ON FUNCTION request_engine.assert_hold_claim_completeness(uuid, uuid)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.assert_reservation_claim_completeness(uuid, uuid)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.check_capacity_owner_completeness()
    FROM PUBLIC;

-- Worker discovery/finalization is an explicit capability. Re-state the grants
-- after privilege hardening so later CREATE OR REPLACE changes cannot make the
-- effective runtime contract depend on historical ACL state.
GRANT EXECUTE ON FUNCTION request_cmd.claim_scheduled_actions(integer, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.complete_scheduled_action(uuid, uuid)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_scheduled_action(uuid, uuid, timestamptz, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.dead_letter_scheduled_action(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.renew_scheduled_action_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_scheduled_action_after(uuid, uuid, interval, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.lock_scheduled_action_claim(uuid, uuid)
    TO request_engine_worker;

GRANT EXECUTE ON FUNCTION request_cmd.claim_outbox_messages(integer, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.complete_outbox_message(uuid, uuid)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_outbox_message(uuid, uuid, timestamptz, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.dead_letter_outbox_message(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.renew_outbox_message_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_outbox_message_after(uuid, uuid, interval, text)
    TO request_engine_worker, request_engine_admin;

GRANT EXECUTE ON FUNCTION request_cmd.claim_provider_events(integer, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.renew_provider_event_lease(uuid, uuid, interval)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.complete_provider_event(uuid, uuid)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.retry_provider_event_after(uuid, uuid, interval, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.reject_provider_event(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.dead_letter_provider_event(uuid, uuid, text)
    TO request_engine_worker, request_engine_admin;

RESET ROLE;
COMMIT;
