"""Privileged persistence for S0d federated Party identity adoption."""

from alembic import op

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

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
    kind text NOT NULL CHECK (kind = 'cedula'),
    authority text NOT NULL CHECK (authority = 'DO:JCE'),
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE UNIQUE INDEX portable_person_identifier_active_uq
    ON request_engine.portable_person_identifiers(kind, authority, fingerprint)
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
    fingerprint text NOT NULL CHECK (fingerprint ~ '^[0-9a-f]{64}$'),
    created_by_principal_id uuid NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT (clock_timestamp() + interval '10 minutes'),
    consumed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
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
REVOKE ALL ON request_engine.portable_person_identities FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.portable_person_identifiers FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.portable_person_profiles FROM request_engine_app, request_engine_worker;
REVOKE ALL ON request_engine.identity_exchange_candidates FROM request_engine_app, request_engine_worker;
GRANT SELECT ON request_engine.organization_person_bindings TO request_engine_app;
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
