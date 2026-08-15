BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_admin, pg_catalog;

-- Reconcile the runtime table privilege contract after all current V3 candidate
-- tables and views exist. This remains additive until V3 freeze is proven.
-- Runtime roles intentionally do not receive DELETE. Worker state transitions
-- remain fenced semantic commands exposed through request_cmd functions.
REVOKE ALL ON ALL TABLES IN SCHEMA request_engine FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA request_read FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA request_admin FROM PUBLIC;
REVOKE DELETE ON ALL TABLES IN SCHEMA request_engine
    FROM request_engine_app, request_engine_worker;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA request_engine
    TO request_engine_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA request_engine
    TO request_engine_worker;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA request_engine
    TO request_engine_admin;

GRANT SELECT ON ALL TABLES IN SCHEMA request_read
    TO request_engine_app, request_engine_worker, request_engine_admin;
GRANT SELECT ON ALL TABLES IN SCHEMA request_admin
    TO request_engine_admin;

-- Prevent privilege drift for later candidate tables created by the schema owner.
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_engine
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_engine
    GRANT SELECT, INSERT, UPDATE ON TABLES
    TO request_engine_app;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_engine
    GRANT SELECT, INSERT, UPDATE ON TABLES
    TO request_engine_worker;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_engine
    GRANT ALL PRIVILEGES ON TABLES
    TO request_engine_admin;

ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_read
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_read
    GRANT SELECT ON TABLES
    TO request_engine_app, request_engine_worker, request_engine_admin;

ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_admin
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_admin
    GRANT SELECT ON TABLES
    TO request_engine_admin;

RESET search_path;
RESET ROLE;
COMMIT;
