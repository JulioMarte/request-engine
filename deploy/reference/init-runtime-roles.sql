\set ON_ERROR_STOP on
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_app') THEN CREATE ROLE request_e2e_app LOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_worker') THEN CREATE ROLE request_e2e_worker LOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_read') THEN CREATE ROLE request_e2e_read LOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_control') THEN CREATE ROLE request_e2e_control LOGIN; END IF;
END $$;
GRANT request_app TO request_e2e_app;
GRANT request_worker TO request_e2e_worker;
GRANT request_read TO request_e2e_read;
GRANT request_platform_control TO request_e2e_control;
