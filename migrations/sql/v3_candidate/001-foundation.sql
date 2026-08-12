BEGIN;

-- Request Engine V3 pre-baseline candidate.
-- This is intentionally a clean schema, not a compatibility delta over V2.

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_schema_owner') THEN
        CREATE ROLE request_engine_schema_owner NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_app') THEN
        CREATE ROLE request_engine_app NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_worker') THEN
        CREATE ROLE request_engine_worker NOLOGIN NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_admin') THEN
        CREATE ROLE request_engine_admin NOLOGIN BYPASSRLS;
    END IF;
END
$roles$;

ALTER ROLE request_engine_schema_owner NOLOGIN NOBYPASSRLS;
ALTER ROLE request_engine_app NOLOGIN NOBYPASSRLS;
ALTER ROLE request_engine_worker NOLOGIN NOBYPASSRLS;
ALTER ROLE request_engine_admin NOLOGIN BYPASSRLS;

CREATE SCHEMA request_engine AUTHORIZATION request_engine_schema_owner;
CREATE SCHEMA request_read AUTHORIZATION request_engine_schema_owner;
CREATE SCHEMA request_cmd AUTHORIZATION request_engine_schema_owner;
CREATE SCHEMA request_admin AUTHORIZATION request_engine_schema_owner;

REVOKE ALL ON SCHEMA request_engine FROM PUBLIC;
REVOKE ALL ON SCHEMA request_read FROM PUBLIC;
REVOKE ALL ON SCHEMA request_cmd FROM PUBLIC;
REVOKE ALL ON SCHEMA request_admin FROM PUBLIC;

SET ROLE request_engine_schema_owner;

CREATE FUNCTION request_engine.current_organization_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('request_engine.organization_id', true), '')::uuid
$function$;

CREATE FUNCTION request_engine.reject_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = '55000';
END
$function$;

CREATE FUNCTION request_engine.touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END
$function$;

RESET ROLE;

REVOKE ALL ON FUNCTION request_engine.current_organization_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.current_organization_id()
    TO request_engine_app, request_engine_worker, request_engine_admin;

GRANT USAGE ON SCHEMA request_engine, request_read, request_cmd
    TO request_engine_app, request_engine_worker;
GRANT USAGE ON SCHEMA request_engine, request_read, request_cmd, request_admin
    TO request_engine_admin;

COMMIT;
