"""Consolidate F2 geospatial cross-tenant discovery.

Revision ID: 0004_f2_discovery
Revises: 0003_f1_runtime_acl
Create Date: 2026-08-23

F2 was developed as revisions 0004-0012 before production. The SQL-bearing
steps are preserved under migrations/f2_steps and executed here in the exact
order that passed the full current-product and compatibility proof. Alembic
therefore exposes one F2 revision without rewriting proven schema semantics.
"""

from collections.abc import Sequence

from migrations.f2_steps import (
    step_0004,
    step_0005,
    step_0006,
    step_0007,
    step_0008,
    step_0009,
    step_0010,
    step_0011,
    step_0012,
)

revision: str = "0004_f2_discovery"
down_revision: str | Sequence[str] | None = "0003_f1_runtime_acl"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STEPS = (
    step_0004,
    step_0005,
    step_0006,
    step_0007,
    step_0008,
    step_0009,
    step_0010,
    step_0011,
    step_0012,
)


def upgrade() -> None:
    for step in _STEPS:
        step.upgrade()


def downgrade() -> None:
    raise RuntimeError("0004 preserves the consolidated F2 production baseline")
