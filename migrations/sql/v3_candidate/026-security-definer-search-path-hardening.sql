BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = pg_catalog;

-- PostgreSQL's safe SECURITY DEFINER pattern puts pg_temp last so temporary
-- objects can never shadow trusted catalog/application objects.
DO $hardening$
DECLARE
    routine record;
BEGIN
    FOR routine IN
        SELECT n.nspname,
               p.proname,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments
        FROM pg_catalog.pg_proc AS p
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('request_engine', 'request_cmd', 'request_admin')
          AND p.prosecdef
          AND p.prokind = 'f'
        ORDER BY n.nspname, p.proname, p.oid
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %I.%I(%s) SET search_path = pg_catalog, request_engine, pg_temp',
            routine.nspname,
            routine.proname,
            routine.identity_arguments
        );
    END LOOP;
END
$hardening$;

RESET ROLE;
COMMIT;
