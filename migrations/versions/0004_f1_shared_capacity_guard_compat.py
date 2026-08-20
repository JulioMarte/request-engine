"""Preserve V3 shared-capacity semantics in the F1 CapacityClaim guard.

Revision ID: 0004_f1_capacity_guard
Revises: 0003_f1_context_sources
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_f1_capacity_guard"
down_revision: str | Sequence[str] | None = "0003_f1_context_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- F1 extends CapacityClaim with ResourceLocationAssignment provenance.  The
-- released V3 guard also owns the cross-tenant SharedCapacityIdentity conflict
-- check, promotion validation, and linked-claim invariants.  Keep that released
-- behavior intact and add only the contextual Location/assignment branch.
CREATE OR REPLACE FUNCTION request_engine.guard_capacity_claim()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
DECLARE
    v_capacity_model text;
    v_capacity_units integer;
    v_resource_active boolean;
    v_resource_location uuid;
    v_owner_offering_version uuid;
    v_owner_during tstzrange;
    v_owner_location uuid;
    v_requirement_offering_version uuid;
    v_required_capability uuid;
    v_required_quantity integer;
    v_other_quantity bigint;
    v_other_count bigint;
    v_promoting_hold boolean;
    v_shared_capacity_identity_id uuid;
    v_shared_conflict boolean;
    v_assignment_resource uuid;
    v_assignment_location uuid;
    v_assignment_during tstzrange;
    v_assignment_status text;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT r.capacity_model, r.capacity_units, r.active, r.location_id
      INTO v_capacity_model, v_capacity_units, v_resource_active, v_resource_location
      FROM request_engine.resources r
     WHERE r.organization_id = NEW.organization_id
       AND r.id = NEW.resource_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % does not exist for capacity claim', NEW.resource_id
            USING ERRCODE = '23503';
    END IF;
    IF NOT v_resource_active THEN
        RAISE EXCEPTION 'Resource % is inactive', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.resource_id <> NEW.resource_id AND EXISTS (
        SELECT 1 FROM request_engine.shared_capacity_claim_links
         WHERE capacity_claim_id = OLD.id
    ) THEN
        RAISE EXCEPTION 'linked CapacityClaim cannot move between Resources; release/recreate it'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.reservation_id IS NOT NULL THEN
        SELECT r.offering_version_id, r.during, r.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.reservations r
         WHERE r.organization_id = NEW.organization_id
           AND r.id = NEW.reservation_id
           AND r.status = 'confirmed';
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'active reservation claim requires confirmed Reservation %',
                NEW.reservation_id
                USING ERRCODE = '23514';
        END IF;

        v_promoting_hold := NEW.hold_id IS NOT NULL AND (
            TG_OP = 'INSERT' OR OLD.reservation_id IS NULL
        );
        IF v_promoting_hold AND NOT EXISTS (
            SELECT 1
              FROM request_engine.capacity_holds h
             WHERE h.organization_id = NEW.organization_id
               AND h.id = NEW.hold_id
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
               AND h.offering_version_id = v_owner_offering_version
               AND h.during = v_owner_during
        ) THEN
            RAISE EXCEPTION
                'cannot promote expired, terminal, or mismatched CapacityHold %',
                NEW.hold_id
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.hold_id IS NULL THEN
            RAISE EXCEPTION 'active hold claim requires CapacityHold'
                USING ERRCODE = '23514';
        END IF;
        SELECT h.offering_version_id, h.during, h.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.capacity_holds h
         WHERE h.organization_id = NEW.organization_id
           AND h.id = NEW.hold_id
           AND h.status = 'active'
           AND h.expires_at > clock_timestamp();
        IF NOT FOUND THEN
            RAISE EXCEPTION 'active hold claim requires live, unexpired CapacityHold %', NEW.hold_id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.during <> v_owner_during THEN
        RAISE EXCEPTION 'CapacityClaim interval must equal its Hold/Reservation interval'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.resource_location_assignment_id IS NOT NULL THEN
        SELECT a.resource_id, a.location_id, a.effective_during, a.status
          INTO v_assignment_resource,
               v_assignment_location,
               v_assignment_during,
               v_assignment_status
          FROM request_engine.resource_location_assignments a
         WHERE a.organization_id = NEW.organization_id
           AND a.id = NEW.resource_location_assignment_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'ResourceLocationAssignment % does not exist for capacity claim',
                NEW.resource_location_assignment_id USING ERRCODE = '23503';
        END IF;
        IF v_assignment_resource <> NEW.resource_id THEN
            RAISE EXCEPTION
                'CapacityClaim ResourceLocationAssignment belongs to a different Resource'
                USING ERRCODE = '23514';
        END IF;
        IF v_assignment_status <> 'active' THEN
            RAISE EXCEPTION 'CapacityClaim ResourceLocationAssignment is not active'
                USING ERRCODE = '23514';
        END IF;
        IF v_owner_location IS NULL OR v_owner_location <> v_assignment_location THEN
            RAISE EXCEPTION
                'CapacityClaim ResourceLocationAssignment belongs to a different Location '
                'than the Hold/Reservation'
                USING ERRCODE = '23514';
        END IF;
        IF NOT (v_assignment_during @> NEW.during) THEN
            RAISE EXCEPTION
                'CapacityClaim interval is outside ResourceLocationAssignment effective range'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_owner_location IS NOT NULL
       AND v_resource_location IS NOT NULL
       AND v_owner_location <> v_resource_location THEN
        RAISE EXCEPTION
            'Resource % belongs to a different Location than the Hold/Reservation',
            NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    SELECT rr.offering_version_id, rr.capability_id, rr.quantity
      INTO v_requirement_offering_version, v_required_capability, v_required_quantity
      FROM request_engine.offering_resource_requirements rr
     WHERE rr.organization_id = NEW.organization_id
       AND rr.id = NEW.requirement_id;
    IF NOT FOUND OR v_requirement_offering_version <> v_owner_offering_version THEN
        RAISE EXCEPTION 'CapacityClaim requirement does not belong to the owner OfferingVersion'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.quantity <> v_required_quantity THEN
        RAISE EXCEPTION
            'CapacityClaim quantity % does not satisfy requirement quantity %',
            NEW.quantity,
            v_required_quantity
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM request_engine.resource_capability_assignments a
         WHERE a.organization_id = NEW.organization_id
           AND a.resource_id = NEW.resource_id
           AND a.capability_id = v_required_capability
    ) THEN
        RAISE EXCEPTION 'Resource % does not satisfy required capability', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(sum(c.quantity), 0), count(*)
      INTO v_other_quantity, v_other_count
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id AND h.id = c.hold_id
     WHERE c.organization_id = NEW.organization_id
       AND c.resource_id = NEW.resource_id
       AND c.status = 'active'
       AND c.id <> NEW.id
       AND c.during && NEW.during
       AND (
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed') OR
           (c.reservation_id IS NULL AND h.status = 'active' AND h.expires_at > clock_timestamp())
       );
    IF v_capacity_model = 'exclusive' AND v_other_count > 0 THEN
        RAISE EXCEPTION 'exclusive Resource % has overlapping live capacity', NEW.resource_id
            USING ERRCODE = '23P01';
    END IF;
    IF v_capacity_model = 'units' AND v_other_quantity + NEW.quantity > v_capacity_units THEN
        RAISE EXCEPTION 'Resource % capacity exceeded: requested %, live %, capacity %',
            NEW.resource_id, NEW.quantity, v_other_quantity, v_capacity_units
            USING ERRCODE = '23P01';
    END IF;

    SELECT b.shared_capacity_identity_id
      INTO v_shared_capacity_identity_id
      FROM request_engine.shared_capacity_bindings b
     WHERE b.organization_id = NEW.organization_id
       AND b.resource_id = NEW.resource_id
       AND b.status = 'active';

    IF v_shared_capacity_identity_id IS NOT NULL THEN
        PERFORM 1
          FROM request_engine.shared_capacity_identities
         WHERE id = v_shared_capacity_identity_id
           AND status = 'active'
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'capacity unavailable'
                USING ERRCODE = '23P01';
        END IF;

        SELECT EXISTS (
            SELECT 1
              FROM request_engine.shared_capacity_claim_links link
              JOIN request_engine.capacity_claims c
                ON c.id = link.capacity_claim_id
              LEFT JOIN request_engine.reservations r
                ON r.organization_id = c.organization_id AND r.id = c.reservation_id
              LEFT JOIN request_engine.capacity_holds h
                ON h.organization_id = c.organization_id AND h.id = c.hold_id
             WHERE link.shared_capacity_identity_id = v_shared_capacity_identity_id
               AND c.id <> NEW.id
               AND c.status = 'active'
               AND c.during && NEW.during
               AND (
                   (c.reservation_id IS NOT NULL AND r.status = 'confirmed') OR
                   (c.reservation_id IS NULL AND h.status = 'active'
                    AND h.expires_at > clock_timestamp())
               )
        ) INTO v_shared_conflict;

        IF v_shared_conflict THEN
            RAISE EXCEPTION 'capacity unavailable'
                USING ERRCODE = '23P01';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    raise RuntimeError("F1 shared-capacity guard compatibility is append-only production history")
