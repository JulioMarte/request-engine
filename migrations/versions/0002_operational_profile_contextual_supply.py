"""Add F1 operational profile and contextual supply foundation.

Revision ID: 0002_operational_profile_contextual_supply
Revises: 0001_initial
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op
from psycopg import ClientCursor, sql

revision: str = "0002_operational_profile_contextual_supply"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE_SQL = r"""
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- ---------------------------------------------------------------------------
-- Existing aggregate extensions
-- ---------------------------------------------------------------------------

ALTER TABLE request_engine.organizations
    ADD COLUMN legal_name text,
    ADD COLUMN default_timezone text,
    ADD COLUMN default_locale text,
    ADD COLUMN default_currency text,
    ADD COLUMN operational_status text NOT NULL DEFAULT 'active',
    ADD CONSTRAINT organizations_legal_name_ck
        CHECK (legal_name IS NULL OR btrim(legal_name) <> ''),
    ADD CONSTRAINT organizations_default_timezone_ck
        CHECK (default_timezone IS NULL OR btrim(default_timezone) <> ''),
    ADD CONSTRAINT organizations_default_locale_ck
        CHECK (default_locale IS NULL OR btrim(default_locale) <> ''),
    ADD CONSTRAINT organizations_default_currency_ck
        CHECK (default_currency IS NULL OR default_currency ~ '^[A-Z]{3}$'),
    ADD CONSTRAINT organizations_operational_status_ck
        CHECK (operational_status IN ('active', 'inactive'));

ALTER TABLE request_engine.locations
    ADD COLUMN address_line1 text,
    ADD COLUMN address_line2 text,
    ADD COLUMN locality text,
    ADD COLUMN administrative_area text,
    ADD COLUMN postal_code text,
    ADD COLUMN country_code text,
    ADD COLUMN latitude numeric(9,6),
    ADD COLUMN longitude numeric(9,6),
    ADD COLUMN geocoding_source text,
    ADD COLUMN geocoded_at timestamptz,
    ADD COLUMN operational_revision bigint NOT NULL DEFAULT 1,
    ADD CONSTRAINT locations_coordinate_pair_ck
        CHECK ((latitude IS NULL) = (longitude IS NULL)),
    ADD CONSTRAINT locations_latitude_ck
        CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    ADD CONSTRAINT locations_longitude_ck
        CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    ADD CONSTRAINT locations_country_code_ck
        CHECK (country_code IS NULL OR country_code ~ '^[A-Z]{2}$'),
    ADD CONSTRAINT locations_address_line1_ck
        CHECK (address_line1 IS NULL OR btrim(address_line1) <> ''),
    ADD CONSTRAINT locations_operational_revision_ck
        CHECK (operational_revision > 0);

ALTER TABLE request_engine.capacity_claims
    ADD COLUMN resource_location_assignment_id uuid;

-- ---------------------------------------------------------------------------
-- Public operational profile surfaces
-- ---------------------------------------------------------------------------

CREATE TABLE request_engine.organization_public_contact_endpoints (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL REFERENCES request_engine.organizations(id),
    channel text NOT NULL,
    normalized_value text NOT NULL,
    label text,
    active boolean NOT NULL DEFAULT true,
    is_public boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, channel, normalized_value),
    CHECK (channel IN ('phone', 'whatsapp', 'email')),
    CHECK (normalized_value <> ''),
    CHECK (label IS NULL OR btrim(label) <> '')
);

CREATE TABLE request_engine.location_public_contact_endpoints (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    label text,
    active boolean NOT NULL DEFAULT true,
    is_public boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, location_id, channel, normalized_value),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (channel IN ('phone', 'whatsapp', 'email')),
    CHECK (normalized_value <> ''),
    CHECK (label IS NULL OR btrim(label) <> '')
);

-- ---------------------------------------------------------------------------
-- Location operational availability
-- ---------------------------------------------------------------------------

CREATE TABLE request_engine.location_operational_hours (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    weekday smallint NOT NULL,
    local_start time NOT NULL,
    local_end time NOT NULL,
    valid_from date,
    valid_until date,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (weekday BETWEEN 0 AND 6),
    CHECK (local_start < local_end),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);

CREATE INDEX location_operational_hours_lookup_idx
    ON request_engine.location_operational_hours
       (organization_id, location_id, weekday, active);

CREATE TABLE request_engine.location_hours_exceptions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (exception_kind IN ('available', 'unavailable')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during)),
    CONSTRAINT location_hours_exceptions_no_active_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            location_id WITH =,
            during WITH &&
        ) WHERE (active)
);

-- ---------------------------------------------------------------------------
-- Resource-at-Location supply
-- ---------------------------------------------------------------------------

CREATE TABLE request_engine.resource_location_assignments (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    effective_during tstzrange NOT NULL,
    status text NOT NULL DEFAULT 'active',
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_id)
        REFERENCES request_engine.resources (organization_id, id),
    FOREIGN KEY (organization_id, location_id)
        REFERENCES request_engine.locations (organization_id, id),
    CHECK (status IN ('active', 'retired')),
    CHECK (NOT isempty(effective_during)),
    CHECK (lower(effective_during) IS NOT NULL),
    CHECK (lower_inc(effective_during) AND NOT upper_inc(effective_during)),
    CHECK (revision > 0),
    CONSTRAINT resource_location_assignments_no_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            resource_id WITH =,
            location_id WITH =,
            effective_during WITH &&
        )
);

CREATE INDEX resource_location_assignments_resource_idx
    ON request_engine.resource_location_assignments
       (organization_id, resource_id, status);
CREATE INDEX resource_location_assignments_location_idx
    ON request_engine.resource_location_assignments
       (organization_id, location_id, status);

CREATE TABLE request_engine.resource_location_availability (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid NOT NULL,
    weekday smallint NOT NULL,
    local_start time NOT NULL,
    local_end time NOT NULL,
    valid_from date,
    valid_until date,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_location_assignment_id)
        REFERENCES request_engine.resource_location_assignments (organization_id, id),
    CHECK (weekday BETWEEN 0 AND 6),
    CHECK (local_start < local_end),
    CHECK (valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from)
);

CREATE INDEX resource_location_availability_lookup_idx
    ON request_engine.resource_location_availability
       (organization_id, resource_location_assignment_id, weekday, active);

CREATE TABLE request_engine.resource_location_schedule_exceptions (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_location_assignment_id)
        REFERENCES request_engine.resource_location_assignments (organization_id, id),
    CHECK (exception_kind IN ('available', 'unavailable')),
    CHECK (NOT isempty(during)),
    CHECK (lower(during) IS NOT NULL AND upper(during) IS NOT NULL),
    CHECK (lower_inc(during) AND NOT upper_inc(during)),
    CONSTRAINT resource_location_exceptions_no_active_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            resource_location_assignment_id WITH =,
            during WITH &&
        ) WHERE (active)
);

-- ---------------------------------------------------------------------------
-- Narrow deterministic commercial terms
-- ---------------------------------------------------------------------------

CREATE TABLE request_engine.offering_version_booking_terms (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    amount numeric(20,6) NOT NULL,
    currency text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    UNIQUE (organization_id, offering_version_id),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    CHECK (amount >= 0),
    CHECK (currency ~ '^[A-Z]{3}$')
);

CREATE TABLE request_engine.booking_context_terms (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    effective_during tstzrange NOT NULL,
    amount numeric(20,6),
    currency text,
    planned_duration_minutes integer,
    bookable boolean NOT NULL DEFAULT true,
    active boolean NOT NULL DEFAULT true,
    revision bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, resource_location_assignment_id)
        REFERENCES request_engine.resource_location_assignments (organization_id, id),
    FOREIGN KEY (organization_id, offering_version_id)
        REFERENCES request_engine.offering_versions (organization_id, id),
    CHECK ((amount IS NULL) = (currency IS NULL)),
    CHECK (amount IS NULL OR amount >= 0),
    CHECK (currency IS NULL OR currency ~ '^[A-Z]{3}$'),
    CHECK (planned_duration_minutes IS NULL OR planned_duration_minutes > 0),
    CHECK (amount IS NOT NULL OR planned_duration_minutes IS NOT NULL OR NOT bookable),
    CHECK (NOT isempty(effective_during)),
    CHECK (lower(effective_during) IS NOT NULL),
    CHECK (lower_inc(effective_during) AND NOT upper_inc(effective_during)),
    CHECK (revision > 0),
    CONSTRAINT booking_context_terms_no_active_overlap
        EXCLUDE USING gist (
            organization_id WITH =,
            resource_location_assignment_id WITH =,
            offering_version_id WITH =,
            effective_during WITH &&
        ) WHERE (active)
);

CREATE INDEX booking_context_terms_offering_idx
    ON request_engine.booking_context_terms
       (organization_id, offering_version_id, active);

-- ---------------------------------------------------------------------------
-- Historical commercial commitment
-- ---------------------------------------------------------------------------

CREATE TABLE request_engine.reservation_commercial_commitments (
    reservation_id uuid PRIMARY KEY,
    organization_id uuid NOT NULL,
    offering_version_booking_terms_id uuid,
    booking_context_terms_id uuid,
    amount numeric(20,6) NOT NULL,
    currency text NOT NULL,
    planned_duration_minutes integer NOT NULL,
    configuration_fingerprint text NOT NULL,
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (organization_id, reservation_id),
    FOREIGN KEY (organization_id, reservation_id)
        REFERENCES request_engine.reservations (organization_id, id),
    FOREIGN KEY (organization_id, offering_version_booking_terms_id)
        REFERENCES request_engine.offering_version_booking_terms (organization_id, id),
    FOREIGN KEY (organization_id, booking_context_terms_id)
        REFERENCES request_engine.booking_context_terms (organization_id, id),
    CHECK (amount >= 0),
    CHECK (currency ~ '^[A-Z]{3}$'),
    CHECK (planned_duration_minutes > 0),
    CHECK (configuration_fingerprint <> ''),
    CHECK (
        offering_version_booking_terms_id IS NOT NULL
        OR booking_context_terms_id IS NOT NULL
    )
);

ALTER TABLE request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_resource_location_assignment_fk
    FOREIGN KEY (organization_id, resource_location_assignment_id)
        REFERENCES request_engine.resource_location_assignments (organization_id, id);

CREATE INDEX capacity_claims_resource_location_assignment_idx
    ON request_engine.capacity_claims
       (organization_id, resource_location_assignment_id)
    WHERE resource_location_assignment_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Revision and scope guards
-- ---------------------------------------------------------------------------

CREATE FUNCTION request_engine.guard_location_operational_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_material_change boolean;
BEGIN
    v_material_change :=
        NEW.active IS DISTINCT FROM OLD.active
        OR NEW.timezone IS DISTINCT FROM OLD.timezone;

    IF v_material_change THEN
        IF NEW.operational_revision = OLD.operational_revision THEN
            NEW.operational_revision := OLD.operational_revision + 1;
        ELSIF NEW.operational_revision <> OLD.operational_revision + 1 THEN
            RAISE EXCEPTION 'Location operational_revision must advance exactly one step for a material availability change'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.operational_revision NOT IN (
        OLD.operational_revision,
        OLD.operational_revision + 1
    ) THEN
        RAISE EXCEPTION 'Location operational_revision cannot jump from % to %',
            OLD.operational_revision, NEW.operational_revision
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER locations_guard_operational_revision
BEFORE UPDATE ON request_engine.locations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_location_operational_revision();

CREATE FUNCTION request_engine.bump_location_operational_revision_from_child()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_org uuid;
    v_location uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.organization_id <> NEW.organization_id
        OR OLD.location_id <> NEW.location_id
    ) THEN
        RAISE EXCEPTION '% rows cannot move between Locations', TG_TABLE_NAME
            USING ERRCODE = '23514';
    END IF;

    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_location := OLD.location_id;
    ELSE
        v_org := NEW.organization_id;
        v_location := NEW.location_id;
    END IF;

    UPDATE request_engine.locations
       SET operational_revision = operational_revision + 1,
           updated_at = clock_timestamp()
     WHERE organization_id = v_org
       AND id = v_location;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Location % not found while changing operational availability', v_location
            USING ERRCODE = '23503';
    END IF;

    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE TRIGGER location_operational_hours_bump_location
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.location_operational_hours
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_location_operational_revision_from_child();

CREATE TRIGGER location_hours_exceptions_bump_location
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.location_hours_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_location_operational_revision_from_child();

CREATE FUNCTION request_engine.guard_resource_location_assignment()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.organization_id <> NEW.organization_id
           OR OLD.resource_id <> NEW.resource_id
           OR OLD.location_id <> NEW.location_id THEN
            RAISE EXCEPTION 'ResourceLocationAssignment identity cannot be retargeted'
                USING ERRCODE = '23514';
        END IF;

        IF OLD.status = 'retired' AND NEW.status <> 'retired' THEN
            RAISE EXCEPTION 'retired ResourceLocationAssignment % cannot be reactivated', OLD.id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER resource_location_assignments_guard
BEFORE UPDATE ON request_engine.resource_location_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_resource_location_assignment();

CREATE TRIGGER resource_location_assignments_revision_step
BEFORE UPDATE ON request_engine.resource_location_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE FUNCTION request_engine.bump_resource_availability_from_assignment()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_org uuid;
    v_resource uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_org := OLD.organization_id;
        v_resource := OLD.resource_id;
    ELSE
        v_org := NEW.organization_id;
        v_resource := NEW.resource_id;
    END IF;

    UPDATE request_engine.resources
       SET availability_revision = availability_revision + 1,
           updated_at = clock_timestamp()
     WHERE organization_id = v_org
       AND id = v_resource;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % not found while changing contextual assignment', v_resource
            USING ERRCODE = '23503';
    END IF;

    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE TRIGGER resource_location_assignments_bump_resource
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.resource_location_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_availability_from_assignment();

CREATE FUNCTION request_engine.bump_resource_availability_from_assignment_child()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_org uuid;
    v_assignment uuid;
    v_resource uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.organization_id <> NEW.organization_id
        OR OLD.resource_location_assignment_id <> NEW.resource_location_assignment_id
    ) THEN
        RAISE EXCEPTION '% rows cannot move between ResourceLocationAssignments', TG_TABLE_NAME
            USING ERRCODE = '23514';
    END IF;

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
        RAISE EXCEPTION 'ResourceLocationAssignment % not found while changing availability', v_assignment
            USING ERRCODE = '23503';
    END IF;

    UPDATE request_engine.resources
       SET availability_revision = availability_revision + 1,
           updated_at = clock_timestamp()
     WHERE organization_id = v_org
       AND id = v_resource;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % not found while changing contextual availability', v_resource
            USING ERRCODE = '23503';
    END IF;

    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE TRIGGER resource_location_availability_bump_resource
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.resource_location_availability
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_availability_from_assignment_child();

CREATE TRIGGER resource_location_exceptions_bump_resource
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.resource_location_schedule_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_availability_from_assignment_child();

CREATE FUNCTION request_engine.guard_booking_context_terms_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.organization_id <> NEW.organization_id
       OR OLD.resource_location_assignment_id <> NEW.resource_location_assignment_id
       OR OLD.offering_version_id <> NEW.offering_version_id THEN
        RAISE EXCEPTION 'BookingContextTerms scope cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$function$;

CREATE TRIGGER booking_context_terms_guard_scope
BEFORE UPDATE ON request_engine.booking_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_booking_context_terms_scope();

CREATE TRIGGER booking_context_terms_revision_step
BEFORE UPDATE ON request_engine.booking_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();

CREATE TRIGGER organization_public_contact_endpoints_touch
BEFORE UPDATE ON request_engine.organization_public_contact_endpoints
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE TRIGGER location_public_contact_endpoints_touch
BEFORE UPDATE ON request_engine.location_public_contact_endpoints
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE TRIGGER location_hours_exceptions_touch
BEFORE UPDATE ON request_engine.location_hours_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE TRIGGER resource_location_assignments_touch
BEFORE UPDATE ON request_engine.resource_location_assignments
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE TRIGGER resource_location_exceptions_touch
BEFORE UPDATE ON request_engine.resource_location_schedule_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE TRIGGER booking_context_terms_touch
BEFORE UPDATE ON request_engine.booking_context_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

CREATE TRIGGER offering_version_booking_terms_immutable
BEFORE UPDATE OR DELETE ON request_engine.offering_version_booking_terms
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER reservation_commercial_commitments_append_only
BEFORE UPDATE OR DELETE ON request_engine.reservation_commercial_commitments
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

-- ---------------------------------------------------------------------------
-- CapacityClaim contextual assignment backstop
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION request_engine.guard_capacity_claim()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_capacity_model text;
    v_capacity_units integer;
    v_resource_active boolean;
    v_resource_location uuid;
    v_owner_offering_version uuid;
    v_owner_during tstzrange;
    v_owner_location uuid;
    v_requirement_offering_version uuid;
    v_required_capability uuid;
    v_required_quantity integer;
    v_other_quantity bigint;
    v_other_count bigint;
    v_assignment_resource uuid;
    v_assignment_location uuid;
    v_assignment_during tstzrange;
    v_assignment_status text;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT r.capacity_model, r.capacity_units, r.active, r.location_id
      INTO v_capacity_model, v_capacity_units, v_resource_active, v_resource_location
      FROM request_engine.resources r
     WHERE r.organization_id = NEW.organization_id
       AND r.id = NEW.resource_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % does not exist for capacity claim', NEW.resource_id
            USING ERRCODE = '23503';
    END IF;

    IF NOT v_resource_active THEN
        RAISE EXCEPTION 'Resource % is inactive', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reservation_id IS NOT NULL THEN
        SELECT r.offering_version_id, r.during, r.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.reservations r
         WHERE r.organization_id = NEW.organization_id
           AND r.id = NEW.reservation_id
           AND r.status = 'confirmed';

        IF NOT FOUND THEN
            RAISE EXCEPTION 'active reservation claim requires confirmed Reservation %', NEW.reservation_id
                USING ERRCODE = '23514';
        END IF;
    ELSE
        IF NEW.hold_id IS NULL THEN
            RAISE EXCEPTION 'active hold claim requires CapacityHold'
                USING ERRCODE = '23514';
        END IF;

        SELECT h.offering_version_id, h.during, h.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.capacity_holds h
         WHERE h.organization_id = NEW.organization_id
           AND h.id = NEW.hold_id
           AND h.status = 'active'
           AND h.expires_at > clock_timestamp();

        IF NOT FOUND THEN
            RAISE EXCEPTION 'active hold claim requires live, unexpired CapacityHold %', NEW.hold_id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.during <> v_owner_during THEN
        RAISE EXCEPTION 'CapacityClaim interval must equal its Hold/Reservation interval'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.resource_location_assignment_id IS NOT NULL THEN
        SELECT a.resource_id, a.location_id, a.effective_during, a.status
          INTO v_assignment_resource, v_assignment_location, v_assignment_during, v_assignment_status
          FROM request_engine.resource_location_assignments a
         WHERE a.organization_id = NEW.organization_id
           AND a.id = NEW.resource_location_assignment_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION 'ResourceLocationAssignment % does not exist for capacity claim',
                NEW.resource_location_assignment_id
                USING ERRCODE = '23503';
        END IF;

        IF v_assignment_resource <> NEW.resource_id THEN
            RAISE EXCEPTION 'CapacityClaim ResourceLocationAssignment belongs to a different Resource'
                USING ERRCODE = '23514';
        END IF;

        IF v_assignment_status <> 'active' THEN
            RAISE EXCEPTION 'CapacityClaim ResourceLocationAssignment is not active'
                USING ERRCODE = '23514';
        END IF;

        IF v_owner_location IS NULL OR v_owner_location <> v_assignment_location THEN
            RAISE EXCEPTION 'CapacityClaim ResourceLocationAssignment belongs to a different Location than the Hold/Reservation'
                USING ERRCODE = '23514';
        END IF;

        IF NOT (v_assignment_during @> NEW.during) THEN
            RAISE EXCEPTION 'CapacityClaim interval is outside ResourceLocationAssignment effective range'
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_owner_location IS NOT NULL
       AND v_resource_location IS NOT NULL
       AND v_owner_location <> v_resource_location THEN
        RAISE EXCEPTION 'Resource % belongs to a different Location than the Hold/Reservation', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    SELECT rr.offering_version_id, rr.capability_id, rr.quantity
      INTO v_requirement_offering_version, v_required_capability, v_required_quantity
      FROM request_engine.offering_resource_requirements rr
     WHERE rr.organization_id = NEW.organization_id
       AND rr.id = NEW.requirement_id;

    IF NOT FOUND OR v_requirement_offering_version <> v_owner_offering_version THEN
        RAISE EXCEPTION 'CapacityClaim requirement does not belong to the owner OfferingVersion'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.quantity <> v_required_quantity THEN
        RAISE EXCEPTION 'CapacityClaim quantity % does not satisfy requirement quantity %', NEW.quantity, v_required_quantity
            USING ERRCODE = '23514';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM request_engine.resource_capability_assignments a
         WHERE a.organization_id = NEW.organization_id
           AND a.resource_id = NEW.resource_id
           AND a.capability_id = v_required_capability
    ) THEN
        RAISE EXCEPTION 'Resource % does not satisfy required capability', NEW.resource_id
            USING ERRCODE = '23514';
    END IF;

    SELECT COALESCE(sum(c.quantity), 0), count(*)
      INTO v_other_quantity, v_other_count
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
     WHERE c.organization_id = NEW.organization_id
       AND c.resource_id = NEW.resource_id
       AND c.status = 'active'
       AND c.id <> NEW.id
       AND c.during && NEW.during
       AND (
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed') OR
           (c.reservation_id IS NULL AND h.status = 'active' AND h.expires_at > clock_timestamp())
       );

    IF v_capacity_model = 'exclusive' AND v_other_count > 0 THEN
        RAISE EXCEPTION 'exclusive Resource % has overlapping live capacity', NEW.resource_id
            USING ERRCODE = '23P01';
    END IF;

    IF v_capacity_model = 'units' AND v_other_quantity + NEW.quantity > v_capacity_units THEN
        RAISE EXCEPTION 'Resource % capacity exceeded: requested %, live %, capacity %',
            NEW.resource_id, NEW.quantity, v_other_quantity, v_capacity_units
            USING ERRCODE = '23P01';
    END IF;

    RETURN NEW;
END
$function$;

-- ---------------------------------------------------------------------------
-- RLS defense in depth for new tenant-owned state
-- ---------------------------------------------------------------------------

ALTER TABLE request_engine.organization_public_contact_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.organization_public_contact_endpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY organization_public_contact_endpoints_tenant_policy
    ON request_engine.organization_public_contact_endpoints
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.location_public_contact_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.location_public_contact_endpoints FORCE ROW LEVEL SECURITY;
CREATE POLICY location_public_contact_endpoints_tenant_policy
    ON request_engine.location_public_contact_endpoints
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.location_operational_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.location_operational_hours FORCE ROW LEVEL SECURITY;
CREATE POLICY location_operational_hours_tenant_policy
    ON request_engine.location_operational_hours
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.location_hours_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.location_hours_exceptions FORCE ROW LEVEL SECURITY;
CREATE POLICY location_hours_exceptions_tenant_policy
    ON request_engine.location_hours_exceptions
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.resource_location_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.resource_location_assignments FORCE ROW LEVEL SECURITY;
CREATE POLICY resource_location_assignments_tenant_policy
    ON request_engine.resource_location_assignments
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.resource_location_availability ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.resource_location_availability FORCE ROW LEVEL SECURITY;
CREATE POLICY resource_location_availability_tenant_policy
    ON request_engine.resource_location_availability
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.resource_location_schedule_exceptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.resource_location_schedule_exceptions FORCE ROW LEVEL SECURITY;
CREATE POLICY resource_location_schedule_exceptions_tenant_policy
    ON request_engine.resource_location_schedule_exceptions
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.offering_version_booking_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.offering_version_booking_terms FORCE ROW LEVEL SECURITY;
CREATE POLICY offering_version_booking_terms_tenant_policy
    ON request_engine.offering_version_booking_terms
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.booking_context_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.booking_context_terms FORCE ROW LEVEL SECURITY;
CREATE POLICY booking_context_terms_tenant_policy
    ON request_engine.booking_context_terms
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

ALTER TABLE request_engine.reservation_commercial_commitments ENABLE ROW LEVEL SECURITY;
ALTER TABLE request_engine.reservation_commercial_commitments FORCE ROW LEVEL SECURITY;
CREATE POLICY reservation_commercial_commitments_tenant_policy
    ON request_engine.reservation_commercial_commitments
    USING (organization_id = request_engine.current_organization_id())
    WITH CHECK (organization_id = request_engine.current_organization_id());

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
    request_engine.reservation_commercial_commitments
FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE ON TABLE
    request_engine.organization_public_contact_endpoints,
    request_engine.location_public_contact_endpoints,
    request_engine.location_operational_hours,
    request_engine.location_hours_exceptions,
    request_engine.resource_location_assignments,
    request_engine.resource_location_availability,
    request_engine.resource_location_schedule_exceptions,
    request_engine.booking_context_terms
TO request_engine_app, request_engine_worker;

GRANT SELECT, INSERT ON TABLE
    request_engine.offering_version_booking_terms,
    request_engine.reservation_commercial_commitments
TO request_engine_app, request_engine_worker;

GRANT ALL PRIVILEGES ON TABLE
    request_engine.organization_public_contact_endpoints,
    request_engine.location_public_contact_endpoints,
    request_engine.location_operational_hours,
    request_engine.location_hours_exceptions,
    request_engine.resource_location_assignments,
    request_engine.resource_location_availability,
    request_engine.resource_location_schedule_exceptions,
    request_engine.offering_version_booking_terms,
    request_engine.booking_context_terms,
    request_engine.reservation_commercial_commitments
TO request_engine_admin;

RESET ROLE;
RESET search_path;
"""


def upgrade() -> None:
    context = op.get_context()
    if context.as_sql:
        raise RuntimeError("F1 migration requires Alembic online mode")

    bind = op.get_bind()
    if bind is None:
        raise RuntimeError("F1 migration requires a live database connection")

    driver_connection = bind.connection.driver_connection
    if driver_connection is None:
        raise RuntimeError("F1 migration requires the live psycopg driver connection")

    # Keep the migration as one reviewed PostgreSQL batch. ClientCursor forces
    # psycopg's simple-query protocol for the multi-statement DDL/function body.
    with ClientCursor(driver_connection) as cursor:
        cursor.execute(sql.SQL(_UPGRADE_SQL))

    bind.exec_driver_sql("RESET ALL")


def downgrade() -> None:
    raise RuntimeError(
        "0002_operational_profile_contextual_supply may contain durable F1 "
        "commercial/configuration provenance and is intentionally irreversible"
    )
