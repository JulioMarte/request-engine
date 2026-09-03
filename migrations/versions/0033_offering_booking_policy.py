"""Append-only OfferingVersion booking-policy override ledger.

Revision ID: 0033_offering_booking_policy
Revises: 0031_queue_release_recall_hold
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0033_offering_booking_policy"
down_revision: str | Sequence[str] | None = "0031_queue_release_recall_hold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

-- offering_versions is append-only (V3-I07 historical snapshot). A later
-- booking-policy for future reservations is therefore an appended override
-- revision, never an in-place mutation. The effective booking policy of an
-- OfferingVersion is the highest-revision row of this ledger when one exists,
-- otherwise the bootstrap booking_policy column. Existing reservations keep
-- their frozen booking_policy_snapshot untouched.
CREATE TABLE request_engine.offering_version_booking_policies (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    booking_policy jsonb NOT NULL CHECK (jsonb_typeof(booking_policy) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, offering_version_id, revision),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id)
);

CREATE INDEX offering_version_booking_policies_effective_idx
    ON request_engine.offering_version_booking_policies (
        organization_id, offering_version_id, revision DESC
    );

-- Same append-only guard the frozen V3 baseline uses for offering_versions:
-- UPDATE/DELETE are rejected for every role, including the table owner.
CREATE TRIGGER offering_version_booking_policies_immutable
BEFORE DELETE OR UPDATE ON request_engine.offering_version_booking_policies
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

ALTER TABLE request_engine.offering_version_booking_policies
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.offering_version_booking_policies
  FORCE ROW LEVEL SECURITY;
CREATE POLICY offering_version_booking_policies_tenant_isolation
  ON request_engine.offering_version_booking_policies
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.offering_version_booking_policies FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.offering_version_booking_policies TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.offering_version_booking_policies TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0032 introduces the append-only OfferingVersion booking-policy override"
        " ledger and is not reversible"
    )
