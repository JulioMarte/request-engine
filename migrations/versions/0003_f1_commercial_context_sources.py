"""Add multi-source contextual commercial provenance and write serialization.

Revision ID: 0003_f1_context_sources
Revises: 0002_f1_supply
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_f1_context_sources"
down_revision: str | Sequence[str] | None = "0002_f1_supply"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- Commercial configuration must linearize with authoritative booking without
-- reusing Resource availability_revision as a broad commercial change token.
CREATE FUNCTION request_engine.lock_booking_context_terms_resource()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_org uuid;
    v_assignment uuid;
    v_resource uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_assignment := OLD.resource_location_assignment_id;
    ELSE
        v_org := NEW.organization_id;
        v_assignment := NEW.resource_location_assignment_id;
    END IF;

    SELECT resource_id
      INTO v_resource
      FROM request_engine.resource_location_assignments
     WHERE organization_id = v_org
       AND id = v_assignment;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ResourceLocationAssignment % not found while changing booking terms',
            v_assignment USING ERRCODE = '23503';
    END IF;

    PERFORM 1
      FROM request_engine.resources
     WHERE organization_id = v_org
       AND id = v_resource
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % not found while changing booking terms', v_resource
            USING ERRCODE = '23503';
    END IF;

    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE TRIGGER booking_context_terms_lock_resource
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.booking_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.lock_booking_context_terms_resource();

CREATE FUNCTION request_engine.lock_offering_version_booking_terms_root()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_org uuid;
    v_offering_version uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_offering_version := OLD.offering_version_id;
    ELSE
        v_org := NEW.organization_id;
        v_offering_version := NEW.offering_version_id;
    END IF;

    PERFORM 1
      FROM request_engine.offering_versions
     WHERE organization_id = v_org
       AND id = v_offering_version
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'OfferingVersion % not found while changing base booking terms',
            v_offering_version USING ERRCODE = '23503';
    END IF;

    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE TRIGGER offering_version_booking_terms_lock_root
BEFORE INSERT OR DELETE ON request_engine.offering_version_booking_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.lock_offering_version_booking_terms_root();

CREATE TABLE request_engine.reservation_commercial_commitment_context_terms (
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    booking_context_terms_id uuid NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (organization_id, reservation_id, booking_context_terms_id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservation_commercial_commitments (
            organization_id, reservation_id
        ),
    FOREIGN KEY (organization_id, booking_context_terms_id)
        REFERENCES request_engine.booking_context_terms (organization_id, id)
);

COMMENT ON TABLE request_engine.reservation_commercial_commitment_context_terms IS
    'Append-only provenance linking one committed Reservation commercial fact to every exact contextual term row that contributed to its resolution.';

CREATE TRIGGER reservation_commercial_commitment_context_terms_append_only
BEFORE UPDATE OR DELETE
ON request_engine.reservation_commercial_commitment_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

ALTER TABLE request_engine.reservation_commercial_commitment_context_terms
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.reservation_commercial_commitment_context_terms
    FORCE ROW LEVEL SECURITY;

CREATE POLICY reservation_commercial_commitment_context_terms_tenant_isolation
ON request_engine.reservation_commercial_commitment_context_terms
USING (organization_id = request_engine.current_organization_id())
WITH CHECK (organization_id = request_engine.current_organization_id());

REVOKE ALL ON request_engine.reservation_commercial_commitment_context_terms FROM PUBLIC;
GRANT SELECT, INSERT
ON request_engine.reservation_commercial_commitment_context_terms
TO request_engine_app, request_engine_worker;
GRANT ALL PRIVILEGES
ON request_engine.reservation_commercial_commitment_context_terms
TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    raise RuntimeError(
        "F1 commercial provenance and serialization are append-only production history"
    )
