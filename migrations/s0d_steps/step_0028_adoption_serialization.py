"""Serialize same-organization S0d adoption before Party creation."""

from alembic import op

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.consume_identity_exchange_candidate_v1(
    p_candidate_id uuid,
    p_kind text,
    p_authority text,
    p_fingerprint text,
    p_principal_id uuid
) RETURNS TABLE (profile jsonb)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_person uuid;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity adoption actor context mismatch' USING ERRCODE = '42501';
    END IF;

    SELECT c.portable_person_id INTO v_person
    FROM request_engine.identity_exchange_candidates c
    WHERE c.id = p_candidate_id AND c.organization_id = v_org
      AND c.created_by_principal_id = p_principal_id
      AND c.kind = p_kind AND c.authority = p_authority
      AND c.fingerprint = p_fingerprint
      AND c.consumed_at IS NULL AND c.expires_at > clock_timestamp()
    FOR UPDATE;
    IF v_person IS NULL THEN
        RETURN;
    END IF;

    -- Different candidates may reference different strong documents for the
    -- same portable person. Serialize only that person inside this tenant so
    -- two aliases cannot create two local Parties before the binding unique
    -- index is reached. Other organizations remain independent.
    PERFORM pg_advisory_xact_lock(
        hashtextextended(v_org::text || ':' || v_person::text, 0)
    );

    -- Expiry is evaluated again after lock acquisition: time spent waiting
    -- must not silently extend a candidate's authorization window.
    IF NOT EXISTS (
        SELECT 1
        FROM request_engine.identity_exchange_candidates c
        WHERE c.id = p_candidate_id AND c.organization_id = v_org
          AND c.created_by_principal_id = p_principal_id
          AND c.consumed_at IS NULL AND c.expires_at > clock_timestamp()
    ) THEN
        RETURN;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM request_engine.organization_person_bindings b
        WHERE b.organization_id = v_org
          AND b.portable_person_id = v_person
          AND b.active
    ) THEN
        RAISE EXCEPTION 'portable identity already adopted by organization'
            USING ERRCODE = '23505',
                  CONSTRAINT = 'organization_person_binding_person_uq';
    END IF;

    UPDATE request_engine.identity_exchange_candidates c
    SET consumed_at = clock_timestamp()
    WHERE c.id = p_candidate_id AND c.organization_id = v_org;

    RETURN QUERY
    SELECT p.profile
    FROM request_engine.portable_person_profiles p
    JOIN request_engine.portable_person_identities i
      ON i.id = p.portable_person_id AND i.active
    WHERE p.portable_person_id = v_person AND p.active;
END
$function$;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)
