"""Add S0d federated Party identity adoption.

Revision ID: 0030_s0d_federated_identity
Revises: 0029_f7_same_day_triage
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from migrations.s0d_steps import (
    step_0030_hardening,
    step_0030_profile_provenance,
    step_0030_tables,
)

revision: str = "0030_s0d_federated_identity"
down_revision: str | Sequence[str] | None = "0029_f7_same_day_triage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    step_0030_tables.upgrade()
    step_0030_profile_provenance.upgrade()
    step_0030_hardening.upgrade()


def downgrade() -> None:
    raise RuntimeError("0030 introduces authoritative federated Party identity adoption")
