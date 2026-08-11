-- Request Engine V2.10 — routine resolution hardening
-- Target: PostgreSQL 18+
-- Applies after: docs/08-postgresql-v2.10-access-surface.sql
--
-- Existing trigger/helper routines were created before the explicit DB access
-- contract. Pin their runtime search_path so object resolution never depends on
-- a caller-controlled session search_path. This does not change domain behavior.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

ALTER FUNCTION request_engine.prevent_fact_mutation()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.touch_updated_at()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_request_terminality()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_payment_requirement_repricing()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.enforce_payment_allocation_budget()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.enforce_allocation_adjustment_budget()
    SET search_path = pg_catalog, request_engine, pg_temp;

ALTER FUNCTION request_engine.guard_fulfillment()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_capacity_claim()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.check_allocation_claim_cardinality()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.bump_schedule_revision()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.bump_resource_revision()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.bump_pool_revision()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.advance_planning_revision(bigint, bigint, bigint)
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.prevent_delete()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_commitment_history()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_capacity_hold_transition()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_reservation_terminal_capacity()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_provider_event_identity()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_idempotency_identity()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_eligible_value_reduction()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_refund_budget()
    SET search_path = pg_catalog, request_engine, pg_temp;
ALTER FUNCTION request_engine.guard_reservation_request_target()
    SET search_path = pg_catalog, request_engine, pg_temp;

-- V2.10 public persistence primitives already declare the same secure path at
-- CREATE FUNCTION time. Revoke PUBLIC again at the schema level as an explicit
-- deny-by-default postcondition after the full migration chain.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA request_cmd FROM PUBLIC;

COMMIT;
