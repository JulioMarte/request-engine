BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- PostgreSQL grants EXECUTE on newly created functions to PUBLIC by default.
-- V3 uses explicit runtime grants, so remove that implicit capability from all
-- application schemas and make the same rule apply to later candidate routines.
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_engine FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_read FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_cmd FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_admin FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_engine
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_read
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_cmd
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_admin
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

RESET search_path;
RESET ROLE;
COMMIT;
