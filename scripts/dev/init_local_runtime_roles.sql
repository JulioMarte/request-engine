-- Development-only runtime logins for running the REAL control plane locally.
--
-- NOT for production. These are throwaway local passwords. Production uses the
-- deployment secret manager; this file only exists so a developer can start
-- request_engine.bootstrap.platform_server against a local PostgreSQL 18.
--
-- The baseline migration already created the managed group roles
-- (request_engine_app, request_platform_control, ...) with no logins. This file
-- creates three LOGIN wrappers and grants exactly the surface the control plane
-- verifies at startup (see bootstrap/platform_server.py::_verify_login).
--
-- Apply with:  psql "$MIGRATION_DATABASE_URL" -f scripts/dev/init_local_runtime_roles.sql
-- (as the database owner / superuser). Idempotent.
\set ON_ERROR_STOP on

DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 're_dev_app') THEN
    CREATE ROLE re_dev_app LOGIN PASSWORD 'dev-app-only';
  ELSE
    ALTER ROLE re_dev_app PASSWORD 'dev-app-only';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 're_dev_read') THEN
    CREATE ROLE re_dev_read LOGIN PASSWORD 'dev-read-only';
  ELSE
    ALTER ROLE re_dev_read PASSWORD 'dev-read-only';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 're_dev_control') THEN
    CREATE ROLE re_dev_control LOGIN PASSWORD 'dev-control-only';
  ELSE
    ALTER ROLE re_dev_control PASSWORD 'dev-control-only';
  END IF;
END
$do$;

GRANT request_engine_app TO re_dev_app;
GRANT request_platform_control TO re_dev_control;
GRANT USAGE ON SCHEMA request_platform TO re_dev_read, re_dev_control;

GRANT EXECUTE ON FUNCTION request_platform.read_principal_authority(uuid) TO re_dev_read;
GRANT EXECUTE ON FUNCTION request_platform.read_platform_provisioners(uuid, uuid, integer) TO re_dev_read;
GRANT EXECUTE ON FUNCTION request_platform.read_identity_recovery_cases(uuid, uuid, integer) TO re_dev_read;
GRANT EXECUTE ON FUNCTION request_platform.read_native_identities(uuid, uuid, integer) TO re_dev_read;
GRANT EXECUTE ON FUNCTION request_platform.read_platform_configuration_revisions(text) TO re_dev_read;
GRANT EXECUTE ON FUNCTION request_platform.read_platform_secret_binding(uuid) TO re_dev_read;
GRANT EXECUTE ON FUNCTION request_platform.read_platform_readiness() TO re_dev_read;
