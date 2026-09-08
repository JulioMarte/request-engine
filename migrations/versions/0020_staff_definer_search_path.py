"""Harden Staff SECURITY DEFINER search paths.

Revision ID: 0020_staff_definer_path
Revises: 0019_staff_membership
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_staff_definer_path"
down_revision: str | Sequence[str] | None = "0019_staff_membership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_STAFF_DEFINERS = (
    ("request_engine.seed_root_staff_membership()", "pg_catalog, request_engine, request_auth, pg_temp"),
    ("request_engine.assert_staff_manager(text)", "pg_catalog, request_engine, pg_temp"),
    ("request_engine.assert_other_tenant_controller(uuid)", "pg_catalog, request_engine, pg_temp"),
    (
        "request_engine.invite_native_staff(uuid, uuid, uuid, uuid, uuid, uuid, text)",
        "pg_catalog, request_engine, request_auth, pg_temp",
    ),
    (
        "request_engine.transition_staff_membership(uuid, bigint, text, text)",
        "pg_catalog, request_engine, request_auth, pg_temp",
    ),
    (
        "request_engine.replace_staff_authority(uuid, bigint, text[], text)",
        "pg_catalog, request_engine, pg_temp",
    ),
)

_PREVIOUS_PATHS = (
    ("request_engine.seed_root_staff_membership()", "pg_catalog, request_engine, request_auth"),
    ("request_engine.assert_staff_manager(text)", "pg_catalog, request_engine"),
    ("request_engine.assert_other_tenant_controller(uuid)", "pg_catalog, request_engine"),
    (
        "request_engine.invite_native_staff(uuid, uuid, uuid, uuid, uuid, uuid, text)",
        "pg_catalog, request_engine, request_auth",
    ),
    (
        "request_engine.transition_staff_membership(uuid, bigint, text, text)",
        "pg_catalog, request_engine, request_auth",
    ),
    (
        "request_engine.replace_staff_authority(uuid, bigint, text[], text)",
        "pg_catalog, request_engine",
    ),
)


def _apply(paths: tuple[tuple[str, str], ...]) -> None:
    for signature, search_path in paths:
        op.execute(f"ALTER FUNCTION {signature} SET search_path TO {search_path}")


def upgrade() -> None:
    _apply(_STAFF_DEFINERS)


def downgrade() -> None:
    _apply(_PREVIOUS_PATHS)
