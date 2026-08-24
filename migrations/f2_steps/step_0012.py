"""Harden F2 publication visibility lifecycle and final authority grants.

Revision ID: 0012_f2_public_projection_hardening
Revises: 0011_f2_public_projection
Create Date: 2026-08-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_f2_public_projection_hardening"
down_revision: str | Sequence[str] | None = "0011_f2_public_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

CREATE OR REPLACE FUNCTION request_engine.guard_f2_publication_lifecycle()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id <> NEW.organization_id
       OR OLD.offering_id <> NEW.offering_id
       OR OLD.location_id <> NEW.location_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.effective_during <> NEW.effective_during
       OR OLD.provider_visibility <> NEW.provider_visibility THEN
        RAISE EXCEPTION
            'DiscoveryPublication scope/effective interval/visibility cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked DiscoveryPublication cannot be reactivated'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

RESET ROLE;
RESET search_path;

-- Reassert the taxonomy authority boundary at the consolidated F2 head. Function
-- ACLs can be broadened by schema/default privilege evolution after the original
-- definition; merge evidence must prove the final deployed state, not only the
-- ACL at the point where the function was first created.
REVOKE ALL ON FUNCTION
    request_admin.create_service_classification(text, text, text, text),
    request_admin.retire_service_classification(uuid, bigint, text, text)
FROM PUBLIC, request_engine_app, request_engine_worker, request_engine_discovery;
GRANT EXECUTE ON FUNCTION
    request_admin.create_service_classification(text, text, text, text),
    request_admin.retire_service_classification(uuid, bigint, text, text)
TO request_engine_admin;
"""


def upgrade() -> None:
    op.execute(_SQL)


def downgrade() -> None:
    raise RuntimeError("0012 preserves immutable F2 provider visibility")
