"""Privileged persistence for S0d federated Party identity adoption."""

from alembic import op

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

ALTER TABLE request_engine.party_identity_documents
    ADD COLUMN authority text;
UPDATE request_engine.party_identity_documents
SET authority = 'DO:JCE'
WHERE kind = 'cedula' AND authority IS NULL;
ALTER TABLE request_engine.party_identity_documents
    DROP CONSTRAINT party_identity_documents_kind_ck;
ALTER TABLE request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_kind_ck
    CHECK (kind IN ('cedula', 'passport', 'rnc'));
ALTER TABLE request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_authority_shape_ck
    CHECK (
        (kind = 'cedula' AND authority = 'DO:JCE')
        OR (kind = 'passport' AND (authority IS NULL OR authority ~ '^[A-Z]{2}$'))
        OR (kind = 'rnc' AND authority = 'DO:DGII')
    );

DROP INDEX request_engine.party_identity_documents_one_active_per_kind_uq;
DROP INDEX request_engine.party_identity_documents_active_value_uq;
CREATE UNIQUE INDEX party_identity_documents_one_active_per_kind_uq
    ON request_engine.party_identity_documents
       (organization_id, party_id, kind, COALESCE(authority, ''))
    WHERE active;
CREATE UNIQUE INDEX party_identity_documents_active_value_uq
    ON request_engine.party_identity_documents
       (organization_id, kind, COALESCE(authority, ''), normalized_value)
    WHERE active;

CREATE OR REPLACE FUNCTION request_engine.guard_party_identity_documents()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, request_engine
AS $function$
DECLARE
    v_party_kind text;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.kind IS DISTINCT FROM NEW.kind
        OR OLD.authority IS DISTINCT FROM NEW.authority
        OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value
    ) THEN
        RAISE EXCEPTION 'party identity document facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT p.party_kind INTO v_party_kind
    FROM request_engine.parties p
    WHERE p.organization_id = NEW.organization_id AND p.id = NEW.party_id;
    IF v_party_kind IS NULL OR NOT (
        (v_party_kind = 'person' AND NEW.kind IN ('cedula', 'passport'))
        OR (v_party_kind = 'organization' AND NEW.kind = 'rnc')
    ) THEN
        RAISE EXCEPTION 'strong identifier kind is incompatible with Party kind'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE FUNCTION request_engine.guard_party_kind_immutable()
RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF OLD.party_kind IS DISTINCT FROM NEW.party_kind THEN
        RAISE EXCEPTION 'Party kind is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER parties_guard_kind
BEFORE UPDATE OF party_kind ON request_engine.parties
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_kind_immutable();

CREATE TABLE request_engine.portable_party_identities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    party_kind text NOT NULL CHECK (party_kind IN ('person', 'organization')),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (id, party_kind)
);

CREATE TABLE request_engine.portable_party_identifiers (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    portable_party_id uuid NOT NULL,
    party_kind text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('cedula', 'passport', 'rnc')),
    authority text NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (portable_party_id, party_kind)
        REFERENCES request_engine.portable_party_identities(id, party_kind),
    CONSTRAINT portable_party_identifier_subject_ck CHECK (
        (party_kind = 'person' AND kind IN ('cedula', 'passport'))
        OR (party_kind = 'organization' AND kind = 'rnc')
    ),
    CONSTRAINT portable_party_identifier_authority_ck CHECK (
        (kind = 'cedula' AND authority = 'DO:JCE')
        OR (kind = 'passport' AND authority ~ '^[A-Z]{2}$')
        OR (kind = 'rnc' AND authority = 'DO:DGII')
    )
);
CREATE UNIQUE INDEX portable_party_identifier_active_uq
    ON request_engine.portable_party_identifiers(party_kind, kind, authority, fingerprint)
    WHERE active;
CREATE INDEX portable_party_identifier_party_idx
    ON request_engine.portable_party_identifiers(portable_party_id)
    WHERE active;

CREATE TABLE request_engine.portable_party_profiles (
    portable_party_id uuid PRIMARY KEY
        REFERENCES request_engine.portable_party_identities(id),
    profile jsonb NOT NULL CHECK (jsonb_typeof(profile) = 'object'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE request_engine.identity_exchange_candidates (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    portable_party_id uuid NOT NULL REFERENCES request_engine.portable_party_identities(id),
    kind text NOT NULL CHECK (kind IN ('cedula', 'passport', 'rnc')),
    authority text NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    created_by_principal_id uuid NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + interval '10 minutes'),
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT identity_exchange_candidate_authority_ck CHECK (
        (kind = 'cedula' AND authority = 'DO:JCE')
        OR (kind = 'passport' AND authority ~ '^[A-Z]{2}$')
        OR (kind = 'rnc' AND authority = 'DO:DGII')
    ),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals(organization_id, id)
);
CREATE INDEX identity_exchange_candidate_lookup_idx
    ON request_engine.identity_exchange_candidates(organization_id, id, expires_at);
ALTER TABLE request_engine.identity_exchange_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.identity_exchange_candidates FORCE ROW LEVEL SECURITY;
CREATE POLICY identity_exchange_candidates_tenant_policy
    ON request_engine.identity_exchange_candidates
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

CREATE TABLE request_engine.organization_party_bindings (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    party_id uuid NOT NULL,
    portable_party_id uuid NOT NULL REFERENCES request_engine.portable_party_identities(id),
    proof_kind text NOT NULL CHECK (proof_kind = 'operator_document_witness'),
    consented_fields text[] NOT NULL CHECK (cardinality(consented_fields) > 0),
    created_by_principal_id uuid NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (organization_id, party_id)
        REFERENCES request_engine.parties(organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals(organization_id, id)
);
CREATE UNIQUE INDEX organization_party_binding_party_uq
    ON request_engine.organization_party_bindings(organization_id, party_id) WHERE active;
CREATE UNIQUE INDEX organization_party_binding_identity_uq
    ON request_engine.organization_party_bindings(organization_id, portable_party_id) WHERE active;
ALTER TABLE request_engine.organization_party_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.organization_party_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY organization_party_bindings_tenant_policy
    ON request_engine.organization_party_bindings
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.portable_party_identities FROM PUBLIC, request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.portable_party_identifiers FROM PUBLIC, request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.portable_party_profiles FROM PUBLIC, request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.identity_exchange_candidates FROM PUBLIC, request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.organization_party_bindings FROM PUBLIC, request_engine_app, request_engine_worker;
GRANT ALL PRIVILEGES ON request_engine.portable_party_identities TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.portable_party_identifiers TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.portable_party_profiles TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.identity_exchange_candidates TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.organization_party_bindings TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)
