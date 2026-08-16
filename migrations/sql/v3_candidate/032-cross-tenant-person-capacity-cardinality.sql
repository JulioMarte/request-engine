BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- A person represents one indivisible physical actor in the initial
-- shared-capacity model. Two active SharedCapacityIdentity rows for the same
-- person would split that mutex and permit the same human to be booked through
-- different roots. Organization identities may legitimately own multiple
-- independent logical capacities, so this restriction is person-specific.
CREATE FUNCTION request_engine.guard_person_shared_capacity_cardinality()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_identity_kind text;
    v_identity_status text;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT identity_kind, status
      INTO v_identity_kind, v_identity_status
      FROM request_engine.global_identities
     WHERE id = NEW.global_identity_id
     FOR UPDATE;

    IF NOT FOUND OR v_identity_status <> 'active' THEN
        RAISE EXCEPTION 'SharedCapacityIdentity requires an active GlobalIdentity'
            USING ERRCODE = '22023';
    END IF;

    IF v_identity_kind = 'person' AND EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_identities existing
         WHERE existing.global_identity_id = NEW.global_identity_id
           AND existing.status = 'active'
           AND existing.id <> NEW.id
    ) THEN
        RAISE EXCEPTION 'person GlobalIdentity already has an active SharedCapacityIdentity'
            USING ERRCODE = '23505';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER shared_capacity_identities_guard_person_cardinality
BEFORE INSERT OR UPDATE OF global_identity_id, status
ON request_engine.shared_capacity_identities
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_person_shared_capacity_cardinality();

REVOKE ALL ON FUNCTION request_engine.guard_person_shared_capacity_cardinality()
    FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
