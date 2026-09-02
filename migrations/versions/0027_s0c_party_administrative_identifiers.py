"""Add tenant-scoped Party administrative identifiers (S0c).

Revision ID: 0027_s0c_party_admin_ids
Revises: 0026_s3_escalation_lineage
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027_s0c_party_admin_ids"
down_revision: str | Sequence[str] | None = "0026_s3_escalation_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.party_administrative_identifiers (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    party_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('insurance_member')),
    issuer text NOT NULL CHECK (issuer <> '' AND length(issuer) <= 128),
    normalized_issuer text NOT NULL CHECK (
        normalized_issuer <> '' AND length(normalized_issuer) <= 128
    ),
    value text NOT NULL CHECK (value <> '' AND length(value) <= 256),
    normalized_value text NOT NULL CHECK (
        normalized_value <> '' AND length(normalized_value) <= 256
    ),
    active boolean NOT NULL DEFAULT true,
    created_by_principal_id uuid NOT NULL,
    source_kind text NOT NULL CHECK (source_kind IN ('operator', 'subject')),
    platform text CHECK (platform IS NULL OR (length(platform) <= 64 AND platform <> '')),
    relay_principal_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (organization_id, party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, relay_principal_id)
        REFERENCES request_engine.principals (organization_id, id)
);

CREATE UNIQUE INDEX party_admin_ids_one_active_per_issuer_uq
    ON request_engine.party_administrative_identifiers
       (organization_id, party_id, kind, normalized_issuer)
    WHERE active;
CREATE UNIQUE INDEX party_admin_ids_active_value_uq
    ON request_engine.party_administrative_identifiers
       (organization_id, kind, normalized_issuer, normalized_value)
    WHERE active;

CREATE FUNCTION request_engine.guard_party_administrative_identifier_facts()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.party_id IS DISTINCT FROM NEW.party_id
        OR OLD.kind IS DISTINCT FROM NEW.kind
        OR OLD.issuer IS DISTINCT FROM NEW.issuer
        OR OLD.normalized_issuer IS DISTINCT FROM NEW.normalized_issuer
        OR OLD.value IS DISTINCT FROM NEW.value
        OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value
    ) THEN
        RAISE EXCEPTION 'party administrative identifier facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER party_administrative_identifiers_guard_facts
BEFORE UPDATE ON request_engine.party_administrative_identifiers
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_administrative_identifier_facts();
CREATE TRIGGER party_administrative_identifiers_touch_updated_at
BEFORE UPDATE ON request_engine.party_administrative_identifiers
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
REVOKE EXECUTE ON FUNCTION
  request_engine.guard_party_administrative_identifier_facts() FROM PUBLIC;

ALTER TABLE request_engine.party_administrative_identifiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.party_administrative_identifiers FORCE ROW LEVEL SECURITY;
CREATE POLICY party_administrative_identifiers_tenant_policy
  ON request_engine.party_administrative_identifiers
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.party_administrative_identifiers FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.party_administrative_identifiers TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.party_administrative_identifiers TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0027 introduces authoritative administrative identifiers")
