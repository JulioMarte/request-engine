BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- Representation provenance is explicit, but remains intentionally small.
ALTER TABLE request_engine.representations
    ADD COLUMN authority_kind text NOT NULL DEFAULT 'delegated';

ALTER TABLE request_engine.representations
    ADD CONSTRAINT representations_authority_kind_check
    CHECK (authority_kind IN ('self', 'guardian', 'authorized_contact', 'delegated'));

-- Expiration is temporal truth from valid_until. Persisted status only models
-- revocation state. Keep the earlier status CHECK in place; this stricter check
-- intentionally intersects it and therefore excludes the legacy 'expired' value.
ALTER TABLE request_engine.representations
    ADD CONSTRAINT representations_status_v3_check
    CHECK (status IN ('active', 'revoked'));

CREATE INDEX representations_authority_lookup_idx
    ON request_engine.representations (
        organization_id,
        principal_id,
        represented_party_id,
        scope_key,
        valid_from,
        id
    )
    WHERE status = 'active';

COMMENT ON COLUMN request_engine.representations.authority_kind IS
    'Authority provenance only: self, guardian, authorized_contact, delegated. Not a permission hierarchy.';

COMMENT ON COLUMN request_engine.representations.scope_key IS
    'Exact namespaced application-policy scope. No wildcard/inheritance semantics in V3 baseline.';

COMMIT;