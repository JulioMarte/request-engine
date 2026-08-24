"""Close final F2 SECURITY DEFINER and taxonomy provenance boundaries.

Revision ID: 0013_f2_authority_boundary_hardening
Revises: 0012_f2_public_projection_hardening
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_f2_authority_boundary_hardening"
down_revision: str | Sequence[str] | None = "0012_f2_public_projection_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.search_discovery_candidates_v2(
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
    mapping_id uuid,
    mapping_revision bigint,
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
    location_address_line1 text,
    location_address_line2 text,
    location_locality text,
    location_administrative_area text,
    location_postal_code text,
    location_country_code text,
    resource_id uuid,
    provider_visibility text,
    provider_key text,
    provider_display_name text,
    provider_role_label text,
    provider_profile_image_ref text,
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
    IF p_classification_key IS NULL
       OR p_origin_latitude IS NULL
       OR p_origin_longitude IS NULL
       OR p_radius_meters IS NULL
       OR p_window_start IS NULL
       OR p_window_end IS NULL
       OR p_limit IS NULL
       OR p_classification_key !~ '^[a-z0-9]+(_[a-z0-9]+)*$'
       OR p_origin_latitude NOT BETWEEN -90 AND 90
       OR p_origin_longitude NOT BETWEEN -180 AND 180
       OR p_radius_meters NOT BETWEEN 1 AND 100000
       OR p_window_end <= p_window_start
       OR p_window_end - p_window_start > interval '7 days'
       OR p_limit NOT BETWEEN 1 AND 201 THEN
        RAISE EXCEPTION 'invalid discovery search contract' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH eligible AS (
        SELECT
            dp.id AS publication_id,
            dp.revision AS publication_revision,
            map.id AS mapping_id,
            map.revision AS mapping_revision,
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
            l.address_line1 AS location_address_line1,
            l.address_line2 AS location_address_line2,
            l.locality AS location_locality,
            l.administrative_area AS location_administrative_area,
            l.postal_code AS location_postal_code,
            l.country_code AS location_country_code,
            dp.resource_id,
            dp.provider_visibility,
            CASE WHEN dp.provider_visibility = 'public'
                THEN r.resource_key END AS provider_key,
            CASE WHEN dp.provider_visibility = 'public'
                THEN rpp.display_name END AS provider_display_name,
            CASE WHEN dp.provider_visibility = 'public'
                THEN rpp.role_label END AS provider_role_label,
            CASE WHEN dp.provider_visibility = 'public'
                THEN rpp.profile_image_ref END AS provider_profile_image_ref,
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
        LEFT JOIN request_engine.resource_public_profiles rpp
          ON rpp.organization_id = dp.organization_id
         AND rpp.resource_id = dp.resource_id
         AND rpp.active
        WHERE dp.status = 'active'
          AND dp.effective_during && tstzrange(p_window_start, p_window_end, '[)')
          AND (dp.resource_id IS NULL OR r.active)
          AND (
              dp.provider_visibility = 'hidden'
              OR (rpp.resource_id IS NOT NULL AND rpp.display_name IS NOT NULL)
          )
    )
    SELECT e.*
      FROM eligible e
     WHERE e.distance_meters <= p_radius_meters
     ORDER BY
        e.distance_meters,
        e.organization_id,
        e.location_id,
        e.offering_id,
        e.publication_id
     LIMIT p_limit;
END
$function$;

REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM PUBLIC, request_engine_app, request_engine_worker;
GRANT EXECUTE ON FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) TO request_engine_discovery;

RESET ROLE;
ALTER FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) OWNER TO request_engine_admin;

REVOKE ALL ON TABLE request_engine.service_classification_authority_events
FROM
    PUBLIC,
    request_engine_app,
    request_engine_worker,
    request_engine_discovery,
    request_engine_admin;
GRANT SELECT ON TABLE request_engine.service_classification_authority_events
TO request_engine_admin;

RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0013 preserves final F2 authority-boundary hardening")
