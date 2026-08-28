"""Advance F5 freshness from booking commitment changes.

Revision ID: 0015_f5_commitment_freshness
Revises: 0014_f5_auto_proposals
Create Date: 2026-08-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015_f5_commitment_freshness"
down_revision: str | Sequence[str] | None = "0014_f5_auto_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- Contract docs/v3/32-operational-recovery-communications-contract.md section 5
-- requires every material source change that advances F4 recovery truth to
-- durably request reprojection, explicitly including "Booking commitments that
-- enter, move or leave the assessed scope". No recovery-freshness trigger
-- existed on the commitment tables yet.
--
-- CapacityClaim is the V3 single capacity truth for Hold/Reservation
-- commitments, so capacity_claims is the primary commitment-change surface:
--   * INSERT of an active claim            -> commitment enters the scope;
--   * UPDATE of `during`                   -> commitment moves inside the scope;
--   * UPDATE of `quantity`                 -> committed workload magnitude moves;
--   * UPDATE of status to a terminal value
--     ('released'/'replaced') or DELETE    -> commitment leaves the scope;
--   * UPDATE of owner link (hold_id/reservation_id)
--                                          -> commitment moves between the
--                                             unplanned-live and planned scopes.
-- reservations is covered as well because the F4 planned-work observation reads
-- reservations.location_id, reservations.during and reservations.status
-- directly; a reservation reposition/cancel repositions the commitment even
-- when claim rows are mutated in a neighbouring statement of the same command.
--
-- Row -> ServiceQueue mapping uses live_capacity_projection_policies, the
-- accepted recovery scope definition (also used by the 0009 resource_activities
-- and 0012 locations/resources triggers): a policy pins one ServiceQueue to one
-- (resource_id, location_id) scope. Hold-only claims are resource-scoped, since
-- F4 counts unplanned live claims for every scope of that resource; claims
-- owned by a Reservation are location-scoped through reservations.location_id,
-- since F4 planned work filters r.location_id = scope.location. A NULL
-- reservation location matches no scope, mirroring the F4 read filter.
--
-- Bookkeeping columns (updated_at, revision, booking_policy_snapshot) churn
-- without moving F4 truth, so like 0012 this trigger only bumps when an
-- assessed-scope column actually changed. When the owner identity changes, the
-- OLD owner mapping is also bumped because the commitment left that scope.
--
-- Tenant safety: the functions are SECURITY DEFINER owned by
-- request_engine_schema_owner with a pinned search_path, run only as row
-- triggers, read live_capacity_projection_policies through the 0012
-- trigger-context policy, and delegate the tenant-scoped revision bump and
-- reassessment enqueue to bump_recovery_source_revision (0013), which pins the
-- organization GUC itself. Revoking PUBLIC keeps the reviewed app/worker
-- executable function surface unchanged.

CREATE FUNCTION request_engine.bump_capacity_claim_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_organization_id uuid;
    v_resource_id uuid;
    v_reservation_id uuid;
    v_queue_id uuid;
    v_scope integer;
    v_scopes integer := 1;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_resource_id := OLD.resource_id;
        v_reservation_id := OLD.reservation_id;
    ELSE
        IF TG_OP = 'UPDATE'
           AND (NEW.organization_id, NEW.resource_id, NEW.hold_id,
                NEW.reservation_id, NEW.during, NEW.quantity, NEW.status)
               IS NOT DISTINCT FROM
               (OLD.organization_id, OLD.resource_id, OLD.hold_id,
                OLD.reservation_id, OLD.during, OLD.quantity, OLD.status) THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'UPDATE'
           AND (OLD.organization_id, OLD.resource_id, OLD.hold_id, OLD.reservation_id)
               IS DISTINCT FROM
               (NEW.organization_id, NEW.resource_id, NEW.hold_id, NEW.reservation_id) THEN
            v_scopes := 2;
        END IF;
        v_organization_id := NEW.organization_id;
        v_resource_id := NEW.resource_id;
        v_reservation_id := NEW.reservation_id;
    END IF;

    FOR v_scope IN 1..v_scopes LOOP
        IF v_scope = 2 THEN
            v_organization_id := OLD.organization_id;
            v_resource_id := OLD.resource_id;
            v_reservation_id := OLD.reservation_id;
        END IF;
        FOR v_queue_id IN
            SELECT p.service_queue_id
            FROM request_engine.live_capacity_projection_policies p
            WHERE p.organization_id = v_organization_id
              AND p.resource_id = v_resource_id
              AND (
                  v_reservation_id IS NULL
                  OR p.location_id = (
                      SELECT r.location_id
                      FROM request_engine.reservations r
                      WHERE r.organization_id = v_organization_id
                        AND r.id = v_reservation_id
                  )
              )
        LOOP
            PERFORM request_engine.bump_recovery_source_revision(
                v_organization_id, v_queue_id
            );
        END LOOP;
    END LOOP;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION request_engine.bump_capacity_claim_recovery_source_revision()
  FROM PUBLIC;

CREATE TRIGGER capacity_claims_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_capacity_claim_recovery_source_revision();

CREATE FUNCTION request_engine.bump_reservation_recovery_source_revision()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = request_engine, pg_catalog
AS $function$
DECLARE
    v_organization_id uuid;
    v_location_id uuid;
    v_reservation_id uuid;
    v_queue_id uuid;
    v_scope integer;
    v_scopes integer := 1;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_location_id := OLD.location_id;
        v_reservation_id := OLD.id;
    ELSE
        IF TG_OP = 'UPDATE'
           AND (NEW.location_id, NEW.during, NEW.status)
               IS NOT DISTINCT FROM
               (OLD.location_id, OLD.during, OLD.status) THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'UPDATE'
           AND (OLD.organization_id, OLD.location_id)
               IS DISTINCT FROM
               (NEW.organization_id, NEW.location_id) THEN
            v_scopes := 2;
        END IF;
        v_organization_id := NEW.organization_id;
        v_location_id := NEW.location_id;
        v_reservation_id := NEW.id;
    END IF;

    FOR v_scope IN 1..v_scopes LOOP
        IF v_scope = 2 THEN
            v_organization_id := OLD.organization_id;
            v_location_id := OLD.location_id;
        END IF;
        FOR v_queue_id IN
            SELECT DISTINCT p.service_queue_id
            FROM request_engine.live_capacity_projection_policies p
            JOIN request_engine.capacity_claims c
              ON c.organization_id = p.organization_id
             AND c.resource_id = p.resource_id
            WHERE p.organization_id = v_organization_id
              AND p.location_id = v_location_id
              AND c.reservation_id = v_reservation_id
              AND c.status = 'active'
        LOOP
            PERFORM request_engine.bump_recovery_source_revision(
                v_organization_id, v_queue_id
            );
        END LOOP;
    END LOOP;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$function$;
REVOKE ALL ON FUNCTION request_engine.bump_reservation_recovery_source_revision()
  FROM PUBLIC;

CREATE TRIGGER reservations_bump_recovery_source_revision
AFTER INSERT OR UPDATE OR DELETE ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_reservation_recovery_source_revision();

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0015 extends booking commitment freshness and is not reversible in place")
