"""Harden F1 runtime privileges without extending frozen V3 surfaces.

Revision ID: 0005_f1_runtime_acl
Revises: 0004_f1_capacity_guard
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_f1_runtime_acl"
down_revision: str | Sequence[str] | None = "0004_f1_capacity_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- Fail closed for future F1 trigger/helper functions too. PostgreSQL's built-in
-- function default grants EXECUTE to PUBLIC unless the creating role has an
-- explicit default ACL that removes it.
ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner
    IN SCHEMA request_engine
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- The released V3 guard has an exact trigger inventory that is part of the
-- frozen V3 compatibility proof. F1 owns its own equivalent revision primitive
-- so new aggregates do not silently widen the released V3 catalog contract.
CREATE FUNCTION request_engine.guard_f1_exact_revision_step()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.revision = OLD.revision THEN
        NEW.revision := OLD.revision + 1;
    ELSIF NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION '% revision must advance exactly one step: old %, attempted %',
            TG_TABLE_NAME, OLD.revision, NEW.revision
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

DROP TRIGGER resource_location_assignments_revision_step
    ON request_engine.resource_location_assignments;
CREATE TRIGGER resource_location_assignments_revision_step
BEFORE UPDATE ON request_engine.resource_location_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f1_exact_revision_step();

DROP TRIGGER booking_context_terms_revision_step
    ON request_engine.booking_context_terms;
CREATE TRIGGER booking_context_terms_revision_step
BEFORE UPDATE ON request_engine.booking_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f1_exact_revision_step();

-- Trigger helpers are internal implementation details. Existing helpers were
-- created before the default ACL above, so close their inherited PUBLIC surface
-- explicitly as well.
REVOKE ALL ON FUNCTION
    request_engine.guard_location_operational_revision(),
    request_engine.bump_location_operational_revision_from_child(),
    request_engine.guard_resource_location_assignment(),
    request_engine.bump_resource_from_assignment(),
    request_engine.bump_resource_from_assignment_child(),
    request_engine.guard_booking_context_terms_scope(),
    request_engine.lock_booking_context_terms_resource(),
    request_engine.lock_offering_version_booking_terms_root(),
    request_engine.guard_capacity_claim_contextual_assignment(),
    request_engine.guard_f1_exact_revision_step()
FROM PUBLIC;

-- Production Worker Assembly deliberately separates worker-control database
-- authority from tenant-domain authority. F1 configuration and commercial
-- provenance are authoritative tenant-domain state, therefore the worker role
-- receives no direct relation privileges on them. Domain handlers use the
-- request_engine_app side of the established split instead.
REVOKE ALL ON TABLE
    request_engine.organization_public_contact_endpoints,
    request_engine.location_public_contact_endpoints,
    request_engine.location_operational_hours,
    request_engine.location_hours_exceptions,
    request_engine.resource_location_assignments,
    request_engine.resource_location_availability,
    request_engine.resource_location_schedule_exceptions,
    request_engine.offering_version_booking_terms,
    request_engine.booking_context_terms,
    request_engine.reservation_commercial_commitments,
    request_engine.reservation_commercial_commitment_context_terms
FROM request_engine_worker;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    raise RuntimeError("F1 runtime privilege hardening is append-only production history")
