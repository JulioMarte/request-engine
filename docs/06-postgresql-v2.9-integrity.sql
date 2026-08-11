-- Request Engine V2.9 — relational integrity hardening
-- Target: PostgreSQL 18+
-- Applies after:
--   docs/03-postgresql-schema.sql
--   docs/04-postgresql-v2.7-hardening.sql
--   docs/05-postgresql-v2.8-hardening.sql
-- Normative source: docs/02-pre-sql-domain-contract.md
--
-- Scope is intentionally narrow:
--   1. prove financial lineage stays inside one PaymentTransaction;
--   2. make confirmed external commitment coverage relational and typed.
--
-- Prefer UNIQUE + FOREIGN KEY over trigger checks when PostgreSQL can prove the
-- relationship continuously. PostgreSQL requires referenced FK columns to be a
-- primary key, unique constraint, or non-partial unique index.

BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = request_engine, public;

-- ============================================================================
-- 1. Financial lineage: every correction belongs to its observation transaction
-- ============================================================================

ALTER TABLE financial_observations
    ADD CONSTRAINT uq_financial_observations_transaction_key
    UNIQUE (organization_id, payment_transaction_id, financial_observation_id);

ALTER TABLE observation_corrections
    DROP CONSTRAINT fk_observation_corrections_observation,
    ADD CONSTRAINT fk_observation_corrections_observation_transaction
    FOREIGN KEY (
        organization_id,
        payment_transaction_id,
        target_financial_observation_id
    )
    REFERENCES financial_observations (
        organization_id,
        payment_transaction_id,
        financial_observation_id
    )
    ON DELETE RESTRICT;

-- ============================================================================
-- 2. Allocation adjustments cannot cross PaymentTransaction boundaries
-- ============================================================================

ALTER TABLE payment_allocations
    ADD CONSTRAINT uq_payment_allocations_transaction_key
    UNIQUE (organization_id, payment_transaction_id, payment_allocation_id);

ALTER TABLE observation_corrections
    ADD CONSTRAINT uq_observation_corrections_transaction_key
    UNIQUE (organization_id, payment_transaction_id, observation_correction_id);

ALTER TABLE financial_reversals
    ADD CONSTRAINT uq_financial_reversals_transaction_key
    UNIQUE (organization_id, payment_transaction_id, financial_reversal_id);

ALTER TABLE payment_allocation_adjustments
    ADD COLUMN payment_transaction_id bigint;

-- The table is append-only in normal operation. The migration temporarily
-- disables only that local history trigger so existing rows can be backfilled;
-- all FK/check constraints remain active and the trigger is restored immediately.
ALTER TABLE payment_allocation_adjustments
    DISABLE TRIGGER trg_payment_allocation_adjustments_append_only;

UPDATE payment_allocation_adjustments paa
   SET payment_transaction_id = pa.payment_transaction_id
  FROM payment_allocations pa
 WHERE pa.organization_id = paa.organization_id
   AND pa.payment_allocation_id = paa.payment_allocation_id;

ALTER TABLE payment_allocation_adjustments
    ENABLE TRIGGER trg_payment_allocation_adjustments_append_only;

ALTER TABLE payment_allocation_adjustments
    ALTER COLUMN payment_transaction_id SET NOT NULL,
    DROP CONSTRAINT fk_payment_allocation_adjustments_allocation,
    DROP CONSTRAINT fk_payment_allocation_adjustments_correction,
    DROP CONSTRAINT fk_payment_allocation_adjustments_reversal,
    ADD CONSTRAINT fk_payment_allocation_adjustments_allocation_transaction
        FOREIGN KEY (
            organization_id,
            payment_transaction_id,
            payment_allocation_id
        )
        REFERENCES payment_allocations (
            organization_id,
            payment_transaction_id,
            payment_allocation_id
        )
        ON DELETE RESTRICT,
    ADD CONSTRAINT fk_payment_allocation_adjustments_correction_transaction
        FOREIGN KEY (
            organization_id,
            payment_transaction_id,
            observation_correction_id
        )
        REFERENCES observation_corrections (
            organization_id,
            payment_transaction_id,
            observation_correction_id
        )
        ON DELETE RESTRICT,
    ADD CONSTRAINT fk_payment_allocation_adjustments_reversal_transaction
        FOREIGN KEY (
            organization_id,
            payment_transaction_id,
            financial_reversal_id
        )
        REFERENCES financial_reversals (
            organization_id,
            payment_transaction_id,
            financial_reversal_id
        )
        ON DELETE RESTRICT;

COMMENT ON COLUMN payment_allocation_adjustments.payment_transaction_id IS
'Denormalized relational key used to prove that the Allocation and its Correction/Reversal source belong to the same PaymentTransaction.';

-- ============================================================================
-- 3. External commitment coverage: JSON is evidence, typed FKs are authority
-- ============================================================================
--
-- external_commitments.scope_snapshot remains historical provider/policy evidence.
-- It must not be the sole proof that a confirmed Reservation requirement is
-- covered. This relation proves all three rows share tenant + Reservation.

CREATE TABLE external_commitment_requirement_links (
    organization_id bigint NOT NULL,
    reservation_id bigint NOT NULL,
    external_commitment_id bigint NOT NULL,
    commitment_requirement_id bigint NOT NULL,
    linked_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (
        organization_id,
        reservation_id,
        external_commitment_id,
        commitment_requirement_id
    ),
    CONSTRAINT fk_external_commitment_requirement_links_reservation_commitment
        FOREIGN KEY (
            organization_id,
            reservation_id,
            external_commitment_id
        )
        REFERENCES reservation_external_commitments (
            organization_id,
            reservation_id,
            external_commitment_id
        )
        ON DELETE RESTRICT,
    CONSTRAINT fk_external_commitment_requirement_links_requirement
        FOREIGN KEY (
            organization_id,
            reservation_id,
            commitment_requirement_id
        )
        REFERENCES commitment_requirements (
            organization_id,
            reservation_id,
            commitment_requirement_id
        )
        ON DELETE RESTRICT
);

COMMENT ON TABLE external_commitment_requirement_links IS
'Typed authoritative coverage of materialized CommitmentRequirements by external commitments already linked to the same Reservation; scope_snapshot remains evidence, not authority.';

-- No additional indexes are added: the primary key supports the principal
-- Reservation/commitment lookup prefix, and referenced rows are immutable or
-- delete-restricted. Add workload-specific indexes only after measured queries.

COMMIT;
