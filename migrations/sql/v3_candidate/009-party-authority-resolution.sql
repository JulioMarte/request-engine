BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- One database-owned definition of current exact-scope Party authority.
-- SECURITY INVOKER is intentional: tenant RLS remains in force for the caller.
CREATE FUNCTION request_engine.resolve_current_party_authority(
    p_organization_id uuid,
    p_principal_id uuid,
    p_represented_party_id uuid,
    p_scope_key text
)
RETURNS TABLE (
    representation_id uuid,
    authority_kind text,
    valid_from timestamptz,
    valid_until timestamptz
)
LANGUAGE sql
VOLATILE
SECURITY INVOKER
SET search_path = pg_catalog, request_engine
AS $function$
    SELECT
        r.id,
        r.authority_kind,
        r.valid_from,
        r.valid_until
    FROM request_engine.representations r
    JOIN request_engine.principals p
      ON p.organization_id = r.organization_id
     AND p.id = r.principal_id
    JOIN request_engine.parties party
      ON party.organization_id = r.organization_id
     AND party.id = r.represented_party_id
    CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
    WHERE p_scope_key <> ''
      AND r.organization_id = p_organization_id
      AND r.principal_id = p_principal_id
      AND r.represented_party_id = p_represented_party_id
      AND r.scope_key = p_scope_key
      AND r.status = 'active'
      AND p.active
      AND party.active
      AND r.valid_from <= clock.db_now
      AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
    ORDER BY r.valid_from DESC, r.id DESC
    LIMIT 1
$function$;

RESET ROLE;

REVOKE ALL ON FUNCTION request_engine.resolve_current_party_authority(uuid, uuid, uuid, text)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION request_engine.resolve_current_party_authority(uuid, uuid, uuid, text)
    TO request_engine_app, request_engine_worker, request_engine_admin;

COMMIT;
