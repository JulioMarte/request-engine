"""Organization-level communication channel policies per purpose.

Revision ID: 0034_org_channel_policies
Revises: 0033_offering_booking_policy
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0034_org_channel_policies"
down_revision: str | Sequence[str] | None = "0033_offering_booking_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_read, request_cmd, pg_catalog;

-- One organization-level default channel policy per supported communication
-- purpose. A MISSING row means "not configured" and falls back to the hardcoded
-- patient-transactional default; a PRESENT row with enabled = false is an
-- intentionally disabled purpose (new intents for it are rejected); a PRESENT
-- row with enabled = true serves as the org default when a task carries no
-- task-level channel policy. In-flight tasks keep their frozen snapshot.
CREATE TABLE request_engine.organization_channel_policies (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    purpose text NOT NULL CHECK (purpose IN (
        'appointment_confirmation',
        'appointment_reminder',
        'attendance_confirmation_request',
        'slot_offer_available',
        'operational_recovery_impact',
        'operational_recovery_rescheduled'
    )),
    enabled boolean NOT NULL,
    channel_policy jsonb NOT NULL CHECK (jsonb_typeof(channel_policy) = 'object'),
    revision integer NOT NULL CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, purpose)
);

ALTER TABLE request_engine.organization_channel_policies
  ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.organization_channel_policies
  FORCE ROW LEVEL SECURITY;
CREATE POLICY organization_channel_policies_tenant_isolation
  ON request_engine.organization_channel_policies
  USING (organization_id = request_engine.current_organization_id())
  WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.organization_channel_policies FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE
  ON request_engine.organization_channel_policies TO request_engine_app;
GRANT ALL PRIVILEGES
  ON request_engine.organization_channel_policies TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "0034 introduces the organization channel-policy configuration table and is not reversible"
    )
