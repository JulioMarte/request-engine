"""Allow the control-plane runtime provider to resolve ACTIVE managed config.

Revision ID: 0089_control_runtime_config
Revises: 0088_secret_runtime_notify

Verified recovery-address delivery happens inside the private control process.
Grant that already least-privilege control login the same narrow ACTIVE runtime
projection used by workers; it still receives only non-secret configuration and
the opaque secret_id used by PlatformSecretStore.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0089_control_runtime_config"
down_revision: str | Sequence[str] | None = "0088_secret_runtime_notify"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIGNATURE = "request_platform.read_active_platform_runtime_configuration(text)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO request_platform_control")


def downgrade() -> None:
    raise RuntimeError("Control runtime configuration projection is accepted surface; roll forward")
