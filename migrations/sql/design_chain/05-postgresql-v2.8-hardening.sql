-- Request Engine V2.8 — PostgreSQL DBA hardening
-- Target: PostgreSQL 18+
-- Applies after:
--   docs/03-postgresql-schema.sql
--   docs/04-postgresql-v2.7-hardening.sql
-- Normative source: docs/02-pre-sql-domain-contract.md
--
-- V2.8 is intentionally small. It fixes lock-order/lifecycle details and removes
-- redundant index/trigger surface discovered during the post-V2.7 DBA review.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = request_engine, public;

-- ============================================================================
-- 1. CapacityClaim lock order: CAPACITY_HOLD -> CAPACITY_AUTHORITY
-- ============================================================================
--
-- docs/02 defines CAPACITY_HOLD before CAPACITY_AUTHORITY in the canonical lock
-- order. A trigger must not silently invert that order. Allocation identity is
-- read without an extra row lock; Allocation/Claim active-state cardinality is
-- owned by the deferred constraint trigger already installed by V2.7.

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_claim()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_authority capacity_authorities%ROWTYPE;
    v_hold capacity_holds%ROWTYPE;
    v_allocation resource_allocations%ROWTYPE;
    v_now timestamptz := clock_timestamp();
    v_peak numeric(30,6);
BEGIN
    -- Decreasing consumption is monotonic. Never make release depend on whether
    -- the acquisition snapshot is still current.
    IF TG_OP = 'UPDATE' AND NEW.state <> 'active' THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' AND NEW.state <> 'active' THEN
        RAISE EXCEPTION 'CapacityClaim must be created active'
            USING ERRCODE = '23514';
    END IF;

    -- Hold-backed claims obey the canonical lock order explicitly.
    IF NEW.claim_kind = 'hold' THEN
        SELECT *
          INTO v_hold
          FROM capacity_holds
         WHERE organization_id = NEW.organization_id
           AND capacity_hold_id = NEW.capacity_hold_id
         FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'CapacityHold not found' USING ERRCODE = '23503';
        END IF;

        IF v_hold.state <> 'active' OR v_hold.expires_at <= v_now THEN
            RAISE EXCEPTION 'CapacityHold is not logically live'
                USING ERRCODE = '23514';
        END IF;

        -- Derived snapshot; callers never author this value independently.
        NEW.hold_expires_at := v_hold.expires_at;
    ELSE
        -- This check proves only immutable consumption identity. Whether the
        -- Allocation is active is checked once, at transaction end, by
        -- check_allocation_claim_cardinality().
        SELECT *
          INTO v_allocation
          FROM resource_allocations
         WHERE organization_id = NEW.organization_id
           AND resource_allocation_id = NEW.resource_allocation_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'ResourceAllocation not found' USING ERRCODE = '23503';
        END IF;

        IF v_allocation.capacity_authority_id <> NEW.capacity_authority_id
           OR v_allocation.quantity <> NEW.quantity
           OR v_allocation.conflict_range <> NEW.conflict_range THEN
            RAISE EXCEPTION 'CapacityClaim does not match ResourceAllocation consumption identity'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    SELECT *
      INTO v_authority
      FROM capacity_authorities
     WHERE organization_id = NEW.organization_id
       AND capacity_authority_id = NEW.capacity_authority_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CapacityAuthority not found' USING ERRCODE = '23503';
    END IF;

    IF NEW.authority_configuration_revision <> v_authority.configuration_revision
       OR NEW.authority_schedule_revision <> v_authority.schedule_revision
       OR (NEW.planning_revision IS NOT NULL
           AND NEW.planning_revision <> v_authority.planning_revision) THEN
        RAISE EXCEPTION 'stale CapacityAuthority revision'
            USING ERRCODE = '40001';
    END IF;

    IF v_authority.capacity_model = 'exclusive' THEN
        IF EXISTS (
            SELECT 1
              FROM capacity_claims c
              LEFT JOIN capacity_holds h
                ON h.organization_id = c.organization_id
               AND h.capacity_hold_id = c.capacity_hold_id
             WHERE c.organization_id = NEW.organization_id
               AND c.capacity_authority_id = NEW.capacity_authority_id
               AND c.capacity_claim_id <> COALESCE(NEW.capacity_claim_id, -1)
               AND c.state = 'active'
               AND c.conflict_range && NEW.conflict_range
               AND (
                    c.claim_kind = 'allocation'
                    OR (h.state = 'active' AND h.expires_at > v_now)
               )
        ) THEN
            RAISE EXCEPTION 'exclusive capacity conflict on authority %',
                NEW.capacity_authority_id USING ERRCODE = '23P01';
        END IF;

        RETURN NEW;
    END IF;

    -- Base-capacity backstop. Variable capacity remains command-owned because its
    -- effective limit is schedule/policy derived and must be evaluated at every
    -- schedule/exception change point while the same authority row is locked.
    WITH live AS (
        SELECT c.conflict_range, c.quantity
          FROM capacity_claims c
          LEFT JOIN capacity_holds h
            ON h.organization_id = c.organization_id
           AND h.capacity_hold_id = c.capacity_hold_id
         WHERE c.organization_id = NEW.organization_id
           AND c.capacity_authority_id = NEW.capacity_authority_id
           AND c.capacity_claim_id <> COALESCE(NEW.capacity_claim_id, -1)
           AND c.state = 'active'
           AND c.conflict_range && NEW.conflict_range
           AND (
                c.claim_kind = 'allocation'
                OR (h.state = 'active' AND h.expires_at > v_now)
           )
    ), points AS (
        SELECT lower(NEW.conflict_range) AS p
        UNION
        SELECT upper(NEW.conflict_range)
        UNION
        SELECT greatest(lower(conflict_range), lower(NEW.conflict_range)) FROM live
        UNION
        SELECT least(upper(conflict_range), upper(NEW.conflict_range)) FROM live
    ), segments AS (
        SELECT p AS segment_start,
               lead(p) OVER (ORDER BY p) AS segment_end
          FROM points
    ), loads AS (
        SELECT s.segment_start,
               COALESCE(sum(l.quantity) FILTER (
                   WHERE l.conflict_range @> s.segment_start
               ), 0) + NEW.quantity AS load
          FROM segments s
          LEFT JOIN live l ON l.conflict_range @> s.segment_start
         WHERE s.segment_end IS NOT NULL
           AND s.segment_start < s.segment_end
         GROUP BY s.segment_start
    )
    SELECT COALESCE(max(load), NEW.quantity)
      INTO v_peak
      FROM loads;

    IF v_peak > v_authority.base_capacity_units THEN
        RAISE EXCEPTION 'unit capacity exceeded on authority %',
            NEW.capacity_authority_id USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

-- ============================================================================
-- 2. CapacityHold lifecycle is strictly monotonic and wall-clock safe
-- ============================================================================

-- V2.6 created trg_capacity_holds_guard_transition and V2.7 introduced the
-- canonical trg_capacity_holds_transition while reusing the same function.
-- Keep exactly one trigger so lifecycle validation has one execution path.
DROP TRIGGER IF EXISTS trg_capacity_holds_guard_transition ON capacity_holds;

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_hold_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.state IS NOT DISTINCT FROM OLD.state THEN
        RETURN NEW;
    END IF;

    IF OLD.state <> 'active'
       OR NEW.state NOT IN ('confirmed','released','expired') THEN
        RAISE EXCEPTION 'invalid CapacityHold transition: % -> %', OLD.state, NEW.state
            USING ERRCODE = '55000';
    END IF;

    IF NEW.state = 'confirmed' AND OLD.expires_at <= clock_timestamp() THEN
        RAISE EXCEPTION 'expired CapacityHold cannot be confirmed'
            USING ERRCODE = '55000';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM capacity_claims c
         WHERE c.organization_id = OLD.organization_id
           AND c.capacity_hold_id = OLD.capacity_hold_id
           AND c.claim_kind = 'hold'
           AND c.state = 'active'
    ) THEN
        RAISE EXCEPTION 'CapacityHold cannot transition with active hold claims'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

-- Existing trigger trg_capacity_holds_transition automatically uses the replaced
-- function definition; no duplicate trigger is required.

-- ============================================================================
-- 3. Index diet: retain only indexes that match real hot predicates
-- ============================================================================
--
-- V2.6 already has ix_capacity_claims_live_overlap as a partial GiST index over
-- (organization_id, capacity_authority_id, conflict_range) WHERE state='active'.
-- The extra B-tree authority/state index added in V2.7 duplicated that hot path.

DROP INDEX IF EXISTS ix_capacity_claims_authority_active;

DROP INDEX IF EXISTS ix_capacity_claims_hold_active;
CREATE INDEX ix_capacity_claims_hold_active
    ON capacity_claims (organization_id, capacity_hold_id)
    WHERE claim_kind = 'hold' AND state = 'active';

DROP INDEX IF EXISTS ix_refunds_transaction_live;
CREATE INDEX ix_refunds_transaction_live
    ON refunds (organization_id, payment_transaction_id)
    INCLUDE (amount_minor)
    WHERE status IN ('requested','processing','succeeded');

DROP INDEX IF EXISTS ix_reconciliation_cases_transaction_live;
CREATE INDEX ix_reconciliation_cases_transaction_live
    ON reconciliation_cases (organization_id, payment_transaction_id)
    WHERE status IN ('open','under_review');

-- ============================================================================
-- 4. Immutable identities use NULL-safe comparison
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_provider_event_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF ROW(
        NEW.organization_id,
        NEW.provider_connection_id,
        NEW.provider_event_id,
        NEW.canonical_payload_hash,
        NEW.payload,
        NEW.authentication_result,
        NEW.received_at
    ) IS DISTINCT FROM ROW(
        OLD.organization_id,
        OLD.provider_connection_id,
        OLD.provider_event_id,
        OLD.canonical_payload_hash,
        OLD.payload,
        OLD.authentication_result,
        OLD.received_at
    ) THEN
        RAISE EXCEPTION 'ProviderEvent envelope is immutable'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION request_engine.guard_idempotency_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF ROW(
        NEW.organization_id,
        NEW.scope,
        NEW.idempotency_key,
        NEW.canonical_request_hash,
        NEW.created_by_principal_id,
        NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.organization_id,
        OLD.scope,
        OLD.idempotency_key,
        OLD.canonical_request_hash,
        OLD.created_by_principal_id,
        OLD.created_at
    ) THEN
        RAISE EXCEPTION 'Idempotency identity is immutable'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

-- ============================================================================
-- 5. Boundary remains explicit
-- ============================================================================
--
-- PostgreSQL owns local structural integrity and stable-row serialization.
-- Command transactions still own multi-root lock planning, variable schedule
-- capacity, pool/member realization, reschedule replacement semantics, external
-- feasibility, completion/correction races and policy-specific financial truth.
--
-- Do not add a trigger merely to avoid writing the documented command protocol.

COMMIT;
