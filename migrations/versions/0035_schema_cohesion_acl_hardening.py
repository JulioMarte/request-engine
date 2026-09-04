"""Tighten runtime ACLs and remove schema-cohesion defects.

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

_SECURITY_DEFINERS = (
    (
        "request_engine.bind_consumed_identity_candidate_v1",
        "uuid, uuid, text[], uuid",
    ),
    (
        "request_engine.consume_identity_exchange_candidate_v1",
        "uuid, text, text, text, uuid",
    ),
    (
        "request_engine.create_identity_exchange_candidate_v1",
        "text, text, text, uuid",
    ),
    ("request_engine.identity_exchange_existing_party_v1", "uuid, uuid"),
    (
        "request_engine.publish_portable_party_v1",
        "uuid, text, text, text, text[], uuid",
    ),
    ("request_read.recovery_source_revision", "uuid, uuid"),
)


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for table in _IMMUTABLE_APP_TABLES:
        statement = f"REVOKE UPDATE ON request_engine.{table} FROM request_engine_app"
        op.execute(statement)
    op.execute("DROP INDEX request_engine.service_sessions_queue_idx")
    for name, arguments in _SECURITY_DEFINERS:
        function_ref = f"{name}({arguments})"
        op.execute(
            f"ALTER FUNCTION {function_ref} "
            "SET search_path = pg_catalog, request_engine, pg_temp"
        )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("schema cohesion hardening is not reversible")
