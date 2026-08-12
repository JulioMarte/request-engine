BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_claim()
RETURNS trigger
LANGUAGE plpgsql
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

    IF NEW.reservation_id IS NOT NULL THEN
        SELECT r.offering_version_id, r.during, r.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.reservations r
         WHERE r.organization_id = NEW.organization_id
           AND r.id = NEW.reservation_id
           AND r.status = 'confirmed';

        IF NOT FOUND THEN
            RAISE EXCEPTION 'active reservation claim requires confirmed Reservation %', NEW.reservation_id
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
            RAISE EXCEPTION 'cannot promote expired, terminal, or mismatched CapacityHold %', NEW.hold_id
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

    IF v_owner_location IS NOT NULL
       AND v_resource_location IS NOT NULL
       AND v_owner_location <> v_resource_location THEN
        RAISE EXCEPTION 'Resource % belongs to a different Location than the Hold/Reservation', NEW.resource_id
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
        RAISE EXCEPTION 'CapacityClaim quantity % does not satisfy requirement quantity %', NEW.quantity, v_required_quantity
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM request_engine.resource_capability_assignments a
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
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
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

    RETURN NEW;
END
$function$;

RESET ROLE;
COMMIT;
