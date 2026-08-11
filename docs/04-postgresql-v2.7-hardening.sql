-- Request Engine V2.7 — PostgreSQL hardening migration
-- Target: PostgreSQL 18+
-- Applies after: docs/03-postgresql-schema.sql
-- Normative source: docs/02-pre-sql-domain-contract.md
--
-- Goal: close physical integrity gaps found during the post-schema adversarial
-- review without turning PostgreSQL into a hidden workflow engine.
--
-- Rule of thumb:
--   FK / UNIQUE / CHECK    -> structural truth
--   small trigger          -> monotonicity, immutable identity, revision bump
--   deferred constraint    -> end-of-transaction cardinality
--   stable row lock        -> aggregate/concurrency invariant
--
-- No network calls. No generic polymorphic references. No implicit FX.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET search_path = request_engine, public;

-- ============================================================================
-- 1. Close relational graph holes with composite keys
-- ============================================================================

-- Fulfillment must use the exact OfferingSelection owned by its OutcomeScope.
ALTER TABLE outcome_scopes
    ADD CONSTRAINT uq_outcome_scopes_fulfillment_key
    UNIQUE (organization_id, request_id, outcome_scope_id, offering_selection_id);

ALTER TABLE fulfillments
    ADD CONSTRAINT fk_fulfillments_scope_selection
    FOREIGN KEY (organization_id, request_id, outcome_scope_id, offering_selection_id)
    REFERENCES outcome_scopes
        (organization_id, request_id, outcome_scope_id, offering_selection_id)
    ON DELETE RESTRICT;

-- A correction cannot claim a different OutcomeScope from the Fulfillment it
-- corrects.
ALTER TABLE fulfillments
    ADD CONSTRAINT uq_fulfillments_correction_key
    UNIQUE (organization_id, fulfillment_id, outcome_scope_id);

ALTER TABLE fulfillment_corrections
    DROP CONSTRAINT fk_fulfillment_corrections_fulfillment,
    ADD CONSTRAINT fk_fulfillment_corrections_fulfillment_scope
    FOREIGN KEY (organization_id, fulfillment_id, outcome_scope_id)
    REFERENCES fulfillments (organization_id, fulfillment_id, outcome_scope_id)
    ON DELETE RESTRICT;

-- Requirement / item / allocation lineage must remain inside one Reservation.
ALTER TABLE commitment_requirements
    ADD CONSTRAINT uq_commitment_requirements_reservation_key
    UNIQUE (organization_id, reservation_id, commitment_requirement_id);

ALTER TABLE commitment_requirement_items
    ADD COLUMN reservation_id bigint;

UPDATE commitment_requirement_items cri
   SET reservation_id = cr.reservation_id
  FROM commitment_requirements cr
 WHERE cr.organization_id = cri.organization_id
   AND cr.commitment_requirement_id = cri.commitment_requirement_id;

ALTER TABLE commitment_requirement_items
    ALTER COLUMN reservation_id SET NOT NULL,
    DROP CONSTRAINT fk_commitment_requirement_items_requirement,
    DROP CONSTRAINT fk_commitment_requirement_items_item,
    ADD CONSTRAINT fk_commitment_requirement_items_requirement
        FOREIGN KEY (organization_id, reservation_id, commitment_requirement_id)
        REFERENCES commitment_requirements
            (organization_id, reservation_id, commitment_requirement_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT fk_commitment_requirement_items_item
        FOREIGN KEY (organization_id, reservation_id, reservation_item_id)
        REFERENCES reservation_items
            (organization_id, reservation_id, reservation_item_id)
        ON DELETE RESTRICT;

ALTER TABLE resource_allocations
    DROP CONSTRAINT fk_resource_allocations_requirement,
    ADD CONSTRAINT fk_resource_allocations_requirement
    FOREIGN KEY (organization_id, reservation_id, commitment_requirement_id)
    REFERENCES commitment_requirements
        (organization_id, reservation_id, commitment_requirement_id)
    ON DELETE RESTRICT;

-- One ResourceAllocation represents one authority consumption; therefore it has
-- exactly one allocation CapacityClaim while active.
CREATE UNIQUE INDEX uq_capacity_claims_allocation
    ON capacity_claims (organization_id, resource_allocation_id)
    WHERE resource_allocation_id IS NOT NULL;

-- ============================================================================
-- 2. Fulfillment scope validation and reject_excess serialization
-- ============================================================================

DROP TRIGGER trg_fulfillments_budget ON fulfillments;
DROP FUNCTION request_engine.enforce_fulfillment_budget();

CREATE OR REPLACE FUNCTION request_engine.validate_fulfillment()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_scope outcome_scopes%ROWTYPE;
    v_current numeric(38,9);
BEGIN
    SELECT *
      INTO v_scope
      FROM outcome_scopes
     WHERE organization_id = NEW.organization_id
       AND outcome_scope_id = NEW.outcome_scope_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'OutcomeScope not found' USING ERRCODE = '23503';
    END IF;

    IF NEW.request_id <> v_scope.request_id
       OR NEW.offering_selection_id <> v_scope.offering_selection_id
       OR NEW.recipient_party_id IS DISTINCT FROM v_scope.recipient_party_id
       OR NEW.model <> v_scope.fulfillment_model
       OR NEW.model_version <> v_scope.fulfillment_model_version THEN
        RAISE EXCEPTION 'Fulfillment does not match authoritative OutcomeScope'
            USING ERRCODE = '23514';
    END IF;

    IF v_scope.fulfillment_model = 'quantity' THEN
        IF NEW.unit_code IS DISTINCT FROM v_scope.unit_code THEN
            RAISE EXCEPTION 'Fulfillment unit does not match OutcomeScope'
                USING ERRCODE = '23514';
        END IF;

        IF v_scope.excess_policy = 'reject_excess' THEN
            SELECT COALESCE(sum(f.quantity), 0)
              INTO v_current
              FROM fulfillments f
             WHERE f.organization_id = NEW.organization_id
               AND f.outcome_scope_id = NEW.outcome_scope_id
               AND NOT EXISTS (
                    SELECT 1
                      FROM fulfillment_corrections fc
                     WHERE fc.organization_id = f.organization_id
                       AND fc.fulfillment_id = f.fulfillment_id
                       AND fc.correction_kind IN ('invalidate','supersede')
               );

            IF v_current + NEW.quantity > v_scope.requested_quantity THEN
                RAISE EXCEPTION 'Fulfillment exceeds reject_excess OutcomeScope budget'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_fulfillments_validate
BEFORE INSERT ON fulfillments
FOR EACH ROW EXECUTE FUNCTION request_engine.validate_fulfillment();

-- ============================================================================
-- 3. Capacity: one authority, one lock protocol, correct interval arithmetic
-- ============================================================================

DROP TRIGGER trg_capacity_claims_enforce ON capacity_claims;
DROP FUNCTION request_engine.enforce_capacity_claim();

CREATE OR REPLACE FUNCTION request_engine.validate_capacity_claim()
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
       OR NEW.authority_schedule_revision <> v_authority.schedule_revision THEN
        RAISE EXCEPTION 'stale capacity authority revision'
            USING ERRCODE = '40001';
    END IF;

    IF NEW.planning_revision IS NOT NULL
       AND NEW.planning_revision <> v_authority.planning_revision THEN
        RAISE EXCEPTION 'stale planning revision'
            USING ERRCODE = '40001';
    END IF;

    IF NEW.claim_kind = 'hold' THEN
        SELECT *
          INTO v_hold
          FROM capacity_holds
         WHERE organization_id = NEW.organization_id
           AND capacity_hold_id = NEW.capacity_hold_id
         FOR UPDATE;

        IF NOT FOUND OR v_hold.state <> 'active' OR v_hold.expires_at <= v_now THEN
            RAISE EXCEPTION 'CapacityHold is not logically live'
                USING ERRCODE = '23514';
        END IF;

        -- Snapshot is derived, never caller-authoritative.
        NEW.hold_expires_at := v_hold.expires_at;
    ELSE
        SELECT *
          INTO v_allocation
          FROM resource_allocations
         WHERE organization_id = NEW.organization_id
           AND resource_allocation_id = NEW.resource_allocation_id
         FOR UPDATE;

        IF NOT FOUND
           OR v_allocation.state <> 'active'
           OR v_allocation.capacity_authority_id <> NEW.capacity_authority_id
           OR v_allocation.quantity <> NEW.quantity
           OR v_allocation.conflict_range <> NEW.conflict_range THEN
            RAISE EXCEPTION 'CapacityClaim does not match active ResourceAllocation'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.state <> 'active' THEN
        RETURN NEW;
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
    ELSE
        -- Evaluate every temporal segment, not the incorrect sum of every claim
        -- that overlaps anywhere with NEW.conflict_range.
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
            UNION SELECT upper(NEW.conflict_range)
            UNION SELECT greatest(lower(conflict_range), lower(NEW.conflict_range)) FROM live
            UNION SELECT least(upper(conflict_range), upper(NEW.conflict_range)) FROM live
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
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_capacity_claims_validate
BEFORE INSERT OR UPDATE OF capacity_authority_id, state, conflict_range, quantity,
    capacity_hold_id, resource_allocation_id, authority_configuration_revision,
    authority_schedule_revision, planning_revision
ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.validate_capacity_claim();

-- Active Allocation <-> active allocation Claim is checked at transaction end so
-- confirmation can create rows in either physical order inside one transaction.
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
    v_allocation_id := COALESCE(NEW.resource_allocation_id, OLD.resource_allocation_id);
    v_org_id := COALESCE(NEW.organization_id, OLD.organization_id);

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

CREATE CONSTRAINT TRIGGER ctrg_resource_allocations_claim
AFTER INSERT OR UPDATE OF state ON resource_allocations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.check_allocation_claim_cardinality();

CREATE CONSTRAINT TRIGGER ctrg_capacity_claims_allocation
AFTER INSERT OR UPDATE OF state, resource_allocation_id ON capacity_claims
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.check_allocation_claim_cardinality();

-- ============================================================================
-- 4. Capacity revisions are infrastructure invariants, not caller conventions
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.bump_capacity_schedule_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org bigint := COALESCE(NEW.organization_id, OLD.organization_id);
    v_authority bigint := COALESCE(NEW.capacity_authority_id, OLD.capacity_authority_id);
BEGIN
    UPDATE capacity_authorities
       SET schedule_revision = schedule_revision + 1
     WHERE organization_id = v_org
       AND capacity_authority_id = v_authority;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_availability_schedules_revision
AFTER INSERT OR UPDATE OR DELETE ON availability_schedules
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_capacity_schedule_revision();

CREATE TRIGGER trg_schedule_exceptions_revision
AFTER INSERT OR UPDATE OR DELETE ON schedule_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_capacity_schedule_revision();

CREATE OR REPLACE FUNCTION request_engine.bump_resource_configuration_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org bigint := COALESCE(NEW.organization_id, OLD.organization_id);
    v_resource bigint := COALESCE(NEW.resource_id, OLD.resource_id);
BEGIN
    UPDATE capacity_authorities
       SET configuration_revision = configuration_revision + 1
     WHERE organization_id = v_org
       AND resource_id = v_resource;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_resource_capacity_revision
AFTER UPDATE OF status, operating_location ON resources
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status
   OR OLD.operating_location IS DISTINCT FROM NEW.operating_location)
EXECUTE FUNCTION request_engine.bump_resource_configuration_revision();

CREATE TRIGGER trg_resource_capability_assignment_revision
AFTER INSERT OR UPDATE OR DELETE ON resource_capability_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_configuration_revision();

CREATE OR REPLACE FUNCTION request_engine.bump_pool_configuration_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org bigint := COALESCE(NEW.organization_id, OLD.organization_id);
    v_pool bigint := COALESCE(NEW.capacity_pool_id, OLD.capacity_pool_id);
BEGIN
    UPDATE capacity_authorities
       SET configuration_revision = configuration_revision + 1
     WHERE organization_id = v_org
       AND capacity_pool_id = v_pool;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_capacity_pool_membership_revision
AFTER INSERT OR UPDATE OR DELETE ON capacity_pool_memberships
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_pool_configuration_revision();

-- Every commitment mutation can invalidate external field-service feasibility.
CREATE OR REPLACE FUNCTION request_engine.bump_claim_planning_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT'
       OR OLD.state IS DISTINCT FROM NEW.state
       OR OLD.conflict_range IS DISTINCT FROM NEW.conflict_range
       OR OLD.quantity IS DISTINCT FROM NEW.quantity THEN
        UPDATE capacity_authorities
           SET planning_revision = planning_revision + 1
         WHERE organization_id = NEW.organization_id
           AND capacity_authority_id = NEW.capacity_authority_id;
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_capacity_claims_planning_revision
AFTER INSERT OR UPDATE OF state, conflict_range, quantity ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_claim_planning_revision();

-- ============================================================================
-- 5. Lifecycle monotonicity: committed history never resurrects
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_terminal_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'reservations' THEN
        IF OLD.status IN ('cancelled','closed') AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'terminal Reservation cannot transition' USING ERRCODE = '55000';
        END IF;
    ELSE
        IF OLD.state IN ('released','replaced') AND NEW.state IS DISTINCT FROM OLD.state THEN
            RAISE EXCEPTION '% terminal state cannot transition', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reservations_terminal_transition
BEFORE UPDATE OF status ON reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_terminal_transition();

CREATE TRIGGER trg_resource_allocations_terminal_transition
BEFORE UPDATE OF state ON resource_allocations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_terminal_transition();

CREATE TRIGGER trg_capacity_claims_terminal_transition
BEFORE UPDATE OF state ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_terminal_transition();

-- Hold cannot transition while its consuming hold claims remain active. Commands
-- release/replace claims first, then transition the Hold in the same transaction.
CREATE OR REPLACE FUNCTION request_engine.guard_capacity_hold_claims()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state = 'active' AND NEW.state <> 'active' THEN
        IF EXISTS (
            SELECT 1
              FROM capacity_claims c
             WHERE c.organization_id = NEW.organization_id
               AND c.capacity_hold_id = NEW.capacity_hold_id
               AND c.claim_kind = 'hold'
               AND c.state = 'active'
        ) THEN
            RAISE EXCEPTION 'CapacityHold cannot transition with active hold claims'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_capacity_holds_claims
BEFORE UPDATE OF state ON capacity_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_hold_claims();

-- Strengthen terminal Reservation proof: no active Allocation and no active
-- allocation Claim may survive.
DROP TRIGGER trg_reservations_guard_terminal_claims ON reservations;
DROP FUNCTION request_engine.guard_reservation_terminal_claims();

CREATE OR REPLACE FUNCTION request_engine.guard_reservation_terminal_capacity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status = 'confirmed' AND NEW.status IN ('cancelled','closed') THEN
        IF EXISTS (
            SELECT 1
              FROM resource_allocations ra
             WHERE ra.organization_id = NEW.organization_id
               AND ra.reservation_id = NEW.reservation_id
               AND ra.state = 'active'
        ) OR EXISTS (
            SELECT 1
              FROM capacity_claims cc
              JOIN resource_allocations ra
                ON ra.organization_id = cc.organization_id
               AND ra.resource_allocation_id = cc.resource_allocation_id
             WHERE ra.organization_id = NEW.organization_id
               AND ra.reservation_id = NEW.reservation_id
               AND cc.state = 'active'
        ) THEN
            RAISE EXCEPTION 'terminal Reservation cannot retain active capacity'
                USING ERRCODE = '55000';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reservations_guard_terminal_capacity
BEFORE UPDATE OF status ON reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_terminal_capacity();

-- ============================================================================
-- 6. Immutable ingress and idempotency identity
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_provider_event_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.organization_id <> OLD.organization_id
       OR NEW.provider_connection_id <> OLD.provider_connection_id
       OR NEW.provider_event_id <> OLD.provider_event_id
       OR NEW.canonical_payload_hash <> OLD.canonical_payload_hash
       OR NEW.payload <> OLD.payload
       OR NEW.authentication_result <> OLD.authentication_result
       OR NEW.received_at <> OLD.received_at THEN
        RAISE EXCEPTION 'ProviderEvent envelope is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_provider_events_identity
BEFORE UPDATE ON provider_events
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_provider_event_identity();

CREATE OR REPLACE FUNCTION request_engine.guard_idempotency_identity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.organization_id <> OLD.organization_id
       OR NEW.scope <> OLD.scope
       OR NEW.idempotency_key <> OLD.idempotency_key
       OR NEW.canonical_request_hash <> OLD.canonical_request_hash
       OR NEW.created_by_principal_id IS DISTINCT FROM OLD.created_by_principal_id
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'Idempotency identity is immutable' USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_idempotency_records_identity
BEFORE UPDATE ON idempotency_records
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_idempotency_identity();

-- ============================================================================
-- 7. Financial reductions cannot become silently overallocated
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_eligible_value_reduction()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_net_allocated bigint;
BEGIN
    IF NEW.current_eligible_amount_minor >= OLD.current_eligible_amount_minor THEN
        RETURN NEW;
    END IF;

    SELECT COALESCE(sum(pa.allocated_amount_minor), 0)
           - COALESCE(sum(adj.amount_minor), 0)
      INTO v_net_allocated
      FROM payment_allocations pa
      LEFT JOIN payment_allocation_adjustments adj
        ON adj.organization_id = pa.organization_id
       AND adj.payment_allocation_id = pa.payment_allocation_id
     WHERE pa.organization_id = OLD.organization_id
       AND pa.payment_transaction_id = OLD.payment_transaction_id;

    IF v_net_allocated > NEW.current_eligible_amount_minor
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

CREATE TRIGGER trg_payment_transactions_eligible_reduction
BEFORE UPDATE OF current_eligible_amount_minor ON payment_transactions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_eligible_value_reduction();

-- Refund writes serialize on PaymentTransaction. The authoritative refundable
-- amount remains policy-derived; this DB backstop only prevents concurrent
-- cumulative refund claims from exceeding nominal transaction value.
CREATE OR REPLACE FUNCTION request_engine.guard_refund_budget()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_tx payment_transactions%ROWTYPE;
    v_reserved bigint;
BEGIN
    SELECT *
      INTO v_tx
      FROM payment_transactions
     WHERE organization_id = NEW.organization_id
       AND payment_transaction_id = NEW.payment_transaction_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'PaymentTransaction not found' USING ERRCODE = '23503';
    END IF;

    IF NEW.currency <> v_tx.currency THEN
        RAISE EXCEPTION 'Refund currency mismatch; implicit FX is forbidden'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status IN ('requested','processing','succeeded') THEN
        SELECT COALESCE(sum(r.amount_minor), 0)
          INTO v_reserved
          FROM refunds r
         WHERE r.organization_id = NEW.organization_id
           AND r.payment_transaction_id = NEW.payment_transaction_id
           AND r.refund_id <> COALESCE(NEW.refund_id, -1)
           AND r.status IN ('requested','processing','succeeded');

        IF v_reserved + NEW.amount_minor > v_tx.nominal_amount_minor THEN
            RAISE EXCEPTION 'refund claims exceed nominal transaction value'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_refunds_budget
BEFORE INSERT OR UPDATE OF status, amount_minor ON refunds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_refund_budget();

-- ============================================================================
-- 8. Typed RequestTarget compatibility
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.validate_reservation_request_target()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_type text;
BEGIN
    SELECT request_type
      INTO v_type
      FROM requests
     WHERE organization_id = NEW.organization_id
       AND request_id = NEW.request_id
     FOR KEY SHARE;

    IF v_type NOT IN ('cancel_reservation','reschedule_reservation') THEN
        RAISE EXCEPTION 'Reservation target is invalid for RequestType %', v_type
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_request_target_reservations_validate
BEFORE INSERT OR UPDATE OF request_id, reservation_id ON request_target_reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.validate_reservation_request_target();

-- ============================================================================
-- 9. Supporting indexes for the lock/validation paths above
-- ============================================================================

CREATE INDEX IF NOT EXISTS ix_capacity_claims_authority_active
    ON capacity_claims (organization_id, capacity_authority_id, state, capacity_claim_id);

CREATE INDEX IF NOT EXISTS ix_capacity_claims_hold_active
    ON capacity_claims (organization_id, capacity_hold_id, state)
    WHERE claim_kind = 'hold';

CREATE INDEX IF NOT EXISTS ix_refunds_transaction_live
    ON refunds (organization_id, payment_transaction_id, status, refund_id)
    WHERE status IN ('requested','processing','succeeded');

CREATE INDEX IF NOT EXISTS ix_reconciliation_cases_transaction_live
    ON reconciliation_cases (organization_id, payment_transaction_id, status)
    WHERE status IN ('open','under_review');

-- ============================================================================
-- DBA notes / explicit non-goals
-- ============================================================================
--
-- 1. Variable schedule capacity still requires the command protocol to derive
--    effective capacity at every schedule/exception change point while holding
--    CapacityAuthority. validate_capacity_claim() fixes interval arithmetic at
--    base capacity; it intentionally does not parse schedule_definition JSON.
--
-- 2. CapacityPool direct-member conflicts still require the canonical
--    multi-authority lock set from docs/02. This migration does not hide that
--    cross-authority proof inside recursive triggers.
--
-- 3. Refund policy may be stricter than nominal value after reversals, fees or
--    provider semantics. guard_refund_budget() is a concurrency backstop, not a
--    replacement for the versioned financial policy.
--
-- 4. RLS remains deployment-specific defense-in-depth. Tenant integrity is
--    structural here; authorization remains application/domain authority.
--
-- 5. All multi-root commands must preserve the canonical lock class order in
--    docs/02. PostgreSQL deadlock detection is fallback, never the lock plan.

COMMIT;
