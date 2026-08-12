BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- ---------------------------------------------------------------------------
-- V3 contract convergence
--
-- Affected invariants:
--   V3-I17 / I18  capacity consumption remains bounded by Resource capacity
--   V3-I19 / I21  Hold/Reservation claim sets remain complete and non-empty
--   V3-I23 / I28  cancelled Reservations retain no active consuming claims
--   V3-I62        aggregate revision advances exactly one step per UPDATE
--
-- `03-db-contract-convergence.md` is normative for these pre-baseline
-- decisions until folded back into the canonical V3 contract.
-- ---------------------------------------------------------------------------

-- quantity is capacity consumption on one selected concrete Resource. It is
-- intentionally not resource-cardinality / k-of-n / pool semantics.
COMMENT ON COLUMN request_engine.offering_resource_requirements.quantity IS
    'Capacity units required on the one concrete Resource selected for this requirement; not a count of Resources.';
COMMENT ON COLUMN request_engine.capacity_claims.quantity IS
    'Capacity units consumed on this claim Resource; must equal the referenced requirement quantity.';

-- ---------------------------------------------------------------------------
-- Temporal live-commitment semantics
-- ---------------------------------------------------------------------------
-- A confirmed Reservation remains durable historical truth after its interval
-- ends, but a past interval must not permanently freeze capacity/location/
-- active-state maintenance on the Resource. Range-overlap validation already
-- has this temporal property; this guard now uses the same principle.

CREATE OR REPLACE FUNCTION request_engine.guard_resource_commitment_sensitive_change()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_live_claims bigint;
BEGIN
    IF NEW.capacity_model = OLD.capacity_model
       AND NEW.capacity_units = OLD.capacity_units
       AND NEW.active = OLD.active
       AND NEW.location_id IS NOT DISTINCT FROM OLD.location_id THEN
        RETURN NEW;
    END IF;

    SELECT count(*)
      INTO v_live_claims
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
     WHERE c.organization_id = OLD.organization_id
       AND c.resource_id = OLD.id
       AND c.status = 'active'
       AND (
           (
               c.reservation_id IS NOT NULL
               AND r.status = 'confirmed'
               AND upper(c.during) > clock_timestamp()
           ) OR
           (
               c.reservation_id IS NULL
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
           )
       );

    IF v_live_claims > 0 THEN
        RAISE EXCEPTION 'Resource % has live capacity commitments; capacity/active/location change requires explicit commitment handling', OLD.id
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

-- ---------------------------------------------------------------------------
-- Canonical revision advancement (V3-I62)
-- ---------------------------------------------------------------------------
-- Revision is an opaque optimistic-concurrency token. Every authoritative row
-- UPDATE advances exactly one step. Existing command code that explicitly does
-- revision = revision + 1 remains valid. Trusted/internal SQL that leaves the
-- value unchanged gets the canonical step supplied here. Arbitrary jumps and
-- backward revisions are rejected.

CREATE FUNCTION request_engine.guard_exact_revision_step()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.revision = OLD.revision THEN
        NEW.revision := OLD.revision + 1;
    ELSIF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION '% revision must advance exactly one step: old %, attempted %',
            TG_TABLE_NAME, OLD.revision, NEW.revision
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER representations_revision_step
BEFORE UPDATE ON request_engine.representations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER requests_revision_step
BEFORE UPDATE ON request_engine.requests
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER capacity_holds_revision_step
BEFORE UPDATE ON request_engine.capacity_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER reservations_revision_step
BEFORE UPDATE ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER service_queues_revision_step
BEFORE UPDATE ON request_engine.service_queues
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER queue_entries_revision_step
BEFORE UPDATE ON request_engine.queue_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER waitlist_entries_revision_step
BEFORE UPDATE ON request_engine.waitlist_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER slot_opportunities_revision_step
BEFORE UPDATE ON request_engine.slot_opportunities
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER slot_offers_revision_step
BEFORE UPDATE ON request_engine.slot_offers
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER communication_tasks_revision_step
BEFORE UPDATE ON request_engine.communication_tasks
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER reminder_plans_revision_step
BEFORE UPDATE ON request_engine.reminder_plans
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

COMMIT;
