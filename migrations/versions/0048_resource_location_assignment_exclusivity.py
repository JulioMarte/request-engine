"""Enforce one temporal location assignment per Resource.

Revision ID: 0048_assignment_exclusivity
Revises: 0047_remove_waitlist_index
Create Date: 2026-09-05

The F1 exclusion key included location_id, so the same Resource could hold
simultaneous assignments at different Locations. Location is the value being
assigned, not part of the identity whose time ranges must be exclusive.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0048_assignment_exclusivity"
down_revision: str | Sequence[str] | None = "0047_remove_waitlist_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET ROLE request_engine_schema_owner")
    op.execute(
        """
        ALTER TABLE request_engine.resource_location_assignments
            DROP CONSTRAINT resource_location_assignments_no_overlap,
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
    raise RuntimeError("Resource cross-location exclusivity hardening is not reversible")
