BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = pg_catalog;

-- Production Worker Assembly split worker control-plane sessions from
-- authoritative domain sessions. Domain commands run through
-- request_engine_app; request_engine_worker should therefore not retain
-- historical EXECUTE grants for idempotency or Party-authority primitives.
REVOKE EXECUTE ON FUNCTION
    request_cmd.acquire_idempotency(uuid, uuid, text, text, text)
    FROM request_engine_worker;
REVOKE EXECUTE ON FUNCTION
    request_cmd.complete_idempotency(uuid, jsonb)
    FROM request_engine_worker;
REVOKE EXECUTE ON FUNCTION
    request_engine.resolve_current_party_authority(uuid, uuid, uuid, text)
    FROM request_engine_worker;
REVOKE EXECUTE ON FUNCTION
    request_engine.lock_current_party_authority(uuid, uuid, uuid, text)
    FROM request_engine_worker;

-- Worker control-plane code has no query-side contract. Domain handlers that
-- need request_read views use their separate request_engine_app session.
REVOKE USAGE ON SCHEMA request_read FROM request_engine_worker;

RESET ROLE;
COMMIT;
