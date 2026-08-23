"""Fence F2 handoff issuance to the exact discovery candidate observation.

Revision ID: 0009_f2_candidate_fence
Revises: 0008_f2_handoff_fence
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_f2_candidate_fence"
down_revision: str | Sequence[str] | None = "0008_f2_handoff_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
DROP FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
);

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
    IF p_classification_key !~ '^[a-z0-9]+(?:_[a-z0-9]+)*$'
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

ALTER FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) OWNER TO request_engine_admin;
REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.search_discovery_candidates_v2(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
) TO request_engine_discovery;

DROP FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, uuid, jsonb, timestamptz
);

CREATE FUNCTION request_engine.issue_discovery_booking_handoff(
    p_token_hash text,
    p_publication_id uuid,
    p_expected_publication_revision bigint,
    p_mapping_id uuid,
    p_expected_mapping_revision bigint,
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
    v_latest_version_id uuid;
    v_latest_bookable boolean;
    v_start timestamptz;
    v_end timestamptz;
    v_selection_offering_version uuid;
    v_selection_location uuid;
    v_id uuid;
BEGIN
    IF p_token_hash !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_selection) <> 'object'
       OR jsonb_typeof(p_selection->'resources') <> 'array'
       OR jsonb_array_length(p_selection->'resources') = 0 THEN
        RAISE EXCEPTION 'invalid discovery handoff payload' USING ERRCODE = '22023';
    END IF;
    IF p_expected_publication_revision < 1 OR p_expected_mapping_revision < 1 THEN
        RAISE EXCEPTION 'invalid discovery handoff observation' USING ERRCODE = '22023';
    END IF;
    IF p_expires_at <= clock_timestamp()
       OR p_expires_at > clock_timestamp() + interval '15 minutes' THEN
        RAISE EXCEPTION 'invalid discovery handoff expiry' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_start := (p_selection->>'start_at')::timestamptz;
        v_end := (p_selection->>'end_at')::timestamptz;
        v_selection_offering_version := (p_selection->>'offering_version_id')::uuid;
        v_selection_location := (p_selection->>'location_id')::uuid;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'invalid discovery handoff selection' USING ERRCODE = '22023';
    END;
    IF v_end <= v_start
       OR v_selection_offering_version <> p_offering_version_id
       OR v_selection_location <> p_location_id THEN
        RAISE EXCEPTION 'discovery handoff selection mismatch' USING ERRCODE = '22023';
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

    SELECT * INTO v_mapping
      FROM request_engine.offering_service_classifications
     WHERE organization_id = v_publication.organization_id
       AND offering_id = v_publication.offering_id
       AND id = p_mapping_id
       AND revision = p_expected_mapping_revision
       AND status = 'active'
     FOR SHARE;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1
          FROM request_engine.service_classifications sc
         WHERE sc.id = v_mapping.service_classification_id
           AND sc.status = 'active'
    ) THEN
        RAISE EXCEPTION 'discovery mapping unavailable' USING ERRCODE = '40001';
    END IF;

    SELECT ov.id, ov.bookable
      INTO v_latest_version_id, v_latest_bookable
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = v_publication.organization_id
       AND ov.offering_id = v_publication.offering_id
     ORDER BY ov.version DESC
     LIMIT 1;
    IF NOT FOUND OR v_latest_version_id <> p_offering_version_id OR NOT v_latest_bookable THEN
        RAISE EXCEPTION 'offering version unavailable' USING ERRCODE = '40001';
    END IF;

    IF v_publication.resource_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_selection->'resources') item
         WHERE item->>'resource_id' = v_publication.resource_id::text
    ) THEN
        RAISE EXCEPTION 'discovery selection escaped publication scope' USING ERRCODE = '23514';
    END IF;

    INSERT INTO request_engine.discovery_booking_handoffs (
        token_hash, organization_id, publication_id, publication_revision,
        mapping_id, mapping_revision, offering_version_id, location_id,
        selection, expires_at
    ) VALUES (
        p_token_hash,
        v_publication.organization_id,
        v_publication.id,
        v_publication.revision,
        v_mapping.id,
        v_mapping.revision,
        p_offering_version_id,
        p_location_id,
        p_selection,
        p_expires_at
    ) RETURNING id INTO v_id;
    RETURN v_id;
END
$function$;

ALTER FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamptz
) OWNER TO request_engine_admin;
REVOKE ALL ON FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamptz
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamptz
) TO request_engine_discovery;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0009 preserves exact F2 candidate observation fencing")
