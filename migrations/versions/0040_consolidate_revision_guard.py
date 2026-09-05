"""Consolidate duplicate exact-revision trigger guards.

Revision ID: 0040_consolidate_revision_guard
Revises: 0039_remove_queue_status_v1
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040_consolidate_revision_guard"
down_revision: str | Sequence[str] | None = "0039_remove_queue_status_v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVISION_TRIGGERS = (
    ("booking_context_terms", "booking_context_terms_revision_step"),
    ("discovery_publications", "discovery_publications_revision_step"),
    ("offering_service_classifications", "offering_service_classifications_revision_step"),
    ("resource_location_assignments", "resource_location_assignments_revision_step"),
    ("resource_public_profiles", "resource_public_profiles_revision_step"),
    ("service_classifications", "service_classifications_revision_step"),
)


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    for table, trigger in _REVISION_TRIGGERS:
        op.execute(f"DROP TRIGGER {trigger} ON request_engine.{table}")
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE ON request_engine.{table} "
            "FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step()"
        )
    op.execute("DROP FUNCTION request_engine.guard_f1_exact_revision_step()")
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("revision-guard consolidation is not reversible")
