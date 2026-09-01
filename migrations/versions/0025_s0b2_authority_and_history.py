"""Rework authority/platform attribution and add party revision ledger (S0b2).

Revision ID: 0025_s0b2_authority_and_history
Revises: 0024_s0b_party_contact_lookup
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025_s0b2_authority_and_history"
down_revision: str | Sequence[str] | None = "0024_s0b_party_contact_lookup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

-- §9.5: attribution becomes two orthogonal durable facts — whose authority
-- produced the change (source_kind) and which surface executed it (platform).
-- The schema is unreleased, so renaming registered_via is safe; the old
-- auto-named CHECK on 'bot' is replaced with the §9.1 authority vocabulary.
-- The fact tables record `relay_principal_id`: the technical caller preserved
-- only in the admitted acting-operator relay. The revision ledger instead
-- stores `attributed_operator_principal_id`: the operator on whose behalf a
-- relay acted (§9.3).
ALTER TABLE request_engine.party_contact_points
  RENAME COLUMN registered_via TO source_kind;
ALTER TABLE request_engine.party_contact_points
  DROP CONSTRAINT party_contact_points_registered_via_check;
ALTER TABLE request_engine.party_contact_points
  ADD CONSTRAINT party_contact_points_source_kind_check
  CHECK (source_kind IN ('operator', 'subject'));

ALTER TABLE request_engine.party_contact_points
  ADD COLUMN platform text
  CHECK (platform IS NULL OR (length(platform) <= 64 AND platform <> ''));
ALTER TABLE request_engine.party_contact_points
  ADD COLUMN relay_principal_id uuid;
ALTER TABLE request_engine.party_contact_points
  ADD CONSTRAINT party_contact_points_relay_principal_fk
  FOREIGN KEY (organization_id, relay_principal_id)
  REFERENCES request_engine.principals (organization_id, id);

ALTER TABLE request_engine.parties
  ADD COLUMN source_kind text CHECK (source_kind IN ('operator', 'subject'));
ALTER TABLE request_engine.parties
  ADD COLUMN platform text
  CHECK (platform IS NULL OR (length(platform) <= 64 AND platform <> ''));
ALTER TABLE request_engine.parties
  ADD COLUMN relay_principal_id uuid;
ALTER TABLE request_engine.parties
  ADD CONSTRAINT parties_relay_principal_fk
  FOREIGN KEY (organization_id, relay_principal_id)
  REFERENCES request_engine.principals (organization_id, id);

ALTER TABLE request_engine.party_identity_documents
  ADD COLUMN source_kind text CHECK (source_kind IN ('operator', 'subject'));
ALTER TABLE request_engine.party_identity_documents
  ADD COLUMN platform text
  CHECK (platform IS NULL OR (length(platform) <= 64 AND platform <> ''));
ALTER TABLE request_engine.party_identity_documents
  ADD COLUMN relay_principal_id uuid;
ALTER TABLE request_engine.party_identity_documents
  ADD CONSTRAINT party_identity_documents_relay_principal_fk
  FOREIGN KEY (organization_id, relay_principal_id)
  REFERENCES request_engine.principals (organization_id, id);

-- §9.3: per-party monotone revision cursor. The revision starts at 1 and
-- only ever moves upward; the check is a direct backstop on the column.
ALTER TABLE request_engine.parties
  ADD COLUMN identity_revision bigint NOT NULL DEFAULT 1
    CONSTRAINT parties_identity_revision_positive CHECK (identity_revision >= 1);

-- §9.3: append-only revision ledger. Every party mutation appends one
-- revision in the same transaction with the resulting full identity snapshot.
CREATE TABLE request_engine.party_identity_revisions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    party_id uuid NOT NULL,
    revision bigint NOT NULL CHECK (revision >= 1),
    change_kind text NOT NULL CHECK (change_kind IN (
        'registered', 'renamed', 'contact_added', 'contact_deactivated',
        'document_added', 'verification_flipped', 'party_deactivated',
        'rollback')),
    display_name text NOT NULL,
    active boolean NOT NULL,
    state jsonb NOT NULL,
    actor_principal_id uuid,
    attributed_operator_principal_id uuid,
    source_kind text CHECK (source_kind IS NULL OR source_kind IN ('operator', 'subject')),
    platform text CHECK (platform IS NULL OR (length(platform) <= 64 AND platform <> '')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, party_id, revision),
    FOREIGN KEY (organization_id, party_id)
        REFERENCES request_engine.parties (organization_id, id),
    FOREIGN KEY (organization_id, actor_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, attributed_operator_principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    CHECK (jsonb_typeof(state) = 'object')
);

-- §9.3: the ledger rejects UPDATE and DELETE at the database level for every
-- role, including the table owner; defense in depth beyond the missing
-- UPDATE/DELETE grants.
CREATE FUNCTION request_engine.guard_party_identity_revisions()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    RAISE EXCEPTION 'party identity revisions is an append-only ledger'
        USING ERRCODE = '23514';
END
$function$;
CREATE TRIGGER party_identity_revisions_guard_append_only
BEFORE UPDATE OR DELETE ON request_engine.party_identity_revisions
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_identity_revisions();

REVOKE EXECUTE ON FUNCTION
  request_engine.guard_party_identity_revisions() FROM PUBLIC;

ALTER TABLE request_engine.party_identity_revisions
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.party_identity_revisions
  FORCE ROW LEVEL SECURITY;
CREATE POLICY party_identity_revisions_tenant_policy
  ON request_engine.party_identity_revisions
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.party_identity_revisions FROM PUBLIC;
-- The schema default privileges (022) pre-grant SELECT/INSERT/UPDATE to the
-- runtime role; the ledger is append-only, so UPDATE is revoked explicitly.
REVOKE UPDATE ON request_engine.party_identity_revisions
  FROM request_engine_app;
GRANT SELECT, INSERT
  ON request_engine.party_identity_revisions TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.party_identity_revisions TO request_engine_admin;

-- §9.2: administrative contacts of staff principals. Verification is
-- mandatory here (one-time code, hashed with expiry and attempt limits);
-- delivery of the code remains external transactional intent.
CREATE TABLE request_engine.principal_contacts (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    principal_id uuid NOT NULL,
    channel text NOT NULL CHECK (channel IN ('whatsapp', 'phone', 'email')),
    normalized_value text NOT NULL CHECK (normalized_value <> ''),
    verified boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    verification_code_hash text,
    verification_expires_at timestamptz,
    verification_attempts integer NOT NULL DEFAULT 0
        CHECK (verification_attempts >= 0),
    created_by_principal_id uuid,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, principal_id, channel, normalized_value),
    FOREIGN KEY (organization_id, principal_id)
        REFERENCES request_engine.principals (organization_id, id),
    FOREIGN KEY (organization_id, created_by_principal_id)
        REFERENCES request_engine.principals (organization_id, id)
);

-- One active administrative contact per staff principal.
CREATE UNIQUE INDEX principal_contacts_one_active_per_principal_uq
    ON request_engine.principal_contacts (organization_id, principal_id)
    WHERE active;

CREATE FUNCTION request_engine.guard_principal_contacts()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.channel IS DISTINCT FROM NEW.channel
           OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value THEN
            RAISE EXCEPTION
                'staff administrative contact facts are immutable; register a new contact instead'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.verified IS TRUE
           AND NEW.verified IS NOT TRUE THEN
            RAISE EXCEPTION
                'staff administrative contact verification is monotone upward'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$function$;
CREATE TRIGGER principal_contacts_guard_facts
BEFORE UPDATE ON request_engine.principal_contacts
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_principal_contacts();

CREATE TRIGGER principal_contacts_touch_updated_at
BEFORE UPDATE ON request_engine.principal_contacts
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

REVOKE EXECUTE ON FUNCTION
  request_engine.guard_principal_contacts() FROM PUBLIC;

ALTER TABLE request_engine.principal_contacts
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.principal_contacts
  FORCE ROW LEVEL SECURITY;
CREATE POLICY principal_contacts_tenant_policy
  ON request_engine.principal_contacts
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.principal_contacts FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.principal_contacts TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.principal_contacts TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0025 reworks attribution authority and introduces the party revision"
        " ledger and is not reversible"
    )
