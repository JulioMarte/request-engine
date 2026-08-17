BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = pg_catalog;

-- The deferred SlotOffer source-consistency constraint is part of the database
-- invariant boundary, not a runtime callable API. PostgreSQL executes trigger
-- functions even when the invoking role has no direct EXECUTE privilege, but
-- the wrapper previously ran as SECURITY INVOKER and its nested call to the
-- private assertion helper therefore inherited request_engine_app privileges.
-- A legitimate app transaction could reach COMMIT and fail with 42501 before
-- the invariant could be evaluated.
--
-- Keep both routines private. Only the trigger wrapper executes as the schema
-- owner so it can evaluate the final-state invariant. Fix search_path exactly
-- to the repository's SECURITY DEFINER hardening contract, including pg_temp
-- last so temporary objects cannot shadow trusted objects.
ALTER FUNCTION request_engine.check_offered_slot_offer_source_consistency()
    SECURITY DEFINER;
ALTER FUNCTION request_engine.check_offered_slot_offer_source_consistency()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.check_offered_slot_offer_source_consistency()
    OWNER TO request_engine_schema_owner;

REVOKE ALL ON FUNCTION request_engine.check_offered_slot_offer_source_consistency()
    FROM PUBLIC, request_engine_app, request_engine_worker, request_engine_admin;
REVOKE ALL ON FUNCTION request_engine.assert_offered_slot_offer_source_consistency(uuid, uuid)
    FROM PUBLIC, request_engine_app, request_engine_worker, request_engine_admin;

RESET search_path;
RESET ROLE;
COMMIT;
