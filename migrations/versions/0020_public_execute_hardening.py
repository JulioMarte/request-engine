"""Close the post-baseline privilege drift in application schemas.

The V3 privilege hardening established three fail-closed rules that later
feature migrations (F2-F5) did not consistently restate for the objects they
created:

1. no application-schema function is executable by ``public``;
2. every SECURITY DEFINER function is owned by a controlled non-login role
   (``request_engine_schema_owner``, or ``request_engine_admin`` for the
   accepted F2 cross-tenant definer-mediated pattern) and pinned to
   ``pg_catalog, request_engine, pg_temp``;
3. runtime tables keep the accepted 022 runtime table privilege contract.

Trigger functions are invoked server-side and need no caller-facing EXECUTE;
callable primitives keep only their reviewed runtime-role grants. This
revision restates those rules in one idempotent reconciliation so the frozen
privilege catalogs and the migrated schema agree again.

Revision ID: 0020_public_execute_hardening
Revises: 0019_f5_change_storm_coalescing
Create Date: 2026-08-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_public_execute_hardening"
down_revision: str | Sequence[str] | None = "0019_f5_change_storm_coalescing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECONCILE = r"""
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_engine FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_read FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_cmd FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA request_admin FROM PUBLIC;

DO $hardening$
DECLARE
    fn record;
BEGIN
    FOR fn IN
        SELECT n.nspname AS schema_name,
               p.proname AS function_name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('request_engine', 'request_cmd', 'request_admin')
          AND p.prosecdef
          AND pg_get_userbyid(p.proowner) NOT IN (
              'request_engine_schema_owner', 'request_engine_admin'
          )
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %I.%I(%s) OWNER TO request_engine_schema_owner',
            fn.schema_name, fn.function_name, fn.identity_arguments
        );
    END LOOP;
END
$hardening$;

DO $search_path$
DECLARE
    fn record;
BEGIN
    FOR fn IN
        SELECT n.nspname AS schema_name,
               p.proname AS function_name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname IN ('request_engine', 'request_cmd', 'request_admin')
          AND p.prosecdef
          AND (
              p.proconfig IS NULL
              OR p.proconfig <> ARRAY[
                  'search_path=pg_catalog, request_engine, pg_temp'
              ]
          )
    LOOP
        EXECUTE format(
            'ALTER FUNCTION %I.%I(%s) '
            'SET search_path TO pg_catalog, request_engine, pg_temp',
            fn.schema_name, fn.function_name, fn.identity_arguments
        );
    END LOOP;
END
$search_path$;
"""


def upgrade() -> None:
    op.execute(_RECONCILE)


def downgrade() -> None:
    # Deny-by-default is the accepted security posture; restoring implicit
    # PUBLIC execute or weakened definer hardening is intentionally not
    # supported.
    pass
