"""Separate platform-configuration reads from the control runtime role.

Revision ID: 0081_platform_config_read_boundary
Revises: 0080_platform_config_governance

P7-C routes administrative reads through the dedicated platform-read login and
mutations through request_platform_control. 0080 initially granted every reviewed
P7 function to the control runtime while the HTTP surface did not yet exist.
This forward migration removes the two read projections from that write role;
deployment-specific read logins receive EXECUTE explicitly at composition time.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0081_platform_config_read_boundary"
down_revision: str | Sequence[str] | None = "0080_platform_config_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READ_FUNCTIONS = (
    "request_platform.read_platform_configuration_revisions(text)",
    "request_platform.read_platform_secret_binding(uuid)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for signature in _READ_FUNCTIONS:
        op.execute(
            f"REVOKE EXECUTE ON FUNCTION {signature} FROM request_platform_control"
        )


def downgrade() -> None:
    raise RuntimeError(
        "Platform configuration read/write separation is security hardening; roll forward"
    )
