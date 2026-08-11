-- Request Engine V2.7 — PostgreSQL hardening
-- Target: PostgreSQL 18+
-- Applies after: docs/03-postgresql-schema.sql
-- Normative source: docs/02-pre-sql-domain-contract.md
--
-- Design rule:
--   constraints          -> structural truth
--   small triggers       -> local monotonicity / immutable identity / backstops
--   deferred constraints -> transaction-end cardinality
--   command transaction  -> multi-root and policy-dependent invariants
--
-- This file is the complete V2.7 delta over the V2.6 reference schema.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = request_engine, public;

-- ============================================================================
-- 1. Structural lineage: prove relationships with composite foreign keys
-- ============================================================================

ALTER TABLE outcome_scopes
    ADD CONSTRAINT uq_outcome_scopes_fulfillment_key
    UNIQUE (organization_id, request_id, outcome_scope_id, offering_selection_id);

ALTER TABLE fulfillments
    ADD CONSTRAINT fk_fulfillments_scope_selection
    FOREIGN KEY (organization_id, request_id, outcome_scope_id, offering_selection_id)
    REFERENCES outcome_scopes
        (organization_id, request_id, outcome_scope_id, offering_selection_id)
    ON DELETE RESTRICT;

ALTER TABLE fulfillments
    ADD CONSTRAINT uq_fulfillments_correction_key
    UNIQUE (organization_id, fulfillment_id, outcome_scope_id);

ALTER TABLE fulfillment_corrections
    DROP CONSTRAINT fk_fulfillment_corrections_fulfillment,
    ADD CONSTRAINT fk_fulfillment_corrections_fulfillment_scope
    FOREIGN KEY (organization_id, fulfillment_id, outcome_scope_id)
    REFERENCES fulfillments (organization_id, fulfillment_id, outcome_scope_id)
    ON DELETE RESTRICT;

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

CREATE UNIQUE INDEX uq_capacity_claims_allocation
    ON capacity_claims (organization_id, resource_allocation_id)
    WHERE resource_allocation_id IS NOT NULL;

-- ============================================================================
-- 2. OutcomeScope is the serialization root for reject_excess fulfillment
-- ============================================================================

DROP TRIGGER IF EXISTS trg_fulfillments_budget ON fulfillments;
DROP FUNCTION IF EXISTS request_engine.enforce_fulfillment_budget();

CREATE OR REPLACE FUNCTION request_engine.guard_fulfillment()
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

    IF v_scope.fulfillment_model <> 'quantity' THEN
        RETURN NEW;
    END IF;

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

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_fulfillments_guard
BEFORE INSERT ON fulfillments
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_fulfillment();

-- ============================================================================
-- 3. CapacityClaim: serialize increases; never block release on stale revisions
-- ============================================================================

DROP TRIGGER IF EXISTS trg_capacity_claims_enforce ON capacity_claims;
DROP FUNCTION IF EXISTS request_engine.enforce_capacity_claim();

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
    -- Historical/terminal writes reduce consumption and must remain possible even
    -- when the claim's captured revisions are stale.
    IF TG_OP = 'UPDATE' AND NEW.state <> 'active' THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'INSERT' AND NEW.state <> 'active' THEN
        RAISE EXCEPTION 'CapacityClaim must be created active'
            USING ERRCODE = '23514';
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

        -- Derived snapshot only. Caller cannot choose a different expiry.
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

    -- Unit-capacity DB backstop. Variable schedule capacity remains command-owned:
    -- docs/02 requires evaluation at every schedule/exception change point.
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
    )
    SELECT COALESCE(max(load), NEW.quantity)
      INTO v_peak
      FROM (
        SELECT s.segment_start,
               COALESCE(sum(l.quantity) FILTER (
                   WHERE l.conflict_range @> s.segment_start
               ), 0) + NEW.quantity AS load
          FROM segments s
          LEFT JOIN live l ON l.conflict_range @> s.segment_start
         WHERE s.segment_end IS NOT NULL
           AND s.segment_start < s.segment_end
         GROUP BY s.segment_start
      ) q;

    IF v_peak > v_authority.base_capacity_units THEN
        RAISE EXCEPTION 'unit capacity exceeded on authority %',
            NEW.capacity_authority_id USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_capacity_claims_guard
BEFORE INSERT OR UPDATE OF state, conflict_range, quantity,
    capacity_authority_id, capacity_hold_id, resource_allocation_id,
    authority_configuration_revision, authority_schedule_revision, planning_revision
ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim();

-- ============================================================================
-- 4. Allocation <-> claim cardinality is checked at transaction end
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.check_allocation_claim_cardinality()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_org_id bigint;
    v_allocation_id bigint;
    v_allocation_state text;
    v_active_claims integer;
BEGIN
    IF TG_TABLE_NAME = 'resource_allocations' THEN
        v_org_id := NEW.organization_id;
        v_allocation_id := NEW.resource_allocation_id;
    ELSE
        v_org_id := NEW.organization_id;
        v_allocation_id := NEW.resource_allocation_id;
    END IF;

    IF v_allocation_id IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT state
      INTO v_allocation_state
      FROM resource_allocations
     WHERE organization_id = v_org_id
       AND resource_allocation_id = v_allocation_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT count(*)
      INTO v_active_claims
      FROM capacity_claims
     WHERE organization_id = v_org_id
       AND resource_allocation_id = v_allocation_id
       AND claim_kind = 'allocation'
       AND state = 'active';

    IF (v_allocation_state = 'active' AND v_active_claims <> 1)
       OR (v_allocation_state <> 'active' AND v_active_claims <> 0) THEN
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
-- 5. Revisions: configuration/schedule are local; PlanningRevision is command-owned
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.bump_schedule_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_old_org bigint;
    v_old_authority bigint;
    v_new_org bigint;
    v_new_authority bigint;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        v_old_org := OLD.organization_id;
        v_old_authority := OLD.capacity_authority_id;
        UPDATE capacity_authorities
           SET schedule_revision = schedule_revision + 1
         WHERE organization_id = v_old_org
           AND capacity_authority_id = v_old_authority;
    END IF;

    IF TG_OP <> 'DELETE'
       AND (TG_OP = 'INSERT'
            OR (NEW.organization_id, NEW.capacity_authority_id)
               IS DISTINCT FROM (OLD.organization_id, OLD.capacity_authority_id)) THEN
        v_new_org := NEW.organization_id;
        v_new_authority := NEW.capacity_authority_id;
        UPDATE capacity_authorities
           SET schedule_revision = schedule_revision + 1
         WHERE organization_id = v_new_org
           AND capacity_authority_id = v_new_authority;
    END IF;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_availability_schedules_revision
AFTER INSERT OR UPDATE OR DELETE ON availability_schedules
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_schedule_revision();

CREATE TRIGGER trg_schedule_exceptions_revision
AFTER INSERT OR UPDATE OR DELETE ON schedule_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_schedule_revision();

CREATE OR REPLACE FUNCTION request_engine.bump_resource_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        UPDATE capacity_authorities
           SET configuration_revision = configuration_revision + 1
         WHERE organization_id = OLD.organization_id
           AND resource_id = OLD.resource_id;
    END IF;

    IF TG_OP <> 'DELETE'
       AND (TG_OP = 'INSERT'
            OR (NEW.organization_id, NEW.resource_id)
               IS DISTINCT FROM (OLD.organization_id, OLD.resource_id)) THEN
        UPDATE capacity_authorities
           SET configuration_revision = configuration_revision + 1
         WHERE organization_id = NEW.organization_id
           AND resource_id = NEW.resource_id;
    END IF;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_resource_capacity_revision
AFTER UPDATE OF status, operating_location ON resources
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status
   OR OLD.operating_location IS DISTINCT FROM NEW.operating_location)
EXECUTE FUNCTION request_engine.bump_resource_revision();

CREATE TRIGGER trg_resource_capability_assignment_revision
AFTER INSERT OR UPDATE OR DELETE ON resource_capability_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_revision();

CREATE OR REPLACE FUNCTION request_engine.bump_pool_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        UPDATE capacity_authorities
           SET configuration_revision = configuration_revision + 1
         WHERE organization_id = OLD.organization_id
           AND capacity_pool_id = OLD.capacity_pool_id;
    END IF;

    IF TG_OP <> 'DELETE'
       AND (TG_OP = 'INSERT'
            OR (NEW.organization_id, NEW.capacity_pool_id)
               IS DISTINCT FROM (OLD.organization_id, OLD.capacity_pool_id)) THEN
        UPDATE capacity_authorities
           SET configuration_revision = configuration_revision + 1
         WHERE organization_id = NEW.organization_id
           AND capacity_pool_id = NEW.capacity_pool_id;
    END IF;

    RETURN NULL;
END;
$$;

CREATE TRIGGER trg_capacity_pool_membership_revision
AFTER INSERT OR UPDATE OR DELETE ON capacity_pool_memberships
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_pool_revision();

CREATE TRIGGER trg_capacity_pool_status_revision
AFTER UPDATE OF status ON capacity_pools
FOR EACH ROW
WHEN (OLD.status IS DISTINCT FROM NEW.status)
EXECUTE FUNCTION request_engine.bump_pool_revision();

COMMENT ON COLUMN capacity_authorities.planning_revision IS
'Increment once per semantic planning-sensitive command, never once per physical CapacityClaim row.';

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

-- ============================================================================
-- 6. Historical commitments are monotonic and non-destructive
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

CREATE TRIGGER trg_capacity_claims_no_delete
BEFORE DELETE ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_delete();

CREATE TRIGGER trg_resource_allocations_no_delete
BEFORE DELETE ON resource_allocations
FOR EACH ROW EXECUTE FUNCTION request_engine.prevent_delete();

CREATE OR REPLACE FUNCTION request_engine.guard_commitment_history()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'reservations' THEN
        IF OLD.status IN ('cancelled','closed') AND NEW.status IS DISTINCT FROM OLD.status THEN
            RAISE EXCEPTION 'terminal Reservation cannot transition' USING ERRCODE = '55000';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.state IN ('released','replaced') AND NEW.state IS DISTINCT FROM OLD.state THEN
        RAISE EXCEPTION '% terminal state cannot transition', TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;

    IF TG_TABLE_NAME = 'capacity_claims'
       AND (
            NEW.organization_id <> OLD.organization_id
            OR NEW.capacity_authority_id <> OLD.capacity_authority_id
            OR NEW.claim_kind <> OLD.claim_kind
            OR NEW.capacity_hold_id IS DISTINCT FROM OLD.capacity_hold_id
            OR NEW.resource_allocation_id IS DISTINCT FROM OLD.resource_allocation_id
            OR NEW.conflict_range IS DISTINCT FROM OLD.conflict_range
            OR NEW.quantity IS DISTINCT FROM OLD.quantity
       ) THEN
        RAISE EXCEPTION 'CapacityClaim consumption identity is immutable; replace it instead'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reservations_terminal
BEFORE UPDATE OF status ON reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_commitment_history();

CREATE TRIGGER trg_resource_allocations_terminal
BEFORE UPDATE OF state ON resource_allocations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_commitment_history();

CREATE TRIGGER trg_capacity_claims_history
BEFORE UPDATE ON capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_commitment_history();

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_hold_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state = 'active' AND NEW.state <> 'active' AND EXISTS (
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

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_capacity_holds_transition
BEFORE UPDATE OF state ON capacity_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_hold_transition();

DROP TRIGGER IF EXISTS trg_reservations_guard_terminal_claims ON reservations;
DROP FUNCTION IF EXISTS request_engine.guard_reservation_terminal_claims();

CREATE OR REPLACE FUNCTION request_engine.guard_reservation_terminal_capacity()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.status = 'confirmed' AND NEW.status IN ('cancelled','closed') AND EXISTS (
        SELECT 1
          FROM resource_allocations ra
         WHERE ra.organization_id = NEW.organization_id
           AND ra.reservation_id = NEW.reservation_id
           AND ra.state = 'active'
    ) THEN
        RAISE EXCEPTION 'terminal Reservation cannot retain active allocations'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_reservations_terminal_capacity
BEFORE UPDATE OF status ON reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_terminal_capacity();

-- ============================================================================
-- 7. External ingress and durable idempotency identity are immutable
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
-- 8. Financial backstops: never hide over-allocation or concurrent refund claims
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

CREATE TRIGGER trg_payment_transactions_eligible_reduction
BEFORE UPDATE OF current_eligible_amount_minor ON payment_transactions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_eligible_value_reduction();

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
-- 9. Typed RequestTarget compatibility
-- ============================================================================

CREATE OR REPLACE FUNCTION request_engine.guard_reservation_request_target()
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

CREATE TRIGGER trg_request_target_reservations_guard
BEFORE INSERT OR UPDATE OF request_id, reservation_id ON request_target_reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_request_target();

-- ============================================================================
-- 10. Index only the hot validation paths not already guaranteed by constraints
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
-- 11. Explicit boundary: what PostgreSQL does NOT pretend to prove here
-- ============================================================================
--
-- Command transaction remains authoritative for:
--   * compound multi-authority acquisition and canonical lock ordering;
--   * variable schedule capacity at every change point;
--   * pool/direct-member conflict and late binding;
--   * shared-requirement amendments and replacement-before-release reschedule;
--   * completion/correction races across OutcomeScope + Request;
--   * PlanningRevision advancement over the correct bounded authority set;
--   * external commitment truth/compensation;
--   * policy-specific refundable value and ambiguous financial attribution.
--
-- A pre-check outside the documented transaction is never authority.

COMMIT;
