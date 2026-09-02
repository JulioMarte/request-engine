"""Narrow SECURITY DEFINER bridge for S0d portable identity exchange."""

from alembic import op

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE FUNCTION request_engine.publish_portable_person_v1(
    p_party_id uuid,
    p_fingerprint text,
    p_consent_fields text[],
    p_principal_id uuid
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_person uuid;
    v_bound_party uuid;
    v_name text;
    v_contacts jsonb;
    v_insurance jsonb;
    v_profile jsonb := '{}'::jsonb;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity exchange actor context mismatch' USING ERRCODE = '42501';
    END IF;
    IF p_fingerprint !~ '^[0-9a-f]{64}$'
       OR cardinality(p_consent_fields) = 0
       OR NOT ('display_name' = ANY(p_consent_fields))
       OR EXISTS (
            SELECT 1 FROM unnest(p_consent_fields) AS field
            WHERE field <> ALL(ARRAY['display_name','phone','email','insurance_member'])
       ) THEN
        RAISE EXCEPTION 'invalid portable profile contract' USING ERRCODE = '22023';
    END IF;

    SELECT p.display_name INTO v_name
    FROM request_engine.parties p
    JOIN request_engine.party_identity_documents d
      ON d.organization_id = p.organization_id AND d.party_id = p.id
     AND d.kind = 'cedula' AND d.active
    WHERE p.organization_id = v_org AND p.id = p_party_id AND p.active
    LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active Party with cédula is required' USING ERRCODE = '22023';
    END IF;

    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'channel', c.channel, 'value', c.normalized_value
    ) ORDER BY c.id), '[]'::jsonb) INTO v_contacts
    FROM request_engine.party_contact_points c
    WHERE c.organization_id = v_org AND c.party_id = p_party_id AND c.active
      AND ((c.channel IN ('phone','whatsapp') AND 'phone' = ANY(p_consent_fields))
        OR (c.channel = 'email' AND 'email' = ANY(p_consent_fields)));

    SELECT coalesce(jsonb_agg(jsonb_build_object(
        'issuer', a.issuer, 'value', a.value
    ) ORDER BY a.id), '[]'::jsonb) INTO v_insurance
    FROM request_engine.party_administrative_identifiers a
    WHERE a.organization_id = v_org AND a.party_id = p_party_id AND a.active
      AND a.kind = 'insurance_member' AND 'insurance_member' = ANY(p_consent_fields);

    v_profile := jsonb_build_object('display_name', v_name);
    IF 'phone' = ANY(p_consent_fields) OR 'email' = ANY(p_consent_fields) THEN
        v_profile := v_profile || jsonb_build_object('contact_points', v_contacts);
    END IF;
    IF 'insurance_member' = ANY(p_consent_fields) THEN
        v_profile := v_profile || jsonb_build_object('insurance_identifiers', v_insurance);
    END IF;

    SELECT i.portable_person_id INTO v_person
    FROM request_engine.portable_person_identifiers i
    JOIN request_engine.portable_person_identities p ON p.id = i.portable_person_id AND p.active
    WHERE i.kind = 'cedula' AND i.authority = 'DO:JCE'
      AND i.fingerprint = p_fingerprint AND i.active
    FOR UPDATE OF i;

    IF v_person IS NULL THEN
        INSERT INTO request_engine.portable_person_identities DEFAULT VALUES RETURNING id INTO v_person;
        INSERT INTO request_engine.portable_person_identifiers
            (portable_person_id, kind, authority, fingerprint)
        VALUES (v_person, 'cedula', 'DO:JCE', p_fingerprint);
        INSERT INTO request_engine.portable_person_profiles(portable_person_id, profile)
        VALUES (v_person, v_profile);
    END IF;

    SELECT b.party_id INTO v_bound_party
    FROM request_engine.organization_person_bindings b
    WHERE b.organization_id = v_org AND b.portable_person_id = v_person AND b.active
    FOR UPDATE;
    IF v_bound_party IS NOT NULL AND v_bound_party <> p_party_id THEN
        RAISE EXCEPTION 'portable identity already belongs to another local Party'
            USING ERRCODE = '23505';
    END IF;
    IF v_bound_party IS NULL THEN
        INSERT INTO request_engine.organization_person_bindings(
            organization_id, party_id, portable_person_id, proof_kind,
            consented_fields, created_by_principal_id
        ) VALUES (
            v_org, p_party_id, v_person, 'operator_document_witness',
            p_consent_fields, p_principal_id
        );
    END IF;
    RETURN v_person;
END
$function$;

CREATE FUNCTION request_engine.create_identity_exchange_candidate_v1(
    p_fingerprint text,
    p_principal_id uuid
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_person uuid;
    v_candidate uuid;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id
       OR p_fingerprint !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid identity match context' USING ERRCODE = '42501';
    END IF;
    SELECT i.portable_person_id INTO v_person
    FROM request_engine.portable_person_identifiers i
    JOIN request_engine.portable_person_identities p ON p.id = i.portable_person_id AND p.active
    JOIN request_engine.portable_person_profiles pr
      ON pr.portable_person_id = i.portable_person_id AND pr.active
    WHERE i.kind = 'cedula' AND i.authority = 'DO:JCE'
      AND i.fingerprint = p_fingerprint AND i.active
      AND NOT EXISTS (
          SELECT 1 FROM request_engine.organization_person_bindings b
          WHERE b.organization_id = v_org
            AND b.portable_person_id = i.portable_person_id AND b.active
      );
    IF v_person IS NULL THEN
        RETURN NULL;
    END IF;
    INSERT INTO request_engine.identity_exchange_candidates(
        organization_id, portable_person_id, fingerprint, created_by_principal_id
    ) VALUES (v_org, v_person, p_fingerprint, p_principal_id)
    RETURNING id INTO v_candidate;
    RETURN v_candidate;
END
$function$;

CREATE FUNCTION request_engine.consume_identity_exchange_candidate_v1(
    p_candidate_id uuid,
    p_fingerprint text,
    p_principal_id uuid
) RETURNS TABLE (portable_person_id uuid, profile jsonb)
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
    UPDATE request_engine.identity_exchange_candidates c
    SET consumed_at = clock_timestamp()
    WHERE c.id = p_candidate_id AND c.organization_id = v_org
      AND c.created_by_principal_id = p_principal_id
      AND c.fingerprint = p_fingerprint
      AND c.consumed_at IS NULL AND c.expires_at > clock_timestamp()
    RETURNING c.portable_person_id INTO v_person;
    IF v_person IS NULL THEN
        RETURN;
    END IF;
    RETURN QUERY
    SELECT p.portable_person_id, p.profile
    FROM request_engine.portable_person_profiles p
    JOIN request_engine.portable_person_identities i
      ON i.id = p.portable_person_id AND i.active
    WHERE p.portable_person_id = v_person AND p.active;
END
$function$;

CREATE FUNCTION request_engine.bind_consumed_identity_candidate_v1(
    p_candidate_id uuid,
    p_party_id uuid,
    p_consent_fields text[],
    p_principal_id uuid
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_person uuid;
    v_binding uuid;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity binding actor context mismatch' USING ERRCODE = '42501';
    END IF;
    SELECT c.portable_person_id INTO v_person
    FROM request_engine.identity_exchange_candidates c
    WHERE c.id = p_candidate_id AND c.organization_id = v_org
      AND c.created_by_principal_id = p_principal_id AND c.consumed_at IS NOT NULL;
    IF v_person IS NULL OR NOT EXISTS (
        SELECT 1 FROM request_engine.parties p
        WHERE p.organization_id = v_org AND p.id = p_party_id AND p.active
    ) THEN
        RAISE EXCEPTION 'candidate or Party is not bindable' USING ERRCODE = '22023';
    END IF;
    INSERT INTO request_engine.organization_person_bindings(
        organization_id, party_id, portable_person_id, proof_kind,
        consented_fields, created_by_principal_id
    ) VALUES (
        v_org, p_party_id, v_person, 'operator_document_witness',
        p_consent_fields, p_principal_id
    ) RETURNING id INTO v_binding;
    RETURN v_binding;
END
$function$;

REVOKE ALL ON FUNCTION request_engine.publish_portable_person_v1(uuid,text,text[],uuid)
    FROM PUBLIC, request_engine_worker;
REVOKE ALL ON FUNCTION request_engine.create_identity_exchange_candidate_v1(text,uuid)
    FROM PUBLIC, request_engine_worker;
REVOKE ALL ON FUNCTION request_engine.consume_identity_exchange_candidate_v1(uuid,text,uuid)
    FROM PUBLIC, request_engine_worker;
REVOKE ALL ON FUNCTION request_engine.bind_consumed_identity_candidate_v1(uuid,uuid,text[],uuid)
    FROM PUBLIC, request_engine_worker;
GRANT EXECUTE ON FUNCTION request_engine.publish_portable_person_v1(uuid,text,text[],uuid)
    TO request_engine_app;
GRANT EXECUTE ON FUNCTION request_engine.create_identity_exchange_candidate_v1(text,uuid)
    TO request_engine_app;
GRANT EXECUTE ON FUNCTION request_engine.consume_identity_exchange_candidate_v1(uuid,text,uuid)
    TO request_engine_app;
GRANT EXECUTE ON FUNCTION request_engine.bind_consumed_identity_candidate_v1(uuid,uuid,text[],uuid)
    TO request_engine_app;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)
