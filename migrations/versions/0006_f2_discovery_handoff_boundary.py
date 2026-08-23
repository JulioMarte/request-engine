"""Add opaque F2 discovery-to-booking handoff and least-privilege read role.

Revision ID: 0006_f2_handoff
Revises: 0005_f2_discovery_hardening
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_f2_handoff"
down_revision: str | Sequence[str] | None = "0005_f2_discovery_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

DO $block$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_discovery') THEN
        CREATE ROLE request_engine_discovery NOLOGIN NOBYPASSRLS;
    END IF;
END
$block$;

CREATE TABLE request_engine.discovery_booking_handoffs (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    token_hash text NOT NULL UNIQUE,
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    publication_id uuid NOT NULL,
    publication_revision bigint NOT NULL,
    mapping_id uuid NOT NULL,
    mapping_revision bigint NOT NULL,
    offering_version_id uuid NOT NULL,
    location_id uuid NOT NULL,
    selection jsonb NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_reservation_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, publication_id)
        REFERENCES request_engine.discovery_publications (organization_id, id),
    FOREIGN KEY (organization_id, mapping_id)
        REFERENCES request_engine.offering_service_classifications (organization_id, id),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CHECK (publication_revision > 0),
    CHECK (mapping_revision > 0),
    CHECK (jsonb_typeof(selection) = 'object')
);
CREATE INDEX discovery_booking_handoffs_expiry_idx
    ON request_engine.discovery_booking_handoffs (expires_at)
    WHERE consumed_reservation_id IS NULL;

ALTER TABLE request_engine.discovery_booking_handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.discovery_booking_handoffs FORCE ROW LEVEL SECURITY;
CREATE POLICY discovery_booking_handoffs_tenant_policy
    ON request_engine.discovery_booking_handoffs
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON TABLE request_engine.discovery_booking_handoffs FROM PUBLIC;
REVOKE ALL ON TABLE request_engine.discovery_booking_handoffs
    FROM request_engine_app, request_engine_worker, request_engine_discovery;
GRANT ALL PRIVILEGES ON TABLE request_engine.discovery_booking_handoffs TO request_engine_admin;

CREATE FUNCTION request_engine.issue_discovery_booking_handoff(
    p_token_hash text,
    p_publication_id uuid,
    p_expected_publication_revision bigint,
    p_offering_version_id uuid,
    p_location_id uuid,
    p_selection jsonb,
    p_expires_at timestamptz
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_publication request_engine.discovery_publications%ROWTYPE;
    v_mapping request_engine.offering_service_classifications%ROWTYPE;
    v_id uuid;
BEGIN
    IF p_token_hash !~ '^[0-9a-f]{64}$' OR jsonb_typeof(p_selection) <> 'object' THEN
        RAISE EXCEPTION 'invalid discovery handoff payload' USING ERRCODE = '22023';
    END IF;
    IF p_expires_at <= clock_timestamp() OR p_expires_at > clock_timestamp() + interval '15 minutes' THEN
        RAISE EXCEPTION 'invalid discovery handoff expiry' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_publication
      FROM request_engine.discovery_publications
     WHERE id = p_publication_id
       AND status = 'active'
       AND revision = p_expected_publication_revision
       AND effective_during @> clock_timestamp()
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery publication unavailable' USING ERRCODE = '40001';
    END IF;
    IF v_publication.location_id <> p_location_id THEN
        RAISE EXCEPTION 'discovery publication scope changed' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_mapping
      FROM request_engine.offering_service_classifications
     WHERE organization_id = v_publication.organization_id
       AND offering_id = v_publication.offering_id
       AND status = 'active'
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery mapping unavailable' USING ERRCODE = '40001';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM request_engine.offering_versions ov
         WHERE ov.organization_id = v_publication.organization_id
           AND ov.offering_id = v_publication.offering_id
           AND ov.id = p_offering_version_id
           AND ov.bookable
    ) THEN
        RAISE EXCEPTION 'offering version unavailable' USING ERRCODE = '40001';
    END IF;

    INSERT INTO request_engine.discovery_booking_handoffs (
        token_hash, organization_id, publication_id, publication_revision,
        mapping_id, mapping_revision, offering_version_id, location_id,
        selection, expires_at
    ) VALUES (
        p_token_hash, v_publication.organization_id, v_publication.id, v_publication.revision,
        v_mapping.id, v_mapping.revision, p_offering_version_id, p_location_id,
        p_selection, p_expires_at
    ) RETURNING id INTO v_id;
    RETURN v_id;
END
$function$;

CREATE FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text)
RETURNS TABLE (handoff_id uuid, organization_id uuid, selection jsonb)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
    SELECT h.id, h.organization_id, h.selection
      FROM request_engine.discovery_booking_handoffs h
     WHERE h.token_hash = p_token_hash
       AND h.organization_id = request_engine.current_organization_id()
       AND h.expires_at > clock_timestamp()
       AND h.consumed_reservation_id IS NULL
$function$;

CREATE FUNCTION request_engine.guard_discovery_handoff_reservation()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_handoff_id uuid;
    v_handoff request_engine.discovery_booking_handoffs%ROWTYPE;
    v_publication request_engine.discovery_publications%ROWTYPE;
    v_mapping request_engine.offering_service_classifications%ROWTYPE;
BEGIN
    BEGIN
        v_handoff_id := NULLIF(current_setting('request_engine.discovery_handoff_id', true), '')::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid discovery handoff context' USING ERRCODE = '22023';
    END;
    IF v_handoff_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_handoff
      FROM request_engine.discovery_booking_handoffs
     WHERE id = v_handoff_id
       AND organization_id = NEW.organization_id
     FOR UPDATE;
    IF NOT FOUND OR v_handoff.expires_at <= clock_timestamp()
       OR v_handoff.consumed_reservation_id IS NOT NULL THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_mapping
      FROM request_engine.offering_service_classifications
     WHERE organization_id = v_handoff.organization_id
       AND id = v_handoff.mapping_id
       AND status = 'active'
       AND revision = v_handoff.mapping_revision
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_publication
      FROM request_engine.discovery_publications
     WHERE organization_id = v_handoff.organization_id
       AND id = v_handoff.publication_id
       AND status = 'active'
       AND revision = v_handoff.publication_revision
       AND effective_during @> lower(NEW.during)
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    IF NEW.offering_version_id <> v_handoff.offering_version_id
       OR NEW.location_id IS DISTINCT FROM v_handoff.location_id
       OR lower(NEW.during) <> (v_handoff.selection->>'start_at')::timestamptz
       OR upper(NEW.during) <> (v_handoff.selection->>'end_at')::timestamptz THEN
        RAISE EXCEPTION 'discovery option does not match Reservation' USING ERRCODE = '23514';
    END IF;

    UPDATE request_engine.discovery_booking_handoffs
       SET consumed_reservation_id = NEW.id
     WHERE id = v_handoff.id;
    RETURN NEW;
END
$function$;

CREATE TRIGGER reservations_guard_discovery_handoff
BEFORE INSERT ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_discovery_handoff_reservation();

REVOKE ALL ON FUNCTION
    request_engine.issue_discovery_booking_handoff(text, uuid, bigint, uuid, uuid, jsonb, timestamptz),
    request_engine.read_discovery_booking_handoff(text),
    request_engine.guard_discovery_handoff_reservation()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION
    request_engine.issue_discovery_booking_handoff(text, uuid, bigint, uuid, uuid, jsonb, timestamptz)
TO request_engine_discovery;
GRANT EXECUTE ON FUNCTION request_engine.read_discovery_booking_handoff(text)
TO request_engine_app;

REVOKE EXECUTE ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM request_engine_app;
GRANT EXECUTE ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) TO request_engine_discovery;

REVOKE SELECT ON TABLE request_engine.service_classifications FROM request_engine_app;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0006 preserves F2 opaque handoff and least-privilege boundary")
