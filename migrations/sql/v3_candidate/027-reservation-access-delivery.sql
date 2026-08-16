BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

ALTER TABLE request_engine.offering_versions
    ADD COLUMN delivery_policy jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE request_engine.offering_versions
    ADD CONSTRAINT offering_versions_delivery_policy_object_ck
    CHECK (jsonb_typeof(delivery_policy) = 'object');

CREATE TABLE request_engine.reservation_access (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    reservation_revision bigint NOT NULL,
    access_key text NOT NULL,
    kind text NOT NULL,
    provider_key text,
    materialization_key text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    access_uri text,
    external_ref text,
    public_data jsonb NOT NULL DEFAULT '{}'::jsonb,
    provisioned_at timestamptz,
    revoked_at timestamptz,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, reservation_id, reservation_revision, access_key),
    UNIQUE (organization_id, materialization_key),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    CHECK (reservation_revision > 0),
    CHECK (access_key <> ''),
    CHECK (materialization_key <> ''),
    CHECK (kind IN (
        'video_link',
        'phone',
        'physical_location',
        'instructions',
        'external_session'
    )),
    CHECK (status IN ('pending', 'ready', 'revoked')),
    CHECK (
        status <> 'ready'
        OR (
            provisioned_at IS NOT NULL
            AND (
                access_uri IS NOT NULL
                OR external_ref IS NOT NULL
                OR public_data <> '{}'::jsonb
            )
        )
    ),
    CHECK (status <> 'revoked' OR revoked_at IS NOT NULL),
    CHECK (status = 'revoked' OR revoked_at IS NULL),
    CHECK (jsonb_typeof(public_data) = 'object'),
    CHECK (revision > 0)
);

CREATE INDEX reservation_access_active_idx
    ON request_engine.reservation_access (
        organization_id,
        reservation_id,
        reservation_revision,
        access_key
    )
    WHERE status <> 'revoked';

CREATE TRIGGER reservation_access_touch
BEFORE UPDATE ON request_engine.reservation_access
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

ALTER TABLE request_engine.reservation_access ENABLE ROW LEVEL SECURITY;
CREATE POLICY reservation_access_tenant_isolation ON request_engine.reservation_access
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

CREATE VIEW request_read.reservation_access_v1
WITH (security_invoker = true)
AS
SELECT
    id,
    organization_id,
    reservation_id,
    reservation_revision,
    access_key,
    kind,
    provider_key,
    materialization_key,
    status,
    access_uri,
    external_ref,
    public_data,
    provisioned_at,
    revoked_at,
    revision,
    created_at,
    updated_at
FROM request_engine.reservation_access;

-- Domain handlers authenticate as request_engine_app. The function validates
-- both tenant context and the exact current Outbox lease before locking the
-- control-plane row in the same authoritative transaction as READY/REVOKED
-- publication. Provider I/O happens before this transaction and never under
-- this lock.
CREATE FUNCTION request_cmd.lock_outbox_message_claim(
    p_organization_id uuid,
    p_message_id uuid,
    p_claim_token uuid
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_found boolean;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT true
      INTO v_found
      FROM request_engine.outbox_messages
     WHERE organization_id = p_organization_id
       AND id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    RETURN COALESCE(v_found, false);
END
$function$;

REVOKE ALL ON request_engine.reservation_access FROM PUBLIC;
REVOKE ALL ON request_read.reservation_access_v1 FROM PUBLIC;
REVOKE ALL ON FUNCTION request_cmd.lock_outbox_message_claim(uuid, uuid, uuid)
    FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE ON request_engine.reservation_access
    TO request_engine_app;
GRANT ALL PRIVILEGES ON request_engine.reservation_access
    TO request_engine_admin;
GRANT SELECT ON request_read.reservation_access_v1
    TO request_engine_app, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_cmd.lock_outbox_message_claim(uuid, uuid, uuid)
    TO request_engine_app, request_engine_admin;

RESET search_path;
RESET ROLE;
COMMIT;
