"""Add F2 geospatial cross-tenant discovery.

Revision ID: 0004_f2_discovery
Revises: 0003_f1_runtime_acl
Create Date: 2026-08-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_f2_discovery"
down_revision: str | Sequence[str] | None = "0003_f1_runtime_acl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE TABLE request_engine.service_classifications (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    classification_key text NOT NULL UNIQUE,
    canonical_name text NOT NULL,
    status text NOT NULL DEFAULT 'active',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (classification_key ~ '^[a-z0-9]+(_[a-z0-9]+)*$'),
    CHECK (btrim(canonical_name) <> ''),
    CHECK (status IN ('active', 'retired')),
    CHECK (revision > 0)
);

CREATE TABLE request_engine.service_classification_authority_events (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    service_classification_id uuid NOT NULL
        REFERENCES request_engine.service_classifications(id),
    action text NOT NULL,
    authority_ref text NOT NULL,
    reason text NOT NULL,
    database_session_user text NOT NULL DEFAULT session_user,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (action IN ('created', 'retired')),
    CHECK (btrim(authority_ref) <> ''),
    CHECK (btrim(reason) <> '')
);

CREATE TABLE request_engine.offering_service_classifications (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    offering_id uuid NOT NULL,
    service_classification_id uuid NOT NULL
        REFERENCES request_engine.service_classifications(id),
    status text NOT NULL DEFAULT 'active',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, offering_id)
        REFERENCES request_engine.offerings (organization_id, id),
    CHECK (status IN ('active', 'revoked')),
    CHECK (revision > 0)
);
CREATE UNIQUE INDEX offering_service_classifications_one_active_idx
    ON request_engine.offering_service_classifications (organization_id, offering_id)
    WHERE status = 'active';
CREATE INDEX offering_service_classifications_lookup_idx
    ON request_engine.offering_service_classifications
       (service_classification_id, status, organization_id, offering_id);

CREATE TABLE request_engine.discovery_publications (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    offering_id uuid NOT NULL,
    location_id uuid NOT NULL,
    resource_id uuid,
    effective_during tstzrange NOT NULL,
    status text NOT NULL DEFAULT 'active',
    provider_visibility text NOT NULL DEFAULT 'hidden',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, offering_id)
        REFERENCES request_engine.offerings (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    CHECK (NOT isempty(effective_during)),
    CHECK (lower(effective_during) IS NOT NULL),
    CHECK (lower_inc(effective_during) AND NOT upper_inc(effective_during)),
    CHECK (status IN ('active', 'revoked')),
    CHECK (provider_visibility IN ('hidden', 'public')),
    CHECK (revision > 0),
    CONSTRAINT discovery_publications_no_active_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            offering_id WITH =,
            location_id WITH =,
            (COALESCE(resource_id, '00000000-0000-0000-0000-000000000000'::uuid)) WITH =,
            effective_during WITH &&
        ) WHERE (status = 'active')
);
CREATE INDEX discovery_publications_lookup_idx
    ON request_engine.discovery_publications
       (organization_id, offering_id, location_id, status);

CREATE FUNCTION request_engine.guard_f2_mapping_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id <> NEW.organization_id OR OLD.offering_id <> NEW.offering_id THEN
        RAISE EXCEPTION 'OfferingServiceClassification scope cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked OfferingServiceClassification cannot be reactivated'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE FUNCTION request_engine.guard_f2_publication_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id <> NEW.organization_id
       OR OLD.offering_id <> NEW.offering_id
       OR OLD.location_id <> NEW.location_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.effective_during <> NEW.effective_during THEN
        RAISE EXCEPTION 'DiscoveryPublication scope/effective interval cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked DiscoveryPublication cannot be reactivated'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER service_classifications_revision_step
BEFORE UPDATE ON request_engine.service_classifications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f1_exact_revision_step();
CREATE TRIGGER service_classifications_touch
BEFORE UPDATE ON request_engine.service_classifications
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER service_classification_authority_events_append_only
BEFORE UPDATE OR DELETE ON request_engine.service_classification_authority_events
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();
CREATE TRIGGER offering_service_classifications_lifecycle
BEFORE UPDATE ON request_engine.offering_service_classifications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f2_mapping_lifecycle();
CREATE TRIGGER offering_service_classifications_revision_step
BEFORE UPDATE ON request_engine.offering_service_classifications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f1_exact_revision_step();
CREATE TRIGGER offering_service_classifications_touch
BEFORE UPDATE ON request_engine.offering_service_classifications
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER discovery_publications_lifecycle
BEFORE UPDATE ON request_engine.discovery_publications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f2_publication_lifecycle();
CREATE TRIGGER discovery_publications_revision_step
BEFORE UPDATE ON request_engine.discovery_publications
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f1_exact_revision_step();
CREATE TRIGGER discovery_publications_touch
BEFORE UPDATE ON request_engine.discovery_publications
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

ALTER TABLE request_engine.offering_service_classifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.offering_service_classifications FORCE ROW LEVEL SECURITY;
CREATE POLICY offering_service_classifications_tenant_policy
    ON request_engine.offering_service_classifications
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.discovery_publications ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.discovery_publications FORCE ROW LEVEL SECURITY;
CREATE POLICY discovery_publications_tenant_policy
    ON request_engine.discovery_publications
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON TABLE
    request_engine.service_classifications,
    request_engine.service_classification_authority_events,
    request_engine.offering_service_classifications,
    request_engine.discovery_publications
FROM PUBLIC;
GRANT SELECT ON TABLE request_engine.service_classifications TO request_engine_app;
GRANT SELECT, INSERT, UPDATE ON TABLE
    request_engine.offering_service_classifications,
    request_engine.discovery_publications
TO request_engine_app;
GRANT ALL PRIVILEGES ON TABLE
    request_engine.service_classifications,
    request_engine.service_classification_authority_events,
    request_engine.offering_service_classifications,
    request_engine.discovery_publications
TO request_engine_admin;
REVOKE ALL ON TABLE
    request_engine.service_classifications,
    request_engine.service_classification_authority_events,
    request_engine.offering_service_classifications,
    request_engine.discovery_publications
FROM request_engine_worker;

REVOKE ALL ON FUNCTION
    request_engine.guard_f2_mapping_lifecycle(),
    request_engine.guard_f2_publication_lifecycle()
FROM PUBLIC;

RESET ROLE;
RESET search_path;
"""

_ADMIN_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_admin, request_engine, pg_catalog;

CREATE FUNCTION request_admin.create_service_classification(
    p_classification_key text,
    p_canonical_name text,
    p_authority_ref text,
    p_reason text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_id uuid;
BEGIN
    IF btrim(COALESCE(p_authority_ref, '')) = '' OR btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'authority_ref and reason are required' USING ERRCODE = '22023';
    END IF;
    INSERT INTO request_engine.service_classifications (classification_key, canonical_name)
    VALUES (p_classification_key, p_canonical_name)
    RETURNING id INTO v_id;
    INSERT INTO request_engine.service_classification_authority_events (
        service_classification_id, action, authority_ref, reason
    ) VALUES (v_id, 'created', p_authority_ref, p_reason);
    RETURN v_id;
END
$function$;

CREATE FUNCTION request_admin.retire_service_classification(
    p_service_classification_id uuid,
    p_expected_revision bigint,
    p_authority_ref text,
    p_reason text
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_revision bigint;
    v_status text;
BEGIN
    IF btrim(COALESCE(p_authority_ref, '')) = '' OR btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'authority_ref and reason are required' USING ERRCODE = '22023';
    END IF;
    SELECT revision, status INTO v_revision, v_status
      FROM request_engine.service_classifications
     WHERE id = p_service_classification_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceClassification not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status <> 'active' OR v_revision <> p_expected_revision THEN
        RAISE EXCEPTION 'ServiceClassification revision/status conflict' USING ERRCODE = '40001';
    END IF;
    IF EXISTS (
        SELECT 1 FROM request_engine.offering_service_classifications
         WHERE service_classification_id = p_service_classification_id
           AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'active Offering mappings still reference ServiceClassification'
            USING ERRCODE = '55000';
    END IF;
    UPDATE request_engine.service_classifications
       SET status = 'retired', revision = revision + 1
     WHERE id = p_service_classification_id
     RETURNING revision INTO v_revision;
    INSERT INTO request_engine.service_classification_authority_events (
        service_classification_id, action, authority_ref, reason
    ) VALUES (p_service_classification_id, 'retired', p_authority_ref, p_reason);
    RETURN v_revision;
END
$function$;

REVOKE ALL ON FUNCTION
    request_admin.create_service_classification(text, text, text, text),
    request_admin.retire_service_classification(uuid, bigint, text, text)
FROM PUBLIC;

RESET ROLE;
RESET search_path;

ALTER FUNCTION request_admin.create_service_classification(text, text, text, text)
    OWNER TO request_engine_admin;
ALTER FUNCTION request_admin.retire_service_classification(uuid, bigint, text, text)
    OWNER TO request_engine_admin;
GRANT EXECUTE ON FUNCTION
    request_admin.create_service_classification(text, text, text, text),
    request_admin.retire_service_classification(uuid, bigint, text, text)
TO request_engine_admin;
"""

_READ_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE FUNCTION request_engine.search_discovery_candidates(
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
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine, pg_temp
AS $function$
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
            6371008.8 * 2 * asin(sqrt(
                power(sin(radians((l.latitude::double precision - p_origin_latitude) / 2)), 2)
                + cos(radians(p_origin_latitude))
                * cos(radians(l.latitude::double precision))
                * power(sin(radians((l.longitude::double precision - p_origin_longitude) / 2)), 2)
            )) AS distance_meters
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
            SELECT ov.id
            FROM request_engine.offering_versions ov
            WHERE ov.organization_id = o.organization_id
              AND ov.offering_id = o.id
              AND ov.bookable
            ORDER BY ov.version DESC
            LIMIT 1
        ) latest ON true
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
    SELECT *
    FROM eligible
    WHERE distance_meters <= p_radius_meters
    ORDER BY distance_meters, organization_id, location_id, offering_id, publication_id
    LIMIT p_limit
$function$;

REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM PUBLIC;

RESET ROLE;
RESET search_path;

ALTER FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) OWNER TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) TO request_engine_app;
"""


def upgrade() -> None:
    op.execute(_SCHEMA_SQL)
    op.execute(_ADMIN_SQL)
    op.execute(_READ_SQL)


def downgrade() -> None:
    raise RuntimeError("0004_f2_discovery contains durable F2 publication provenance")
