\set ON_ERROR_STOP on
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_app') THEN CREATE ROLE request_e2e_app LOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_worker') THEN CREATE ROLE request_e2e_worker LOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_read') THEN CREATE ROLE request_e2e_read LOGIN; END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='request_e2e_control') THEN CREATE ROLE request_e2e_control LOGIN; END IF;
END $$;
GRANT request_engine_app TO request_e2e_app;
GRANT request_engine_worker TO request_e2e_worker;
GRANT request_platform_control TO request_e2e_control;
GRANT EXECUTE ON FUNCTION request_platform.read_principal_authority(uuid) TO request_e2e_read;
GRANT EXECUTE ON FUNCTION request_platform.read_platform_provisioners(uuid,uuid,integer) TO request_e2e_read;
GRANT EXECUTE ON FUNCTION request_platform.read_identity_recovery_cases(uuid,uuid,integer) TO request_e2e_read;
GRANT EXECUTE ON FUNCTION request_platform.read_native_identities(uuid,uuid,integer) TO request_e2e_read;
