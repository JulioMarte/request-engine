BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- The pre-RLS CapacityClaim guard must run for the actual application runtime
-- identity, including ordinary login roles that inherit request_engine_app. A
-- PostgreSQL superuser can satisfy pg_has_role(..., 'MEMBER') for roles it was
-- never intended to represent, and BYPASSRLS roles are explicitly trusted
-- maintenance/control-plane identities. Treating either as application runtime
-- causes false tenant-context failures during bootstrap/admin maintenance.
--
-- Keep the exact request_engine_app role covered because test/runtime sessions
-- may SET ROLE to the NOLOGIN group role itself. Inherited membership is only
-- considered runtime when the current role is neither superuser nor BYPASSRLS.
CREATE OR REPLACE FUNCTION request_engine.guard_capacity_claim_tenant_context()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_context_organization_id uuid;
    v_is_runtime_app boolean := false;
BEGIN
    IF current_user = 'request_engine_app' THEN
        v_is_runtime_app := true;
    ELSE
        SELECT
            pg_catalog.pg_has_role(current_user, 'request_engine_app', 'MEMBER')
            AND NOT role_row.rolsuper
            AND NOT role_row.rolbypassrls
          INTO v_is_runtime_app
          FROM pg_catalog.pg_roles AS role_row
         WHERE role_row.rolname = current_user;
    END IF;

    IF COALESCE(v_is_runtime_app, false) THEN
        v_context_organization_id := request_engine.current_organization_id();
        IF v_context_organization_id IS NULL
           OR NEW.organization_id IS DISTINCT FROM v_context_organization_id
        THEN
            RAISE EXCEPTION 'capacity claim organization context mismatch'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_tenant_context() FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
