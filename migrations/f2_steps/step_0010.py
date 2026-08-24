"""Close the F2 handoff payload contract and remove the provisional read surface.

Revision ID: 0010_f2_payload_contract
Revises: 0009_f2_candidate_fence
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_f2_payload_contract"
down_revision: str | Sequence[str] | None = "0009_f2_candidate_fence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
DROP FUNCTION request_engine.issue_discovery_booking_handoff(
    text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamptz
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
    v_duration integer;
    v_amount numeric;
    v_location_revision bigint;
    v_id uuid;
BEGIN
    IF p_token_hash IS NULL OR p_token_hash !~ '^[0-9a-f]{64}$'
       OR p_selection IS NULL
       OR COALESCE(jsonb_typeof(p_selection), '') <> 'object'
       OR COALESCE(jsonb_typeof(p_selection->'resources'), '') <> 'array'
       OR NULLIF(btrim(p_selection->>'currency'), '') IS NULL
       OR (p_selection->>'currency') !~ '^[A-Z]{3}$'
       OR NULLIF(btrim(p_selection->>'configuration_fingerprint'), '') IS NULL THEN
        RAISE EXCEPTION 'invalid discovery handoff payload' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_selection->'resources') = 0 THEN
        RAISE EXCEPTION 'discovery handoff resources are required' USING ERRCODE = '22023';
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
        v_duration := (p_selection->>'planned_duration_minutes')::integer;
        v_amount := (p_selection->>'amount')::numeric;
        v_location_revision := (p_selection->>'location_operational_revision')::bigint;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'invalid discovery handoff selection' USING ERRCODE = '22023';
    END;
    IF v_end <= v_start
       OR v_duration <= 0
       OR v_amount < 0
       OR v_location_revision <= 0
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
        p_token_hash, v_publication.organization_id, v_publication.id, v_publication.revision,
        v_mapping.id, v_mapping.revision, p_offering_version_id, p_location_id,
        p_selection, p_expires_at
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

DROP FUNCTION request_engine.search_discovery_candidates(
    text, double precision, double precision, integer, timestamptz, timestamptz, integer
);
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0010 preserves the final F2 handoff payload contract")
