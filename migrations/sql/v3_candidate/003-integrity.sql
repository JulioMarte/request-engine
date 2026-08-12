BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, pg_catalog;

-- ---------------------------------------------------------------------------
-- Lifecycle and immutable-history guards
-- ---------------------------------------------------------------------------

CREATE FUNCTION request_engine.guard_request_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.status IN ('completed', 'cancelled', 'failed') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'terminal Request % cannot transition from % to %', OLD.id, OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'open' AND NEW.status NOT IN ('open', 'completed', 'cancelled', 'failed') THEN
        RAISE EXCEPTION 'invalid Request transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status = 'completed' AND NEW.completed_at IS NULL THEN
        RAISE EXCEPTION 'completed Request % requires completed_at', NEW.id
            USING ERRCODE = '23514';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'Request revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER requests_guard_transition
BEFORE UPDATE ON request_engine.requests
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_request_transition();

CREATE FUNCTION request_engine.guard_reservation_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.status = 'cancelled' AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'cancelled Reservation % cannot transition to %', OLD.id, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'confirmed' AND NEW.status NOT IN ('confirmed', 'cancelled') THEN
        RAISE EXCEPTION 'invalid Reservation transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'Reservation revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER reservations_guard_transition
BEFORE UPDATE ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_transition();

CREATE FUNCTION request_engine.guard_hold_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF OLD.status IN ('consumed', 'released', 'expired') AND NEW.status <> OLD.status THEN
        RAISE EXCEPTION 'terminal CapacityHold % cannot transition from % to %', OLD.id, OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'active' AND NEW.status NOT IN ('active', 'consumed', 'released', 'expired') THEN
        RAISE EXCEPTION 'invalid CapacityHold transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'CapacityHold revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER capacity_holds_guard_transition
BEFORE UPDATE ON request_engine.capacity_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_hold_transition();

CREATE FUNCTION request_engine.guard_queue_entry_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF NOT (
        (OLD.status = 'waiting' AND NEW.status IN ('called', 'cancelled')) OR
        (OLD.status = 'called' AND NEW.status IN ('serving', 'cancelled', 'no_show')) OR
        (OLD.status = 'serving' AND NEW.status = 'completed')
    ) THEN
        RAISE EXCEPTION 'invalid QueueEntry transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'QueueEntry revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER queue_entries_guard_transition
BEFORE UPDATE ON request_engine.queue_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_entry_transition();

CREATE FUNCTION request_engine.guard_slot_opportunity_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF OLD.status <> 'open' OR NEW.status NOT IN ('filled', 'closed', 'expired') THEN
        RAISE EXCEPTION 'invalid SlotOpportunity transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER slot_opportunities_guard_transition
BEFORE UPDATE ON request_engine.slot_opportunities
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_opportunity_transition();

CREATE FUNCTION request_engine.guard_slot_offer_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.status = OLD.status THEN
        RETURN NEW;
    END IF;

    IF OLD.status <> 'offered' OR NEW.status NOT IN ('accepted', 'declined', 'expired', 'cancelled') THEN
        RAISE EXCEPTION 'invalid SlotOffer transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER slot_offers_guard_transition
BEFORE UPDATE ON request_engine.slot_offers
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_transition();

CREATE FUNCTION request_engine.guard_reminder_plan_transition()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF NEW.status <> OLD.status AND (
        OLD.status <> 'active' OR NEW.status NOT IN ('cancelled', 'completed')
    ) THEN
        RAISE EXCEPTION 'invalid ReminderPlan transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'ReminderPlan revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER reminder_plans_guard_transition
BEFORE UPDATE ON request_engine.reminder_plans
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reminder_plan_transition();

CREATE TRIGGER offering_versions_immutable
BEFORE UPDATE OR DELETE ON request_engine.offering_versions
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER offering_resource_requirements_immutable
BEFORE UPDATE OR DELETE ON request_engine.offering_resource_requirements
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER request_definition_versions_immutable
BEFORE UPDATE OR DELETE ON request_engine.request_definition_versions
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER attendance_responses_append_only
BEFORE UPDATE OR DELETE ON request_engine.attendance_responses
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER reminder_acknowledgements_append_only
BEFORE UPDATE OR DELETE ON request_engine.reminder_acknowledgements
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

CREATE TRIGGER audit_records_append_only
BEFORE UPDATE OR DELETE ON request_engine.audit_records
FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();

-- ---------------------------------------------------------------------------
-- Resource availability serialization
-- ---------------------------------------------------------------------------

CREATE FUNCTION request_engine.bump_resource_availability_revision()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_org uuid;
    v_resource uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.organization_id <> NEW.organization_id OR OLD.resource_id <> NEW.resource_id
    ) THEN
        RAISE EXCEPTION '% rows cannot move between Resources; delete/recreate explicitly', TG_TABLE_NAME
            USING ERRCODE = '23514';
    END IF;

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
        RAISE EXCEPTION 'Resource % not found while changing availability', v_resource
            USING ERRCODE = '23503';
    END IF;

    RETURN COALESCE(NEW, OLD);
END
$function$;

CREATE TRIGGER availability_schedules_bump_resource
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.availability_schedules
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_availability_revision();

CREATE TRIGGER schedule_exceptions_bump_resource
BEFORE INSERT OR UPDATE OR DELETE ON request_engine.schedule_exceptions
FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_availability_revision();

CREATE FUNCTION request_engine.guard_resource_commitment_sensitive_change()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_live_claims bigint;
BEGIN
    IF NEW.capacity_model = OLD.capacity_model
       AND NEW.capacity_units = OLD.capacity_units
       AND NEW.active = OLD.active
       AND NEW.location_id IS NOT DISTINCT FROM OLD.location_id THEN
        RETURN NEW;
    END IF;

    SELECT count(*)
      INTO v_live_claims
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
     WHERE c.organization_id = OLD.organization_id
       AND c.resource_id = OLD.id
       AND c.status = 'active'
       AND (
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed') OR
           (c.reservation_id IS NULL AND h.status = 'active' AND h.expires_at > clock_timestamp())
       );

    IF v_live_claims > 0 THEN
        RAISE EXCEPTION 'Resource % has live capacity commitments; capacity/active/location change requires explicit commitment handling', OLD.id
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER resources_guard_commitment_sensitive_change
BEFORE UPDATE ON request_engine.resources
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_resource_commitment_sensitive_change();

-- ---------------------------------------------------------------------------
-- CapacityClaim validation and serialization
-- ---------------------------------------------------------------------------

CREATE FUNCTION request_engine.guard_capacity_claim()
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

    IF v_owner_location IS NOT NULL
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

CREATE TRIGGER capacity_claims_guard_capacity
BEFORE INSERT OR UPDATE OF resource_id, requirement_id, hold_id, reservation_id, during, quantity, status
ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim();

-- Deferred aggregate completeness lets commands construct a multi-row claim set
-- inside one transaction while rejecting partial final states at COMMIT.
CREATE FUNCTION request_engine.assert_hold_claim_completeness(p_org uuid, p_hold uuid)
RETURNS void
LANGUAGE plpgsql
AS $function$
DECLARE
    v_status text;
    v_expires_at timestamptz;
    v_offering_version uuid;
    v_required bigint;
    v_claims bigint;
BEGIN
    SELECT status, expires_at, offering_version_id
      INTO v_status, v_expires_at, v_offering_version
      FROM request_engine.capacity_holds
     WHERE organization_id = p_org
       AND id = p_hold;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT count(*)
      INTO v_required
      FROM request_engine.offering_resource_requirements
     WHERE organization_id = p_org
       AND offering_version_id = v_offering_version;

    SELECT count(*)
      INTO v_claims
      FROM request_engine.capacity_claims
     WHERE organization_id = p_org
       AND hold_id = p_hold
       AND reservation_id IS NULL
       AND status = 'active';

    IF v_status = 'active' AND v_expires_at > clock_timestamp() THEN
        IF v_required = 0 OR v_claims <> v_required THEN
            RAISE EXCEPTION 'live CapacityHold % requires complete claim set: required %, active %', p_hold, v_required, v_claims
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_status IN ('consumed', 'released', 'expired') AND v_claims <> 0 THEN
        RAISE EXCEPTION 'terminal CapacityHold % cannot retain active hold-only claims', p_hold
            USING ERRCODE = '23514';
    END IF;
END
$function$;

CREATE FUNCTION request_engine.assert_reservation_claim_completeness(p_org uuid, p_reservation uuid)
RETURNS void
LANGUAGE plpgsql
AS $function$
DECLARE
    v_status text;
    v_offering_version uuid;
    v_required bigint;
    v_claims bigint;
BEGIN
    SELECT status, offering_version_id
      INTO v_status, v_offering_version
      FROM request_engine.reservations
     WHERE organization_id = p_org
       AND id = p_reservation;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    SELECT count(*)
      INTO v_required
      FROM request_engine.offering_resource_requirements
     WHERE organization_id = p_org
       AND offering_version_id = v_offering_version;

    SELECT count(*)
      INTO v_claims
      FROM request_engine.capacity_claims
     WHERE organization_id = p_org
       AND reservation_id = p_reservation
       AND status = 'active';

    IF v_status = 'confirmed' THEN
        IF v_required = 0 OR v_claims <> v_required THEN
            RAISE EXCEPTION 'confirmed Reservation % requires complete claim set: required %, active %', p_reservation, v_required, v_claims
                USING ERRCODE = '23514';
        END IF;
    ELSIF v_status = 'cancelled' AND v_claims <> 0 THEN
        RAISE EXCEPTION 'cancelled Reservation % cannot retain active capacity claims', p_reservation
            USING ERRCODE = '23514';
    END IF;
END
$function$;

CREATE FUNCTION request_engine.check_capacity_owner_completeness()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_TABLE_NAME = 'capacity_claims' THEN
        IF TG_OP <> 'INSERT' THEN
            IF OLD.hold_id IS NOT NULL THEN
                PERFORM request_engine.assert_hold_claim_completeness(OLD.organization_id, OLD.hold_id);
            END IF;
            IF OLD.reservation_id IS NOT NULL THEN
                PERFORM request_engine.assert_reservation_claim_completeness(OLD.organization_id, OLD.reservation_id);
            END IF;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            IF NEW.hold_id IS NOT NULL THEN
                PERFORM request_engine.assert_hold_claim_completeness(NEW.organization_id, NEW.hold_id);
            END IF;
            IF NEW.reservation_id IS NOT NULL THEN
                PERFORM request_engine.assert_reservation_claim_completeness(NEW.organization_id, NEW.reservation_id);
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'capacity_holds' THEN
        PERFORM request_engine.assert_hold_claim_completeness(NEW.organization_id, NEW.id);
    ELSIF TG_TABLE_NAME = 'reservations' THEN
        PERFORM request_engine.assert_reservation_claim_completeness(NEW.organization_id, NEW.id);
    END IF;

    RETURN NULL;
END
$function$;

CREATE CONSTRAINT TRIGGER capacity_claims_owner_completeness
AFTER INSERT OR UPDATE OR DELETE ON request_engine.capacity_claims
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.check_capacity_owner_completeness();

CREATE CONSTRAINT TRIGGER capacity_holds_claim_completeness
AFTER INSERT OR UPDATE ON request_engine.capacity_holds
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.check_capacity_owner_completeness();

CREATE CONSTRAINT TRIGGER reservations_claim_completeness
AFTER INSERT OR UPDATE ON request_engine.reservations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION request_engine.check_capacity_owner_completeness();

-- ---------------------------------------------------------------------------
-- SlotOffer/CapacityHold consistency
-- ---------------------------------------------------------------------------

CREATE FUNCTION request_engine.guard_slot_offer_live_hold()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_hold_status text;
    v_hold_expires timestamptz;
    v_opportunity_status text;
BEGIN
    IF NEW.status <> 'offered' THEN
        RETURN NEW;
    END IF;

    SELECT status
      INTO v_opportunity_status
      FROM request_engine.slot_opportunities
     WHERE organization_id = NEW.organization_id
       AND id = NEW.slot_opportunity_id;

    IF v_opportunity_status IS DISTINCT FROM 'open' THEN
        RAISE EXCEPTION 'offered SlotOffer requires open SlotOpportunity'
            USING ERRCODE = '23514';
    END IF;

    SELECT status, expires_at
      INTO v_hold_status, v_hold_expires
      FROM request_engine.capacity_holds
     WHERE organization_id = NEW.organization_id
       AND id = NEW.capacity_hold_id;

    IF v_hold_status IS DISTINCT FROM 'active' OR v_hold_expires <= clock_timestamp() THEN
        RAISE EXCEPTION 'offered SlotOffer requires active, unexpired CapacityHold'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.expires_at > v_hold_expires THEN
        RAISE EXCEPTION 'SlotOffer cannot outlive its CapacityHold'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$function$;

CREATE TRIGGER slot_offers_guard_live_hold
BEFORE INSERT OR UPDATE OF status, capacity_hold_id, slot_opportunity_id, expires_at
ON request_engine.slot_offers
FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_live_hold();

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

CREATE TRIGGER organizations_touch BEFORE UPDATE ON request_engine.organizations
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER principals_touch BEFORE UPDATE ON request_engine.principals
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER parties_touch BEFORE UPDATE ON request_engine.parties
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER party_contact_points_touch BEFORE UPDATE ON request_engine.party_contact_points
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER representations_touch BEFORE UPDATE ON request_engine.representations
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER locations_touch BEFORE UPDATE ON request_engine.locations
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER offerings_touch BEFORE UPDATE ON request_engine.offerings
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER resources_touch BEFORE UPDATE ON request_engine.resources
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER request_definitions_touch BEFORE UPDATE ON request_engine.request_definitions
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER requests_touch BEFORE UPDATE ON request_engine.requests
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER capacity_holds_touch BEFORE UPDATE ON request_engine.capacity_holds
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER reservations_touch BEFORE UPDATE ON request_engine.reservations
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER capacity_claims_touch BEFORE UPDATE ON request_engine.capacity_claims
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER service_queues_touch BEFORE UPDATE ON request_engine.service_queues
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER queue_entries_touch BEFORE UPDATE ON request_engine.queue_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER waitlist_entries_touch BEFORE UPDATE ON request_engine.waitlist_entries
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER slot_opportunities_touch BEFORE UPDATE ON request_engine.slot_opportunities
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER slot_offers_touch BEFORE UPDATE ON request_engine.slot_offers
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER communication_tasks_touch BEFORE UPDATE ON request_engine.communication_tasks
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER communication_deliveries_touch BEFORE UPDATE ON request_engine.communication_deliveries
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER reminder_plans_touch BEFORE UPDATE ON request_engine.reminder_plans
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER scheduled_actions_touch BEFORE UPDATE ON request_engine.scheduled_actions
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();
CREATE TRIGGER outbox_messages_touch BEFORE UPDATE ON request_engine.outbox_messages
FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security: tenant defense-in-depth
-- ---------------------------------------------------------------------------

ALTER TABLE request_engine.organizations ENABLE ROW LEVEL SECURITY;
CREATE POLICY organizations_tenant_isolation ON request_engine.organizations
    USING (id = request_engine.current_organization_id())
    WITH CHECK (id = request_engine.current_organization_id());

DO $rls$
DECLARE
    v_table text;
    v_tables text[] := ARRAY[
        'principals',
        'parties',
        'party_contact_points',
        'representations',
        'locations',
        'offerings',
        'offering_versions',
        'resource_capabilities',
        'offering_resource_requirements',
        'resources',
        'resource_capability_assignments',
        'availability_schedules',
        'schedule_exceptions',
        'request_definitions',
        'request_definition_versions',
        'requests',
        'request_participants',
        'external_correlations',
        'capacity_holds',
        'reservations',
        'capacity_claims',
        'attendance_responses',
        'service_queues',
        'queue_entries',
        'waitlist_entries',
        'slot_opportunities',
        'slot_offers',
        'communication_tasks',
        'communication_deliveries',
        'reminder_plans',
        'reminder_acknowledgements',
        'scheduled_actions',
        'idempotency_records',
        'provider_events',
        'audit_records',
        'outbox_messages'
    ];
BEGIN
    FOREACH v_table IN ARRAY v_tables LOOP
        EXECUTE format('ALTER TABLE request_engine.%I ENABLE ROW LEVEL SECURITY', v_table);
        EXECUTE format(
            'CREATE POLICY %I ON request_engine.%I USING (organization_id = request_engine.current_organization_id()) WITH CHECK (organization_id = request_engine.current_organization_id())',
            v_table || '_tenant_isolation',
            v_table
        );
    END LOOP;
END
$rls$;

RESET ROLE;
COMMIT;
