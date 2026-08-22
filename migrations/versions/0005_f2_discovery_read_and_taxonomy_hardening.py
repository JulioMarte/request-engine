"""Harden F2 discovery read semantics and taxonomy administration.

Revision ID: 0005_f2_discovery_hardening
Revises: 0004_f2_discovery
Create Date: 2026-08-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_f2_discovery_hardening"
down_revision: str | Sequence[str] | None = "0004_f2_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HARDEN_SQL = r"""
-- Taxonomy changes must use the audited request_admin functions. The functions
-- are re-owned by the schema owner so request_engine_admin can remain SELECT-only
-- on the underlying taxonomy/evidence relations while retaining EXECUTE authority.
ALTER FUNCTION request_admin.create_service_classification(text, text, text, text)
    OWNER TO request_engine_schema_owner;
ALTER FUNCTION request_admin.retire_service_classification(uuid, bigint, text, text)
    OWNER TO request_engine_schema_owner;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE
    request_engine.service_classifications,
    request_engine.service_classification_authority_events
FROM request_engine_admin;
GRANT SELECT ON TABLE
    request_engine.service_classifications,
    request_engine.service_classification_authority_events
TO request_engine_admin;

CREATE OR REPLACE FUNCTION request_engine.search_discovery_candidates(
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
                power(sin(radians(
                    (l.latitude::double precision - p_origin_latitude) / 2
                )), 2)
                + cos(radians(p_origin_latitude))
                * cos(radians(l.latitude::double precision))
                * power(sin(radians(
                    (l.longitude::double precision - p_origin_longitude) / 2
                )), 2)
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
    SELECT *
    FROM eligible
    WHERE distance_meters <= p_radius_meters
    ORDER BY distance_meters, organization_id, location_id, offering_id, publication_id
    LIMIT p_limit
$function$;

ALTER FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) OWNER TO request_engine_admin;
REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) TO request_engine_app;
"""


def upgrade() -> None:
    op.execute(_HARDEN_SQL)


def downgrade() -> None:
    raise RuntimeError("0005 preserves F2 security and discovery semantic corrections")
