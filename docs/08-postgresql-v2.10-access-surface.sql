-- Request Engine V2.10 — PostgreSQL access surface
-- Target: PostgreSQL 18+
-- Applies after:
--   docs/03-postgresql-schema.sql
--   docs/04-postgresql-v2.7-hardening.sql
--   docs/05-postgresql-v2.8-hardening.sql
--   docs/06-postgresql-v2.9-integrity.sql
-- Normative access contract: docs/07-database-access-contract.md
--
-- Purpose:
--   * stable versioned read views for Python Query Services;
--   * narrow data-centric command primitives for SQLAlchemy repositories/workers;
--   * explicit privilege boundary preparation;
--   * no stored-procedure application backend and no writable business views.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog, request_engine, request_read, request_cmd, request_admin;

-- ============================================================================
-- 1. Interface schemas
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS request_read;
CREATE SCHEMA IF NOT EXISTS request_cmd;
CREATE SCHEMA IF NOT EXISTS request_admin;

COMMENT ON SCHEMA request_read IS
'Versioned read-only contracts for Python Query Services. Views are projections and never mutation authority.';

COMMENT ON SCHEMA request_cmd IS
'Narrow PostgreSQL consistency primitives called inside Python-owned transactions. Not a domain workflow layer.';

COMMENT ON SCHEMA request_admin IS
'DBA/support/reconciliation diagnostic surface. Never product mutation authority.';

REVOKE ALL ON SCHEMA request_read FROM PUBLIC;
REVOKE ALL ON SCHEMA request_cmd FROM PUBLIC;
REVOKE ALL ON SCHEMA request_admin FROM PUBLIC;

-- PostgreSQL grants EXECUTE on functions to PUBLIC by default. Make the command
-- schema deny-by-default both now and for future routines created by this owner.
ALTER DEFAULT PRIVILEGES IN SCHEMA request_cmd
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

ALTER DEFAULT PRIVILEGES IN SCHEMA request_read
    REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES IN SCHEMA request_admin
    REVOKE ALL ON TABLES FROM PUBLIC;

-- ============================================================================
-- 2. Read contract: stable, versioned, non-authoritative projections
-- ============================================================================

CREATE VIEW request_read.request_summary_v1
WITH (security_invoker = true) AS
SELECT
    r.organization_id,
    r.request_id,
    r.public_id AS request_public_id,
    r.request_type,
    r.status,
    r.completion_validity,
    r.revision,
    r.workflow_key,
    r.workflow_version,
    r.completion_policy_key,
    r.completion_policy_version,
    r.completed_at,
    r.terminal_at,
    r.created_at,
    r.updated_at,
    r.status IN ('completed', 'cancelled', 'failed_terminal') AS is_terminal
FROM request_engine.requests AS r;

COMMENT ON VIEW request_read.request_summary_v1 IS
'Current Request read model. is_terminal is a projection; commands still lock/revalidate request_engine.requests.';

CREATE VIEW request_read.reservation_summary_v1
WITH (security_invoker = true) AS
SELECT
    r.organization_id,
    r.reservation_id,
    r.public_id AS reservation_public_id,
    req.public_id AS originating_request_public_id,
    replacement.public_id AS replaces_reservation_public_id,
    r.status,
    lower(r.planned_service_range) AS planned_start_at,
    upper(r.planned_service_range) AS planned_end_at,
    r.revision,
    r.confirmed_at,
    r.cancelled_at,
    r.closed_at,
    r.created_at,
    r.updated_at
FROM request_engine.reservations AS r
JOIN request_engine.requests AS req
  ON req.organization_id = r.organization_id
 AND req.request_id = r.originating_request_id
LEFT JOIN request_engine.reservations AS replacement
  ON replacement.organization_id = r.organization_id
 AND replacement.reservation_id = r.replaces_reservation_id;

COMMENT ON VIEW request_read.reservation_summary_v1 IS
'Current Reservation read model. planned timestamps are derived from the canonical [start,end) range.';

CREATE VIEW request_read.payment_requirement_status_v1
WITH (security_invoker = true) AS
WITH allocation_totals AS (
    SELECT
        pa.organization_id,
        pa.payment_requirement_id,
        sum(pa.allocated_amount_minor) AS allocated_amount_minor
    FROM request_engine.payment_allocations AS pa
    GROUP BY pa.organization_id, pa.payment_requirement_id
), adjustment_totals AS (
    SELECT
        pa.organization_id,
        pa.payment_requirement_id,
        sum(paa.amount_minor) AS adjusted_amount_minor
    FROM request_engine.payment_allocation_adjustments AS paa
    JOIN request_engine.payment_allocations AS pa
      ON pa.organization_id = paa.organization_id
     AND pa.payment_allocation_id = paa.payment_allocation_id
    GROUP BY pa.organization_id, pa.payment_requirement_id
)
SELECT
    pr.organization_id,
    pr.payment_requirement_id,
    pr.public_id AS payment_requirement_public_id,
    req.public_id AS request_public_id,
    pr.payer_party_id,
    pr.purpose,
    pr.currency,
    pr.required_amount_minor,
    pr.disposition,
    pr.due_at,
    GREATEST(
        COALESCE(a.allocated_amount_minor, 0) - COALESCE(adj.adjusted_amount_minor, 0),
        0
    ) AS net_allocated_amount_minor,
    GREATEST(
        pr.required_amount_minor
        - GREATEST(
            COALESCE(a.allocated_amount_minor, 0) - COALESCE(adj.adjusted_amount_minor, 0),
            0
          ),
        0
    ) AS remaining_amount_minor,
    CASE
        WHEN pr.disposition = 'waived' THEN 'waived'
        WHEN pr.disposition = 'cancelled' THEN 'cancelled'
        WHEN GREATEST(
                 COALESCE(a.allocated_amount_minor, 0) - COALESCE(adj.adjusted_amount_minor, 0),
                 0
             ) >= pr.required_amount_minor THEN 'satisfied'
        WHEN GREATEST(
                 COALESCE(a.allocated_amount_minor, 0) - COALESCE(adj.adjusted_amount_minor, 0),
                 0
             ) > 0 THEN 'partial'
        WHEN pr.due_at IS NOT NULL AND pr.due_at < clock_timestamp() THEN 'overdue'
        ELSE 'open'
    END AS current_status,
    pr.created_at
FROM request_engine.payment_requirements AS pr
JOIN request_engine.requests AS req
  ON req.organization_id = pr.organization_id
 AND req.request_id = pr.request_id
LEFT JOIN allocation_totals AS a
  ON a.organization_id = pr.organization_id
 AND a.payment_requirement_id = pr.payment_requirement_id
LEFT JOIN adjustment_totals AS adj
  ON adj.organization_id = pr.organization_id
 AND adj.payment_requirement_id = pr.payment_requirement_id;

COMMENT ON VIEW request_read.payment_requirement_status_v1 IS
'Derived PaymentRequirement status. Never authorizes allocation; AllocatePayment revalidates locked authoritative rows.';

CREATE VIEW request_read.payment_transaction_status_v1
WITH (security_invoker = true) AS
WITH allocation_totals AS (
    SELECT
        pa.organization_id,
        pa.payment_transaction_id,
        sum(pa.allocated_amount_minor) AS allocated_amount_minor
    FROM request_engine.payment_allocations AS pa
    GROUP BY pa.organization_id, pa.payment_transaction_id
), adjustment_totals AS (
    SELECT
        paa.organization_id,
        paa.payment_transaction_id,
        sum(paa.amount_minor) AS adjusted_amount_minor
    FROM request_engine.payment_allocation_adjustments AS paa
    GROUP BY paa.organization_id, paa.payment_transaction_id
), refund_totals AS (
    SELECT
        r.organization_id,
        r.payment_transaction_id,
        sum(r.amount_minor) FILTER (
            WHERE r.status IN ('requested', 'processing', 'succeeded')
        ) AS reserved_refund_amount_minor,
        sum(r.amount_minor) FILTER (
            WHERE r.status = 'succeeded'
        ) AS succeeded_refund_amount_minor
    FROM request_engine.refunds AS r
    GROUP BY r.organization_id, r.payment_transaction_id
), reconciliation_totals AS (
    SELECT
        rc.organization_id,
        rc.payment_transaction_id,
        count(*) AS open_case_count
    FROM request_engine.reconciliation_cases AS rc
    WHERE rc.status IN ('open', 'under_review')
      AND rc.payment_transaction_id IS NOT NULL
    GROUP BY rc.organization_id, rc.payment_transaction_id
)
SELECT
    pt.organization_id,
    pt.payment_transaction_id,
    pt.public_id AS payment_transaction_public_id,
    pt.transaction_kind,
    pt.currency,
    pt.nominal_amount_minor,
    pt.current_finality,
    pt.current_eligible_amount_minor,
    GREATEST(
        COALESCE(a.allocated_amount_minor, 0) - COALESCE(adj.adjusted_amount_minor, 0),
        0
    ) AS net_allocated_amount_minor,
    GREATEST(
        pt.current_eligible_amount_minor
        - GREATEST(
            COALESCE(a.allocated_amount_minor, 0) - COALESCE(adj.adjusted_amount_minor, 0),
            0
          ),
        0
    ) AS remaining_eligible_amount_minor,
    COALESCE(rf.reserved_refund_amount_minor, 0) AS reserved_refund_amount_minor,
    COALESCE(rf.succeeded_refund_amount_minor, 0) AS succeeded_refund_amount_minor,
    COALESCE(rc.open_case_count, 0) > 0 AS has_open_reconciliation,
    pt.interpretation_policy_key,
    pt.interpretation_policy_version,
    pt.revision,
    pt.created_at,
    pt.updated_at
FROM request_engine.payment_transactions AS pt
LEFT JOIN allocation_totals AS a
  ON a.organization_id = pt.organization_id
 AND a.payment_transaction_id = pt.payment_transaction_id
LEFT JOIN adjustment_totals AS adj
  ON adj.organization_id = pt.organization_id
 AND adj.payment_transaction_id = pt.payment_transaction_id
LEFT JOIN refund_totals AS rf
  ON rf.organization_id = pt.organization_id
 AND rf.payment_transaction_id = pt.payment_transaction_id
LEFT JOIN reconciliation_totals AS rc
  ON rc.organization_id = pt.organization_id
 AND rc.payment_transaction_id = pt.payment_transaction_id;

COMMENT ON VIEW request_read.payment_transaction_status_v1 IS
'Derived financial read model. current_eligible_amount_minor remains authoritative on PaymentTransaction; all derived totals are query projections.';

CREATE VIEW request_read.external_commitment_status_v1
WITH (security_invoker = true) AS
WITH coverage AS (
    SELECT
        ecrl.organization_id,
        ecrl.reservation_id,
        ecrl.external_commitment_id,
        count(*) AS covered_requirement_count
    FROM request_engine.external_commitment_requirement_links AS ecrl
    GROUP BY
        ecrl.organization_id,
        ecrl.reservation_id,
        ecrl.external_commitment_id
)
SELECT
    rec.organization_id,
    rec.reservation_id,
    r.public_id AS reservation_public_id,
    rec.external_commitment_id,
    ec.public_id AS external_commitment_public_id,
    pc.public_id AS provider_connection_public_id,
    pc.provider_kind,
    ec.external_commitment_ref,
    rec.mandatory,
    ec.status,
    ec.verified_at,
    ec.valid_until,
    ec.release_capability,
    COALESCE(c.covered_requirement_count, 0) AS covered_requirement_count,
    ec.status = 'committed'
      AND (ec.valid_until IS NULL OR ec.valid_until > clock_timestamp())
      AS is_wall_clock_current,
    ec.source_policy_key,
    ec.source_policy_version,
    rec.linked_at
FROM request_engine.reservation_external_commitments AS rec
JOIN request_engine.reservations AS r
  ON r.organization_id = rec.organization_id
 AND r.reservation_id = rec.reservation_id
JOIN request_engine.external_commitments AS ec
  ON ec.organization_id = rec.organization_id
 AND ec.external_commitment_id = rec.external_commitment_id
JOIN request_engine.provider_connections AS pc
  ON pc.organization_id = ec.organization_id
 AND pc.provider_connection_id = ec.provider_connection_id
LEFT JOIN coverage AS c
  ON c.organization_id = rec.organization_id
 AND c.reservation_id = rec.reservation_id
 AND c.external_commitment_id = rec.external_commitment_id;

COMMENT ON VIEW request_read.external_commitment_status_v1 IS
'is_wall_clock_current is only temporal/status projection. ConfirmReservation still evaluates versioned external-commitment policy.';

CREATE VIEW request_read.queue_entry_status_v1
WITH (security_invoker = true) AS
SELECT
    qe.organization_id,
    qe.queue_entry_id,
    qe.public_id AS queue_entry_public_id,
    qe.admission_context,
    CASE
        WHEN qe.reservation_item_id IS NOT NULL THEN 'reservation_item'
        ELSE 'offering_selection'
    END AS admission_scope_kind,
    COALESCE(ri.public_id, os.public_id) AS admission_scope_public_id,
    qe.status,
    qe.priority_class,
    qe.enqueued_at,
    qe.ended_at
FROM request_engine.queue_entries AS qe
LEFT JOIN request_engine.reservation_items AS ri
  ON ri.organization_id = qe.organization_id
 AND ri.reservation_item_id = qe.reservation_item_id
LEFT JOIN request_engine.offering_selections AS os
  ON os.organization_id = qe.organization_id
 AND os.offering_selection_id = qe.offering_selection_id;

COMMENT ON VIEW request_read.queue_entry_status_v1 IS
'Queue ordering inputs/current state only. Absolute queue position and ETA remain non-authoritative projections.';

REVOKE ALL ON ALL TABLES IN SCHEMA request_read FROM PUBLIC;

-- ============================================================================
-- 3. Supporting indexes for established hot command/read paths
-- ============================================================================

CREATE INDEX IF NOT EXISTS ix_payment_allocation_adjustments_allocation
    ON request_engine.payment_allocation_adjustments
        (organization_id, payment_allocation_id);

CREATE INDEX IF NOT EXISTS ix_payment_allocation_adjustments_reversal
    ON request_engine.payment_allocation_adjustments
        (organization_id, financial_reversal_id)
    WHERE financial_reversal_id IS NOT NULL;

-- ============================================================================
-- 4. Narrow command primitives
-- ============================================================================

-- Hardening for the pre-existing internal CAS primitive used by the wrapper below.
ALTER FUNCTION request_engine.advance_planning_revision(bigint, bigint, bigint)
    SET search_path = pg_catalog, request_engine, pg_temp;

CREATE OR REPLACE FUNCTION request_cmd.lock_capacity_authorities(
    p_organization_id bigint,
    p_capacity_authority_ids bigint[]
)
RETURNS TABLE (
    capacity_authority_id bigint,
    configuration_revision bigint,
    schedule_revision bigint,
    planning_revision bigint
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_id bigint;
BEGIN
    IF p_organization_id IS NULL
       OR p_capacity_authority_ids IS NULL
       OR cardinality(p_capacity_authority_ids) = 0 THEN
        RAISE EXCEPTION 'organization and at least one CapacityAuthority are required'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM unnest(p_capacity_authority_ids) AS x(id)
        WHERE id IS NULL
    ) THEN
        RAISE EXCEPTION 'CapacityAuthority id list cannot contain NULL'
            USING ERRCODE = '22023';
    END IF;

    FOR v_id IN
        SELECT DISTINCT x.id
        FROM unnest(p_capacity_authority_ids) AS x(id)
        ORDER BY x.id
    LOOP
        SELECT
            ca.capacity_authority_id,
            ca.configuration_revision,
            ca.schedule_revision,
            ca.planning_revision
        INTO
            capacity_authority_id,
            configuration_revision,
            schedule_revision,
            planning_revision
        FROM request_engine.capacity_authorities AS ca
        WHERE ca.organization_id = p_organization_id
          AND ca.capacity_authority_id = v_id
        FOR UPDATE;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'CapacityAuthority % not found for organization', v_id
                USING ERRCODE = '23503';
        END IF;

        RETURN NEXT;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION request_cmd.lock_capacity_authorities(bigint, bigint[]) IS
'Locks CapacityAuthorities in ascending internal id order and returns current revisions. Called inside a Python-owned transaction.';

CREATE OR REPLACE FUNCTION request_cmd.advance_planning_revision(
    p_organization_id bigint,
    p_capacity_authority_id bigint,
    p_expected_revision bigint
)
RETURNS bigint
LANGUAGE sql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
    SELECT request_engine.advance_planning_revision($1, $2, $3);
$$;

COMMENT ON FUNCTION request_cmd.advance_planning_revision(bigint, bigint, bigint) IS
'Public persistence primitive for CAS advancement of PlanningRevision. Does not own the surrounding business transaction.';

CREATE OR REPLACE FUNCTION request_cmd.acquire_idempotency(
    p_organization_id bigint,
    p_scope text,
    p_idempotency_key text,
    p_canonical_request_hash bytea,
    p_created_by_principal_id bigint DEFAULT NULL
)
RETURNS TABLE (
    idempotency_record_id bigint,
    state text,
    logical_result jsonb,
    is_new boolean
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_record request_engine.idempotency_records%ROWTYPE;
BEGIN
    IF p_organization_id IS NULL
       OR NULLIF(btrim(p_scope), '') IS NULL
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR p_canonical_request_hash IS NULL
       OR octet_length(p_canonical_request_hash) < 32 THEN
        RAISE EXCEPTION 'invalid idempotency identity/hash'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO request_engine.idempotency_records (
        organization_id,
        scope,
        idempotency_key,
        canonical_request_hash,
        created_by_principal_id
    )
    VALUES (
        p_organization_id,
        p_scope,
        p_idempotency_key,
        p_canonical_request_hash,
        p_created_by_principal_id
    )
    ON CONFLICT (organization_id, scope, idempotency_key) DO NOTHING
    RETURNING * INTO v_record;

    IF FOUND THEN
        RETURN QUERY
        SELECT
            v_record.idempotency_record_id,
            v_record.state,
            v_record.logical_result,
            true;
        RETURN;
    END IF;

    SELECT ir.*
    INTO v_record
    FROM request_engine.idempotency_records AS ir
    WHERE ir.organization_id = p_organization_id
      AND ir.scope = p_scope
      AND ir.idempotency_key = p_idempotency_key
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'idempotency record disappeared during acquisition'
            USING ERRCODE = '40001';
    END IF;

    IF v_record.canonical_request_hash IS DISTINCT FROM p_canonical_request_hash THEN
        RAISE EXCEPTION 'idempotency key reused with a different canonical request'
            USING ERRCODE = '23505';
    END IF;

    RETURN QUERY
    SELECT
        v_record.idempotency_record_id,
        v_record.state,
        v_record.logical_result,
        false;
END;
$$;

COMMENT ON FUNCTION request_cmd.acquire_idempotency(bigint, text, text, bytea, bigint) IS
'Race-safe key/hash acquisition. Same key+different hash raises conflict; caller decides replay behavior from returned state/result.';

CREATE OR REPLACE FUNCTION request_cmd.complete_idempotency(
    p_organization_id bigint,
    p_idempotency_record_id bigint,
    p_logical_result jsonb
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_record request_engine.idempotency_records%ROWTYPE;
BEGIN
    IF p_logical_result IS NULL THEN
        RAISE EXCEPTION 'completed idempotency requires logical_result'
            USING ERRCODE = '22023';
    END IF;

    SELECT ir.*
    INTO v_record
    FROM request_engine.idempotency_records AS ir
    WHERE ir.organization_id = p_organization_id
      AND ir.idempotency_record_id = p_idempotency_record_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'idempotency record not found'
            USING ERRCODE = '23503';
    END IF;

    IF v_record.state = 'completed' THEN
        IF v_record.logical_result IS DISTINCT FROM p_logical_result THEN
            RAISE EXCEPTION 'completed idempotency result is immutable'
                USING ERRCODE = '55000';
        END IF;
        RETURN;
    END IF;

    IF v_record.state <> 'in_progress' THEN
        RAISE EXCEPTION 'idempotency record is not completable from state %', v_record.state
            USING ERRCODE = '55000';
    END IF;

    UPDATE request_engine.idempotency_records
    SET state = 'completed',
        logical_result = p_logical_result,
        completed_at = clock_timestamp()
    WHERE organization_id = p_organization_id
      AND idempotency_record_id = p_idempotency_record_id;
END;
$$;

COMMENT ON FUNCTION request_cmd.complete_idempotency(bigint, bigint, jsonb) IS
'Completes an in-progress idempotency record inside the same Python-owned transaction as the authoritative command result.';

CREATE OR REPLACE FUNCTION request_cmd.claim_outbox_batch(
    p_worker_id text,
    p_batch_size integer DEFAULT 100,
    p_lease_timeout interval DEFAULT interval '5 minutes'
)
RETURNS TABLE (
    organization_id bigint,
    outbox_message_id bigint,
    public_id uuid,
    domain_event_id bigint,
    message_type text,
    destination text,
    idempotency_key text,
    payload jsonb,
    attempt_count integer,
    available_at timestamptz,
    claimed_at timestamptz
)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
BEGIN
    IF NULLIF(btrim(p_worker_id), '') IS NULL THEN
        RAISE EXCEPTION 'worker_id is required' USING ERRCODE = '22023';
    END IF;

    IF p_batch_size < 1 OR p_batch_size > 500 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 500' USING ERRCODE = '22023';
    END IF;

    IF p_lease_timeout IS NULL OR p_lease_timeout <= interval '0 seconds' THEN
        RAISE EXCEPTION 'lease_timeout must be positive' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH candidates AS (
        SELECT
            om.organization_id,
            om.outbox_message_id
        FROM request_engine.outbox_messages AS om
        WHERE om.delivered_at IS NULL
          AND om.available_at <= v_now
          AND (
              om.claimed_at IS NULL
              OR om.claimed_at < v_now - p_lease_timeout
          )
        ORDER BY om.available_at, om.outbox_message_id
        FOR UPDATE SKIP LOCKED
        LIMIT p_batch_size
    )
    UPDATE request_engine.outbox_messages AS om
    SET claimed_at = v_now,
        claimed_by = p_worker_id,
        attempt_count = om.attempt_count + 1
    FROM candidates AS c
    WHERE om.organization_id = c.organization_id
      AND om.outbox_message_id = c.outbox_message_id
    RETURNING
        om.organization_id,
        om.outbox_message_id,
        om.public_id,
        om.domain_event_id,
        om.message_type,
        om.destination,
        om.idempotency_key,
        om.payload,
        om.attempt_count,
        om.available_at,
        om.claimed_at;
END;
$$;

COMMENT ON FUNCTION request_cmd.claim_outbox_batch(text, integer, interval) IS
'Worker-only atomic outbox claim using FOR UPDATE SKIP LOCKED. Stale claims become reclaimable after the supplied lease timeout.';

CREATE OR REPLACE FUNCTION request_cmd.mark_outbox_delivered(
    p_organization_id bigint,
    p_outbox_message_id bigint,
    p_worker_id text
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
BEGIN
    UPDATE request_engine.outbox_messages AS om
    SET delivered_at = clock_timestamp(),
        last_error = NULL
    WHERE om.organization_id = p_organization_id
      AND om.outbox_message_id = p_outbox_message_id
      AND om.delivered_at IS NULL
      AND om.claimed_by = p_worker_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'outbox message not claim-owned or already delivered'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

COMMENT ON FUNCTION request_cmd.mark_outbox_delivered(bigint, bigint, text) IS
'Marks delivery only for the worker that currently owns the claim.';

CREATE OR REPLACE FUNCTION request_cmd.release_outbox_claim(
    p_organization_id bigint,
    p_outbox_message_id bigint,
    p_worker_id text,
    p_error text,
    p_retry_after interval DEFAULT interval '30 seconds'
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
BEGIN
    IF p_retry_after IS NULL OR p_retry_after < interval '0 seconds' THEN
        RAISE EXCEPTION 'retry_after cannot be negative' USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages AS om
    SET claimed_at = NULL,
        claimed_by = NULL,
        available_at = GREATEST(om.available_at, v_now + p_retry_after),
        last_error = p_error
    WHERE om.organization_id = p_organization_id
      AND om.outbox_message_id = p_outbox_message_id
      AND om.delivered_at IS NULL
      AND om.claimed_by = p_worker_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'outbox message not claim-owned or already delivered'
            USING ERRCODE = '55000';
    END IF;
END;
$$;

COMMENT ON FUNCTION request_cmd.release_outbox_claim(bigint, bigint, text, text, interval) IS
'Releases a worker-owned outbox claim and schedules the next retry without changing at-least-once semantics.';

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA request_cmd FROM PUBLIC;

-- ============================================================================
-- 5. Admin/diagnostic read surface
-- ============================================================================

CREATE VIEW request_admin.outbox_health_v1
WITH (security_invoker = true) AS
SELECT
    om.organization_id,
    count(*) FILTER (
        WHERE om.delivered_at IS NULL
    ) AS undelivered_count,
    count(*) FILTER (
        WHERE om.delivered_at IS NULL
          AND om.claimed_at IS NOT NULL
    ) AS claimed_count,
    count(*) FILTER (
        WHERE om.delivered_at IS NULL
          AND om.available_at <= clock_timestamp()
          AND (
              om.claimed_at IS NULL
              OR om.claimed_at < clock_timestamp() - interval '5 minutes'
          )
    ) AS default_lease_claimable_count,
    min(om.available_at) FILTER (
        WHERE om.delivered_at IS NULL
    ) AS oldest_undelivered_available_at,
    max(om.attempt_count) FILTER (
        WHERE om.delivered_at IS NULL
    ) AS max_undelivered_attempt_count
FROM request_engine.outbox_messages AS om
GROUP BY om.organization_id;

COMMENT ON VIEW request_admin.outbox_health_v1 IS
'Diagnostic outbox projection. default_lease_claimable_count uses the V2.10 default five-minute lease and is not worker authority.';

CREATE VIEW request_admin.open_reconciliation_v1
WITH (security_invoker = true) AS
SELECT
    rc.organization_id,
    rc.reconciliation_case_id,
    rc.public_id AS reconciliation_case_public_id,
    pt.public_id AS payment_transaction_public_id,
    rc.status,
    rc.reason_code,
    rc.details,
    rc.revision,
    rc.opened_at
FROM request_engine.reconciliation_cases AS rc
LEFT JOIN request_engine.payment_transactions AS pt
  ON pt.organization_id = rc.organization_id
 AND pt.payment_transaction_id = rc.payment_transaction_id
WHERE rc.status IN ('open', 'under_review');

COMMENT ON VIEW request_admin.open_reconciliation_v1 IS
'Diagnostic list of unresolved reconciliation cases. Resolution remains an application command with row locking/version checks.';

REVOKE ALL ON ALL TABLES IN SCHEMA request_admin FROM PUBLIC;

-- ============================================================================
-- 6. Deployment privilege contract
-- ============================================================================
--
-- Runtime roles are intentionally NOT created here. Role provisioning is
-- deployment/cluster-specific and may require CREATEROLE beyond Alembic's DDL
-- owner. Provisioning should grant only the required surface, for example:
--
--   request_app:
--     USAGE request_read, request_cmd
--     SELECT request_read.*
--     EXECUTE only app-safe request_cmd functions
--     explicit DML on request_engine tables required by command repositories
--
--   request_worker:
--     USAGE request_cmd
--     EXECUTE claim/mark/release outbox functions
--
--   request_readonly:
--     USAGE request_read
--     SELECT request_read.*
--
-- Views use security_invoker=true deliberately. If RLS is introduced later,
-- base-table privileges/policies for the invoking role must be designed together;
-- the view contract is not by itself a tenant authorization boundary.

COMMIT;
