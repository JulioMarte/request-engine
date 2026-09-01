"""Add party identity documents and registry attribution columns (S0b).

Revision ID: 0023_s0b_party_identity_docs
Revises: 0022_f7_arrival_estimates
Create Date: 2026-08-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_s0b_party_identity_docs"
down_revision: str | Sequence[str] | None = "0022_f7_arrival_estimates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

CREATE TABLE request_engine.party_identity_documents (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    party_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('cedula', 'passport')),
    normalized_value text NOT NULL CHECK (normalized_value <> ''),
    active boolean NOT NULL DEFAULT true,
    created_by_principal_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, kind, normalized_value),
    FOREIGN KEY (organization_id, party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id)
);

CREATE UNIQUE INDEX party_identity_documents_one_active_per_kind_uq
    ON request_engine.party_identity_documents (organization_id, party_id, kind)
    WHERE active;
CREATE INDEX party_identity_documents_exact_lookup_idx
    ON request_engine.party_identity_documents (organization_id, kind, normalized_value)
    WHERE active;

CREATE FUNCTION request_engine.guard_party_identity_documents()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.kind IS DISTINCT FROM NEW.kind
           OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value THEN
            RAISE EXCEPTION 'party identity document facts are immutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER party_identity_documents_guard_facts
BEFORE INSERT OR UPDATE ON request_engine.party_identity_documents
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_identity_documents();

CREATE TRIGGER party_identity_documents_touch_updated_at
BEFORE UPDATE ON request_engine.party_identity_documents
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

REVOKE EXECUTE ON FUNCTION
  request_engine.guard_party_identity_documents() FROM PUBLIC;

ALTER TABLE request_engine.parties
  ADD COLUMN created_by_principal_id uuid;
ALTER TABLE request_engine.parties
  ADD CONSTRAINT parties_created_by_principal_fk
  FOREIGN KEY (organization_id, created_by_principal_id)
  REFERENCES request_engine.principals (organization_id, id);
ALTER TABLE request_engine.party_contact_points
  ADD COLUMN created_by_principal_id uuid;
ALTER TABLE request_engine.party_contact_points
  ADD COLUMN registered_via text CHECK (registered_via IN ('operator', 'bot'));

ALTER TABLE request_engine.party_contact_points
  ADD CONSTRAINT party_contact_points_created_by_principal_fk
  FOREIGN KEY (organization_id, created_by_principal_id)
  REFERENCES request_engine.principals (organization_id, id);

ALTER TABLE request_engine.party_identity_documents
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.party_identity_documents
  FORCE ROW LEVEL SECURITY;
CREATE POLICY party_identity_documents_tenant_policy
  ON request_engine.party_identity_documents
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.party_identity_documents FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.party_identity_documents TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.party_identity_documents TO request_engine_admin;

CREATE FUNCTION request_engine.guard_party_contact_point_verification()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.verified IS TRUE
       AND NEW.verified IS NOT TRUE THEN
        RAISE EXCEPTION 'party contact point verification is monotone upward'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER party_contact_points_guard_verification
BEFORE UPDATE ON request_engine.party_contact_points
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_contact_point_verification();

REVOKE EXECUTE ON FUNCTION
  request_engine.guard_party_contact_point_verification() FROM PUBLIC;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0023 introduces party identity documents and is not reversible")
