"""Add F2 opaque discovery-to-booking handoff and runtime role.

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

_ROLE_SQL = r"""
RESET ROLE;
DO $block$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'request_engine_discovery') THEN
        CREATE ROLE request_engine_discovery NOLOGIN NOBYPASSRLS;
    END IF;
END
$block$;
"""

_SCHEMA_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

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
GRANT ALL PRIVILEGES ON TABLE request_engine.discovery_booking_handoffs
TO request_engine_admin;
GRANT USAGE ON SCHEMA request_engine TO request_engine_discovery;

CREATE OR REPLACE FUNCTION request_engine.guard_f2_publication_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id <> NEW.organization_id
       OR OLD.offering_id <> NEW.offering_id
       OR OLD.location_id <> NEW.location_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.effective_during <> NEW.effective_during
       OR OLD.provider_visibility <> NEW.provider_visibility THEN
        RAISE EXCEPTION 'DiscoveryPublication scope/effective interval/visibility is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked DiscoveryPublication cannot be reactivated'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE FUNCTION request_engine.guard_f2_publication_broad_specific_overlap()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_lock_key bigint;
BEGIN
    v_lock_key := hashtextextended(
        NEW.organization_id::text || ':' || NEW.offering_id::text || ':' || NEW.location_id::text,
        0
    );
    PERFORM pg_advisory_xact_lock(v_lock_key);
    IF NEW.status = 'active' AND EXISTS (
        SELECT 1
          FROM request_engine.discovery_publications p
         WHERE p.organization_id = NEW.organization_id
           AND p.offering_id = NEW.offering_id
           AND p.location_id = NEW.location_id
           AND p.id <> NEW.id
           AND p.status = 'active'
           AND p.effective_during && NEW.effective_during
           AND (p.resource_id IS NULL OR NEW.resource_id IS NULL)
    ) THEN
        RAISE EXCEPTION 'broad and resource-specific discovery publications cannot overlap'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER discovery_publications_broad_specific_guard
BEFORE INSERT OR UPDATE ON request_engine.discovery_publications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f2_publication_broad_specific_overlap();

CREATE FUNCTION request_engine.lookup_active_service_classification(p_key text)
RETURNS TABLE (id uuid, classification_key text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
    SELECT sc.id, sc.classification_key
      FROM request_engine.service_classifications sc
     WHERE sc.classification_key = p_key
       AND sc.status = 'active'
$function$;
REVOKE ALL ON FUNCTION request_engine.lookup_active_service_classification(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.lookup_active_service_classification(text)
TO request_engine_app;
REVOKE SELECT ON TABLE request_engine.service_classifications FROM request_engine_app;

RESET ROLE;
RESET search_path;
"""

_PRIVILEGED_SQL = r"""
CREATE FUNCTION request_engine.search_discovery_candidates_v2(
    p_classification_key text,
    p_origin_latitude double precision,
    p_origin_longitude double precision,
    p_radius_meters integer,
    p_window_start timestamptz,
    p_window_end timestamptz,
    p_limit integer
)
RETURNS TABLE (
    publication_id uuid,
    publication_revision bigint,
    organization_id uuid,
    organization_key text,
    organization_display_name text,
    offering_id uuid,
    offering_key text,
    offering_display_name text,
    offering_version_id uuid,
    location_id uuid,
    location_key text,
    location_display_name text,
    resource_id uuid,
    provider_visibility text,
    publication_start timestamptz,
    publication_end timestamptz,
    distance_meters double precision
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
BEGIN
    IF p_classification_key !~ '^[a-z0-9]+(_[a-z0-9]+)*$'
       OR p_origin_latitude NOT BETWEEN -90 AND 90
       OR p_origin_longitude NOT BETWEEN -180 AND 180
       OR p_radius_meters NOT BETWEEN 1 AND 100000
       OR p_window_end <= p_window_start
       OR p_window_end - p_window_start > interval '7 days'
       OR p_limit NOT BETWEEN 1 AND 501 THEN
        RAISE EXCEPTION 'invalid discovery search contract' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH eligible AS (
        SELECT
            dp.id AS publication_id,
            dp.revision AS publication_revision,
            org.id AS organization_id,
            org.organization_key,
            org.display_name AS organization_display_name,
            o.id AS offering_id,
            o.offering_key,
            o.display_name AS offering_display_name,
            latest.id AS offering_version_id,
            l.id AS location_id,
            l.location_key,
            l.display_name AS location_display_name,
            dp.resource_id,
            dp.provider_visibility,
            lower(dp.effective_during) AS publication_start,
            upper(dp.effective_during) AS publication_end,
            6371008.8 * 2 * asin(sqrt(LEAST(1.0, GREATEST(0.0,
                power(sin(radians((l.latitude::double precision - p_origin_latitude) / 2)), 2)
                + cos(radians(p_origin_latitude))
                * cos(radians(l.latitude::double precision))
                * power(sin(radians((l.longitude::double precision - p_origin_longitude) / 2)), 2)
            )))) AS distance_meters
        FROM request_engine.discovery_publications dp
        JOIN request_engine.offering_service_classifications map
          ON map.organization_id = dp.organization_id
         AND map.offering_id = dp.offering_id
         AND map.status = 'active'
        JOIN request_engine.service_classifications sc
          ON sc.id = map.service_classification_id
         AND sc.status = 'active'
         AND sc.classification_key = p_classification_key
        JOIN request_engine.organizations org
          ON org.id = dp.organization_id
         AND org.operational_status = 'active'
        JOIN request_engine.offerings o
          ON o.organization_id = dp.organization_id
         AND o.id = dp.offering_id
         AND o.active
        JOIN LATERAL (
            SELECT ov.id, ov.bookable
              FROM request_engine.offering_versions ov
             WHERE ov.organization_id = o.organization_id
               AND ov.offering_id = o.id
             ORDER BY ov.version DESC
             LIMIT 1
        ) latest ON latest.bookable
        JOIN request_engine.locations l
          ON l.organization_id = dp.organization_id
         AND l.id = dp.location_id
         AND l.active
         AND l.latitude IS NOT NULL
         AND l.longitude IS NOT NULL
        LEFT JOIN request_engine.resources r
          ON r.organization_id = dp.organization_id
         AND r.id = dp.resource_id
        WHERE dp.status = 'active'
          AND dp.effective_during && tstzrange(p_window_start, p_window_end, '[)')
          AND (dp.resource_id IS NULL OR r.active)
    )
    SELECT e.*
      FROM eligible e
     WHERE e.distance_meters <= p_radius_meters
     ORDER BY e.distance_meters, e.organization_id, e.location_id, e.offering_id, e.publication_id
     LIMIT p_limit;
END
$function$;

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
    v_start timestamptz;
    v_end timestamptz;
    v_id uuid;
BEGIN
    IF p_token_hash !~ '^[0-9a-f]{64}$' OR jsonb_typeof(p_selection) <> 'object' THEN
        RAISE EXCEPTION 'invalid discovery handoff payload' USING ERRCODE = '22023';
    END IF;
    IF p_expires_at <= clock_timestamp()
       OR p_expires_at > clock_timestamp() + interval '15 minutes' THEN
        RAISE EXCEPTION 'invalid discovery handoff expiry' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_start := (p_selection->>'start_at')::timestamptz;
        v_end := (p_selection->>'end_at')::timestamptz;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'invalid discovery handoff interval' USING ERRCODE = '22023';
    END;
    IF v_end <= v_start THEN
        RAISE EXCEPTION 'invalid discovery handoff interval' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_publication
      FROM request_engine.discovery_publications
     WHERE id = p_publication_id
       AND status = 'active'
       AND revision = p_expected_publication_revision
       AND tstzrange(v_start, v_end, '[)') <@ effective_during
     FOR SHARE;
    IF NOT FOUND OR v_publication.location_id <> p_location_id THEN
        RAISE EXCEPTION 'discovery publication unavailable' USING ERRCODE = '40001';
    END IF;
    IF v_publication.resource_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_selection->'resources') item
         WHERE item->>'resource_id' = v_publication.resource_id::text
    ) THEN
        RAISE EXCEPTION 'discovery selection escaped publication scope' USING ERRCODE = '23514';
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
        v_handoff_id := NULLIF(
            current_setting('request_engine.discovery_handoff_id', true), ''
        )::uuid;
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
       AND NEW.during <@ effective_during
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

ALTER FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) OWNER TO request_engine_admin;
ALTER FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, uuid, jsonb, timestamptz
) OWNER TO request_engine_admin;
ALTER FUNCTION request_engine.read_discovery_booking_handoff(text)
    OWNER TO request_engine_admin;
ALTER FUNCTION request_engine.guard_discovery_handoff_reservation()
    OWNER TO request_engine_admin;

REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, uuid, jsonb, timestamptz
) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.read_discovery_booking_handoff(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_discovery_handoff_reservation() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.guard_f2_publication_broad_specific_overlap() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) TO request_engine_discovery;
GRANT EXECUTE ON FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, uuid, jsonb, timestamptz
) TO request_engine_discovery;
GRANT EXECUTE ON FUNCTION request_engine.read_discovery_booking_handoff(text)
TO request_engine_app;
GRANT EXECUTE ON FUNCTION request_engine.guard_discovery_handoff_reservation()
TO request_engine_schema_owner;
REVOKE EXECUTE ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM request_engine_app;

SET ROLE request_engine_schema_owner;
CREATE TRIGGER reservations_guard_discovery_handoff
BEFORE INSERT ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_discovery_handoff_reservation();
RESET ROLE;
"""


def upgrade() -> None:
    op.execute(_ROLE_SQL)
    op.execute(_SCHEMA_SQL)
    op.execute(_PRIVILEGED_SQL)


def downgrade() -> None:
    raise RuntimeError("0006 preserves F2 opaque handoff and least-privilege boundary")
