"""Make Resource location assignment temporally exclusive across Locations.

Revision ID: 0049_assignment_exclusivity
Revises: 0048_remove_legacy_resource_location
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0049_assignment_exclusivity"
down_revision: str | Sequence[str] | None = "0048_remove_legacy_resource_location"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        "ALTER TABLE request_engine.resource_location_assignments "
        "DROP CONSTRAINT resource_location_assignments_no_overlap"
    )
    op.execute(
        """
        ALTER TABLE request_engine.resource_location_assignments
        ADD CONSTRAINT resource_location_assignments_no_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            resource_id WITH =,
            effective_during WITH &&
        )
        """
    )
    op.execute("RESET ROLE")


def downgrade() -> None:
    raise RuntimeError("Resource assignment exclusivity hardening is not reversible")
