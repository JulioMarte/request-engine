"""Separate platform-configuration reads from the control runtime role.

Revision ID: 0081_platform_config_read
Revises: 0080_platform_config_governance

P7-C routes administrative reads through the dedicated platform-read login and
mutations through request_platform_control. The read projections are owned by
the private BYPASSRLS read definer, not by the write/control definer. The shared
actor assertion remains control-owned but is executable only by the read
definer for these reviewed projections; runtime logins cannot invoke it
directly.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0081_platform_config_read"
down_revision: str | Sequence[str] | None = "0080_platform_config_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_READ_DEFINER = "request_platform_definer"
_CONTROL_RUNTIME = "request_platform_control"
_ACTOR_HELPER = "request_platform.assert_platform_configuration_actor(text)"
_READ_FUNCTIONS = (
    "request_platform.read_platform_configuration_revisions(text)",
    "request_platform.read_platform_secret_binding(uuid)",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")

    op.execute(
        f"""
        GRANT SELECT (
            id,
            configuration_kind,
            provider_kind,
            revision,
            configuration,
            secret_binding_id,
            state,
            created_by_principal_id,
            created_at,
            validated_at,
            activated_at,
            disabled_at
        )
        ON request_engine.platform_configuration_revisions
        TO {_READ_DEFINER};

        GRANT SELECT (
            id,
            purpose,
            backend,
            backend_version,
            status,
            revision,
            created_at,
            rotated_at,
            revoked_at
        )
        ON request_engine.platform_secret_bindings
        TO {_READ_DEFINER};

        GRANT EXECUTE ON FUNCTION {_ACTOR_HELPER}
        TO {_READ_DEFINER};

        GRANT USAGE, CREATE ON SCHEMA request_platform
        TO {_READ_DEFINER};
        """
    )

    for signature in _READ_FUNCTIONS:
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {_READ_DEFINER}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"REVOKE EXECUTE ON FUNCTION {signature} FROM {_CONTROL_RUNTIME}")

    op.execute(f"REVOKE CREATE ON SCHEMA request_platform FROM {_READ_DEFINER}")


def downgrade() -> None:
    raise RuntimeError(
        "Platform configuration read/write separation is security hardening; roll forward"
    )
