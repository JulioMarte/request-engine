BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- A Resource may be re-authorized after revocation, including back to the same
-- SharedCapacityIdentity.  It may not, however, be moved to a different shared
-- root while a live CapacityClaim still carries historical serialization
-- provenance for the old root.  That would make one physical commitment stop
-- consuming the old root and ambiguously start consuming another.
CREATE FUNCTION request_engine.guard_shared_capacity_rebinding()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM request_engine.capacity_claims c
          JOIN request_engine.shared_capacity_claim_links link
            ON link.capacity_claim_id = c.id
          LEFT JOIN request_engine.reservations r
            ON r.organization_id = c.organization_id
           AND r.id = c.reservation_id
          LEFT JOIN request_engine.capacity_holds h
            ON h.organization_id = c.organization_id
           AND h.id = c.hold_id
         WHERE c.organization_id = NEW.organization_id
           AND c.resource_id = NEW.resource_id
           AND link.shared_capacity_identity_id <> NEW.shared_capacity_identity_id
           AND c.status = 'active'
           AND (
               (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
               OR
               (c.reservation_id IS NULL AND h.status = 'active'
                AND h.expires_at > clock_timestamp())
           )
    ) THEN
        RAISE EXCEPTION 'Resource has live commitments bound to another shared capacity root'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER shared_capacity_bindings_guard_rebinding
BEFORE INSERT ON request_engine.shared_capacity_bindings
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_shared_capacity_rebinding();

REVOKE ALL ON FUNCTION request_engine.guard_shared_capacity_rebinding() FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
