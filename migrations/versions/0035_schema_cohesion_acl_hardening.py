"""Tighten runtime ACLs around append-only and immutable facts.

Revision ID: 0035_schema_cohesion_acl_hardening
Revises: 0034_org_channel_policies
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0035_schema_cohesion_acl_hardening"
down_revision: str | Sequence[str] | None = "0034_org_channel_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_IMMUTABLE_APP_TABLES = (
    "attendance_responses",
    "audit_records",
    "offering_resource_requirements",
    "offering_version_booking_policies",
    "offering_version_booking_terms",
    "offering_versions",
    "operational_recovery_escalations",
    "operational_recovery_proposals",
    "queue_entry_operator_selections",
    "reminder_acknowledgements",
    "request_definition_versions",
    "reservation_commercial_commitment_context_terms",
    "reservation_commercial_commitments",
)


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for table in _IMMUTABLE_APP_TABLES:
        op.execute(
            f"REVOKE UPDATE ON TABLE request_engine.{table} FROM request_engine_app"
        )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("least-privilege schema cohesion hardening is not reversible")
