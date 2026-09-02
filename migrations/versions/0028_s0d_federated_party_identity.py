"""Add S0d federated Party identity adoption.

Revision ID: 0028_s0d_federated_identity
Revises: 0027_s0c_party_admin_ids
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from migrations.s0d_steps import (
    step_0028_hardening,
    step_0028_profile_provenance,
    step_0028_tables,
)

revision: str = "0028_s0d_federated_identity"
down_revision: str | Sequence[str] | None = "0027_s0c_party_admin_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    step_0028_tables.upgrade()
    step_0028_profile_provenance.upgrade()
    step_0028_hardening.upgrade()


def downgrade() -> None:
    raise RuntimeError("0028 introduces authoritative federated Party identity adoption")
