"""Privileged persistence for S0d federated Party identity adoption."""

from alembic import op

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- S0b originally stored identity document kind + value. S0d makes the issuer
-- namespace explicit so passports from different countries cannot collide.
ALTER TABLE request_engine.party_identity_documents
    ADD COLUMN authority text;
UPDATE request_engine.party_identity_documents
SET authority = 'DO:JCE'
WHERE kind = 'cedula' AND authority IS NULL;
ALTER TABLE request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_authority_shape_ck
    CHECK (
        (kind = 'cedula' AND authority = 'DO:JCE')
        OR (kind = 'passport' AND (authority IS NULL OR authority ~ '^[A-Z]{2}$'))
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
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.kind IS DISTINCT FROM NEW.kind
           OR OLD.authority IS DISTINCT FROM NEW.authority
           OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value THEN
            RAISE EXCEPTION 'party identity document facts are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;

CREATE TABLE request_engine.portable_person_identities (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE request_engine.portable_person_identifiers (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    portable_person_id uuid NOT NULL
        REFERENCES request_engine.portable_person_identities(id),
    kind text NOT NULL CHECK (kind IN ('cedula', 'passport')),
    authority text NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT portable_person_identifier_authority_ck CHECK (
        (kind = 'cedula' AND authority = 'DO:JCE')
        OR (kind = 'passport' AND authority ~ '^[A-Z]{2}$')
    )
);
CREATE UNIQUE INDEX portable_person_identifier_active_uq
    ON request_engine.portable_person_identifiers(kind, authority, fingerprint)
    WHERE active;
CREATE INDEX portable_person_identifier_person_idx
    ON request_engine.portable_person_identifiers(portable_person_id)
    WHERE active;

CREATE TABLE request_engine.portable_person_profiles (
    portable_person_id uuid PRIMARY KEY
        REFERENCES request_engine.portable_person_identities(id),
    profile jsonb NOT NULL CHECK (jsonb_typeof(profile) = 'object'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE request_engine.identity_exchange_candidates (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    portable_person_id uuid NOT NULL
        REFERENCES request_engine.portable_person_identities(id),
    kind text NOT NULL CHECK (kind IN ('cedula', 'passport')),
    authority text NOT NULL,
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    created_by_principal_id uuid NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + interval '10 minutes'),
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT identity_exchange_candidate_authority_ck CHECK (
        (kind = 'cedula' AND authority = 'DO:JCE')
        OR (kind = 'passport' AND authority ~ '^[A-Z]{2}$')
    ),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals(organization_id, id)
);
CREATE INDEX identity_exchange_candidate_lookup_idx
    ON request_engine.identity_exchange_candidates(organization_id, id, expires_at);

CREATE TABLE request_engine.organization_person_bindings (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    party_id uuid NOT NULL,
    portable_person_id uuid NOT NULL
        REFERENCES request_engine.portable_person_identities(id),
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
CREATE UNIQUE INDEX organization_person_binding_party_uq
    ON request_engine.organization_person_bindings(organization_id, party_id)
    WHERE active;
CREATE UNIQUE INDEX organization_person_binding_person_uq
    ON request_engine.organization_person_bindings(organization_id, portable_person_id)
    WHERE active;

ALTER TABLE request_engine.organization_person_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.organization_person_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY organization_person_bindings_tenant_policy
    ON request_engine.organization_person_bindings
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.portable_person_identities FROM PUBLIC;
REVOKE ALL ON request_engine.portable_person_identifiers FROM PUBLIC;
REVOKE ALL ON request_engine.portable_person_profiles FROM PUBLIC;
REVOKE ALL ON request_engine.identity_exchange_candidates FROM PUBLIC;
REVOKE ALL ON request_engine.organization_person_bindings FROM PUBLIC;
REVOKE ALL ON request_engine.portable_person_identities
    FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.portable_person_identifiers
    FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.portable_person_profiles
    FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.identity_exchange_candidates
    FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.organization_person_bindings
    FROM request_engine_app, request_engine_worker;
GRANT ALL PRIVILEGES ON request_engine.portable_person_identities TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.portable_person_identifiers TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.portable_person_profiles TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.identity_exchange_candidates TO request_engine_admin;
GRANT ALL PRIVILEGES ON request_engine.organization_person_bindings TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)
