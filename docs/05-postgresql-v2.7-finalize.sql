-- Request Engine V2.7 — hardening finalization
-- Target: PostgreSQL 18+
-- Applies after:
--   docs/03-postgresql-schema.sql
--   docs/04-postgresql-v2.7-hardening.sql
--
-- This file intentionally replaces a few V2.7 trigger implementations found to
-- be too row-centric during self-review. The final database state after 03→04→05
-- is the V2.7 schema candidate.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET search_path = request_engine, public;

-- ============================================================================
-- 1. PlanningRevision belongs to the semantic command, not each physical row
-- ============================================================================

DROP TRIGGER IF EXISTS trg_capacity_claims_planning_revision ON capacity_claims;
DROP FUNCTION IF EXISTS request_engine.bump_claim_planning_revision();

COMMENT ON COLUMN capacity_authorities.planning_revision IS
'Increment exactly once by a semantic command that changes the bounded planning state; never once per physical CapacityClaim row.';

-- ============================================================================
-- 2. Trigger helpers must handle INSERT / UPDATE / DELETE explicitly
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.check_allocation_claim_cardinality()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_allocation_id bigint;
    v_org_id bigint;
    v_state text;
    v_count integer;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_allocation_id := NEW.resource_allocation_id;
        v_org_id := NEW.organization_id;
    ELSE
        v_allocation_id := COALESCE(NEW.resource_allocation_id, OLD.resource_allocation_id);
        v_org_id := COALESCE(NEW.organization_id, OLD.organization_id);
    END IF;

    IF v_allocation_id IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT state
      INTO v_state
      FROM resource_allocations
     WHERE organization_id = v_org_id
       AND resource_allocation_id = v_allocation_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT count(*)
      INTO v_count
      FROM capacity_claims
     WHERE organization_id = v_org_id
       AND resource_allocation_id = v_allocation_id
       AND claim_kind = 'allocation'
       AND state = 'active';

    IF (v_state = 'active' AND v_count <> 1)
       OR (v_state <> 'active' AND v_count <> 0) THEN
        RAISE EXCEPTION 'ResourceAllocation/CapacityClaim cardinality violation'
            USING ERRCODE = '23514';
    END IF;

    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION request_engine.bump_capacity_schedule_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org bigint;
    v_authority bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_authority := OLD.capacity_authority_id;
    ELSE
        v_org := NEW.organization_id;
        v_authority := NEW.capacity_authority_id;
    END IF;

    UPDATE capacity_authorities
       SET schedule_revision = schedule_revision + 1
     WHERE organization_id = v_org
       AND capacity_authority_id = v_authority;

    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION request_engine.bump_resource_configuration_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org bigint;
    v_resource bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_resource := OLD.resource_id;
    ELSE
        v_org := NEW.organization_id;
        v_resource := NEW.resource_id;
    END IF;

    UPDATE capacity_authorities
       SET configuration_revision = configuration_revision + 1
     WHERE organization_id = v_org
       AND resource_id = v_resource;

    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION request_engine.bump_pool_configuration_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org bigint;
    v_pool bigint;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_pool := OLD.capacity_pool_id;
    ELSE
        v_org := NEW.organization_id;
        v_pool := NEW.capacity_pool_id;
    END IF;

    UPDATE capacity_authorities
       SET configuration_revision = configuration_revision + 1
     WHERE organization_id = v_org
       AND capacity_pool_id = v_pool;

    RETURN NULL;
END;
$$;

-- A pool status change affects reservability just as membership does.
DROP TRIGGER IF EXISTS trg_capacity_pool_status_revision ON capacity_pools;
CREATE TRIGGER trg_capacity_pool_status_revision
AFTER UPDATE OF status ON capacity_pools
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION request_engine.bump_pool_configuration_revision();

-- ============================================================================
-- 3. Financial reduction arithmetic: avoid join multiplication
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_eligible_value_reduction()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_allocated bigint;
    v_adjusted bigint;
BEGIN
    IF NEW.current_eligible_amount_minor >= OLD.current_eligible_amount_minor THEN
        RETURN NEW;
    END IF;

    SELECT COALESCE(sum(pa.allocated_amount_minor), 0)
      INTO v_allocated
      FROM payment_allocations pa
     WHERE pa.organization_id = OLD.organization_id
       AND pa.payment_transaction_id = OLD.payment_transaction_id;

    SELECT COALESCE(sum(adj.amount_minor), 0)
      INTO v_adjusted
      FROM payment_allocation_adjustments adj
      JOIN payment_allocations pa
        ON pa.organization_id = adj.organization_id
       AND pa.payment_allocation_id = adj.payment_allocation_id
     WHERE pa.organization_id = OLD.organization_id
       AND pa.payment_transaction_id = OLD.payment_transaction_id;

    IF v_allocated - v_adjusted > NEW.current_eligible_amount_minor
       AND NOT EXISTS (
            SELECT 1
              FROM reconciliation_cases rc
             WHERE rc.organization_id = OLD.organization_id
               AND rc.payment_transaction_id = OLD.payment_transaction_id
               AND rc.status IN ('open','under_review')
       ) THEN
        RAISE EXCEPTION 'eligible-value reduction requires adjustments or ReconciliationCase'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

-- ============================================================================
-- 4. Commitment history is update-oriented, never physically deleted
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.prevent_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% history cannot be deleted', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS trg_capacity_claims_no_delete ON capacity_claims;
CREATE TRIGGER trg_capacity_claims_no_delete
BEFORE DELETE ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_delete();

DROP TRIGGER IF EXISTS trg_resource_allocations_no_delete ON resource_allocations;
CREATE TRIGGER trg_resource_allocations_no_delete
BEFORE DELETE ON resource_allocations
FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_delete();

-- ============================================================================
-- 5. Explicit command-owned PlanningRevision helper
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.advance_planning_revision(
    p_organization_id bigint,
    p_capacity_authority_id bigint,
    p_expected_revision bigint
)
RETURNS bigint
LANGUAGE plpgsql
AS $$
DECLARE
    v_revision bigint;
BEGIN
    UPDATE capacity_authorities
       SET planning_revision = planning_revision + 1
     WHERE organization_id = p_organization_id
       AND capacity_authority_id = p_capacity_authority_id
       AND planning_revision = p_expected_revision
     RETURNING planning_revision INTO v_revision;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'stale PlanningRevision for CapacityAuthority %',
            p_capacity_authority_id USING ERRCODE = '40001';
    END IF;

    RETURN v_revision;
END;
$$;

COMMENT ON FUNCTION request_engine.advance_planning_revision(bigint,bigint,bigint) IS
'Call once per semantic planning-sensitive command after all relevant authority rows are already locked in canonical order.';

-- ============================================================================
-- 6. Final V2.7 protocol statement
-- ============================================================================
--
-- Final physical responsibility split:
--
-- STRUCTURAL CONSTRAINTS
--   tenant equality, typed lineage, one allocation claim, bounded intervals,
--   state/value shape, provider/idempotency uniqueness.
--
-- SMALL TRIGGERS
--   history monotonicity, immutable ingress identity, configuration/schedule
--   revision bumps, wall-clock hold validation, basic aggregate backstops.
--
-- DEFERRED CONSTRAINT TRIGGERS
--   active ResourceAllocation <-> exactly one active CapacityClaim.
--
-- COMMAND TRANSACTIONS
--   compound multi-authority acquisition, variable schedule change-point proof,
--   pool/direct-member conflict, shared-requirement amendments, atomic reschedule,
--   completion/correction races, PlanningRevision advancement, financial
--   correction attribution and policy-specific refundable value.
--
-- A command-level invariant is valid only when docs/02 names its stable lock root
-- and lock order. A naked pre-check outside that transaction is never authority.

COMMIT;
