    SELECT NULLIF(current_setting('request_engine.organization_id', true), '')::uuid
$$;


ALTER FUNCTION request_engine.current_organization_id() OWNER TO request_engine_schema_owner;

--
-- Name: guard_booking_context_terms_scope(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_booking_context_terms_scope() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.organization_id <> NEW.organization_id
       OR OLD.resource_location_assignment_id <> NEW.resource_location_assignment_id
       OR OLD.offering_version_id <> NEW.offering_version_id THEN
        RAISE EXCEPTION 'BookingContextTerms scope cannot be retargeted' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_booking_context_terms_scope() OWNER TO request_engine_schema_owner;

--
-- Name: guard_capacity_claim(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_capacity_claim() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_capacity_model text;
    v_capacity_units integer;
    v_resource_active boolean;
    v_owner_offering_version uuid;
    v_owner_during tstzrange;
    v_owner_location uuid;
    v_requirement_offering_version uuid;
    v_required_capability uuid;
    v_required_quantity integer;
    v_other_quantity bigint;
    v_other_count bigint;
    v_promoting_hold boolean;
    v_shared_capacity_identity_id uuid;
    v_shared_conflict boolean;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT r.capacity_model, r.capacity_units, r.active
      INTO v_capacity_model,
           v_capacity_units,
           v_resource_active
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

    IF TG_OP = 'UPDATE' AND OLD.resource_id <> NEW.resource_id AND EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_claim_links
         WHERE capacity_claim_id = OLD.id
    ) THEN
        RAISE EXCEPTION
            'linked CapacityClaim cannot move between Resources; release/recreate it'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.reservation_id IS NOT NULL THEN
        SELECT r.offering_version_id, r.during, r.location_id
          INTO v_owner_offering_version, v_owner_during, v_owner_location
          FROM request_engine.reservations r
         WHERE r.organization_id = NEW.organization_id
           AND r.id = NEW.reservation_id
           AND r.status = 'confirmed';
        IF NOT FOUND THEN
            RAISE EXCEPTION
                'active reservation claim requires confirmed Reservation %',
                NEW.reservation_id
                USING ERRCODE = '23514';
        END IF;

        v_promoting_hold := NEW.hold_id IS NOT NULL AND (
            TG_OP = 'INSERT' OR OLD.reservation_id IS NULL
        );
        IF v_promoting_hold AND NOT EXISTS (
            SELECT 1
              FROM request_engine.capacity_holds h
             WHERE h.organization_id = NEW.organization_id
               AND h.id = NEW.hold_id
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
               AND h.offering_version_id = v_owner_offering_version
               AND h.during = v_owner_during
        ) THEN
            RAISE EXCEPTION
                'cannot promote expired, terminal, or mismatched CapacityHold %',
                NEW.hold_id
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
            RAISE EXCEPTION
                'active hold claim requires live, unexpired CapacityHold %',
                NEW.hold_id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.during <> v_owner_during THEN
        RAISE EXCEPTION
            'CapacityClaim interval must equal its Hold/Reservation interval'
            USING ERRCODE = '23514';
    END IF;

    SELECT rr.offering_version_id, rr.capability_id, rr.quantity
      INTO v_requirement_offering_version,
           v_required_capability,
           v_required_quantity
      FROM request_engine.offering_resource_requirements rr
     WHERE rr.organization_id = NEW.organization_id
       AND rr.id = NEW.requirement_id;
    IF NOT FOUND OR v_requirement_offering_version <> v_owner_offering_version THEN
        RAISE EXCEPTION
            'CapacityClaim requirement does not belong to the owner OfferingVersion'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.quantity <> v_required_quantity THEN
        RAISE EXCEPTION
            'CapacityClaim quantity % does not satisfy requirement quantity %',
            NEW.quantity,
            v_required_quantity
            USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM request_engine.resource_capability_assignments a
         WHERE a.organization_id = NEW.organization_id
           AND a.resource_id = NEW.resource_id
           AND a.capability_id = v_required_capability
    ) THEN
        RAISE EXCEPTION
            'Resource % does not satisfy required capability',
            NEW.resource_id
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
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
           OR (
               c.reservation_id IS NULL
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
           )
       );
    IF v_capacity_model = 'exclusive' AND v_other_count > 0 THEN
        RAISE EXCEPTION
            'exclusive Resource % has overlapping live capacity',
            NEW.resource_id
            USING ERRCODE = '23P01';
    END IF;
    IF v_capacity_model = 'units'
       AND v_other_quantity + NEW.quantity > v_capacity_units THEN
        RAISE EXCEPTION
            'Resource % capacity exceeded: requested %, live %, capacity %',
            NEW.resource_id,
            NEW.quantity,
            v_other_quantity,
            v_capacity_units
            USING ERRCODE = '23P01';
    END IF;

    SELECT b.shared_capacity_identity_id
      INTO v_shared_capacity_identity_id
      FROM request_engine.shared_capacity_bindings b
     WHERE b.organization_id = NEW.organization_id
       AND b.resource_id = NEW.resource_id
       AND b.status = 'active';

    IF v_shared_capacity_identity_id IS NOT NULL THEN
        PERFORM 1
          FROM request_engine.shared_capacity_identities
         WHERE id = v_shared_capacity_identity_id
           AND status = 'active'
         FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'capacity unavailable'
                USING ERRCODE = '23P01';
        END IF;

        SELECT EXISTS (
            SELECT 1
              FROM request_engine.shared_capacity_claim_links link
              JOIN request_engine.capacity_claims c
                ON c.id = link.capacity_claim_id
              LEFT JOIN request_engine.reservations r
                ON r.organization_id = c.organization_id
               AND r.id = c.reservation_id
              LEFT JOIN request_engine.capacity_holds h
                ON h.organization_id = c.organization_id
               AND h.id = c.hold_id
             WHERE link.shared_capacity_identity_id = v_shared_capacity_identity_id
               AND c.id <> NEW.id
               AND c.status = 'active'
               AND c.during && NEW.during
               AND (
                   (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
                   OR (
                       c.reservation_id IS NULL
                       AND h.status = 'active'
                       AND h.expires_at > clock_timestamp()
                   )
               )
        ) INTO v_shared_conflict;

        IF v_shared_conflict THEN
            RAISE EXCEPTION 'capacity unavailable'
                USING ERRCODE = '23P01';
        END IF;
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_capacity_claim() OWNER TO request_engine_schema_owner;

--
-- Name: guard_capacity_claim_contextual_assignment(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_capacity_claim_contextual_assignment() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_assignment_resource uuid;
    v_assignment_location uuid;
    v_assignment_during tstzrange;
    v_assignment_status text;
    v_owner_location uuid;
    v_owner_found boolean := false;
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.resource_location_assignment_id
           IS DISTINCT FROM OLD.resource_location_assignment_id THEN
        RAISE EXCEPTION
            'CapacityClaim ResourceLocationAssignment provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.status <> 'active' OR NEW.resource_location_assignment_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT a.resource_id, a.location_id, a.effective_during, a.status
      INTO v_assignment_resource,
           v_assignment_location,
           v_assignment_during,
           v_assignment_status
      FROM request_engine.resource_location_assignments a
     WHERE a.organization_id = NEW.organization_id
       AND a.id = NEW.resource_location_assignment_id;
    IF NOT FOUND THEN
        -- Do not expose whether a caller-supplied foreign UUID exists elsewhere.
        RAISE EXCEPTION 'ResourceLocationAssignment does not exist for capacity claim'
            USING ERRCODE = '23503';
    END IF;
    IF v_assignment_resource <> NEW.resource_id THEN
        RAISE EXCEPTION
            'CapacityClaim ResourceLocationAssignment belongs to a different Resource'
            USING ERRCODE = '23514';
    END IF;
    IF v_assignment_status <> 'active' THEN
        RAISE EXCEPTION 'CapacityClaim ResourceLocationAssignment is not active'
            USING ERRCODE = '23514';
    END IF;
    IF NOT (v_assignment_during @> NEW.during) THEN
        RAISE EXCEPTION
            'CapacityClaim interval is outside ResourceLocationAssignment effective range'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reservation_id IS NOT NULL THEN
        SELECT r.location_id
          INTO v_owner_location
          FROM request_engine.reservations r
         WHERE r.organization_id = NEW.organization_id
           AND r.id = NEW.reservation_id;
        v_owner_found := FOUND;
    ELSIF NEW.hold_id IS NOT NULL THEN
        SELECT h.location_id
          INTO v_owner_location
          FROM request_engine.capacity_holds h
         WHERE h.organization_id = NEW.organization_id
           AND h.id = NEW.hold_id;
        v_owner_found := FOUND;
    END IF;

    IF v_owner_found
       AND (
           v_owner_location IS NULL
           OR v_owner_location <> v_assignment_location
       ) THEN
        RAISE EXCEPTION
            'CapacityClaim ResourceLocationAssignment belongs to a different Location '
            'than the Hold/Reservation'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_capacity_claim_contextual_assignment() OWNER TO request_engine_schema_owner;

--
-- Name: guard_capacity_claim_replacement_provenance(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_capacity_claim_replacement_provenance() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_target_status text;
    v_target_requirement_id uuid;
    v_target_reservation_id uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'active' OR NEW.replaced_by_claim_id IS NOT NULL THEN
            RAISE EXCEPTION 'CapacityClaim must be created as active without replacement provenance'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status <> 'replaced' THEN
        IF NEW.replaced_by_claim_id IS NOT NULL THEN
            RAISE EXCEPTION 'CapacityClaim replacement edge requires replaced status'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'replaced' THEN
        RETURN NEW;
    END IF;

    IF OLD.status <> 'released' THEN
        RAISE EXCEPTION 'CapacityClaim must be released before replacement is recorded'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.reservation_id IS NULL OR NEW.replaced_by_claim_id = NEW.id THEN
        RAISE EXCEPTION 'CapacityClaim replacement provenance is invalid'
            USING ERRCODE = '23514';
    END IF;

    SELECT target.status, target.requirement_id, target.reservation_id
      INTO v_target_status, v_target_requirement_id, v_target_reservation_id
      FROM request_engine.capacity_claims target
     WHERE target.organization_id = NEW.organization_id
       AND target.id = NEW.replaced_by_claim_id
     FOR UPDATE;

    IF NOT FOUND
       OR v_target_status <> 'active'
       OR v_target_requirement_id <> NEW.requirement_id
       OR v_target_reservation_id IS DISTINCT FROM NEW.reservation_id
    THEN
        RAISE EXCEPTION 'CapacityClaim replacement must target the live successor for the same owner and requirement'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_capacity_claim_replacement_provenance() OWNER TO request_engine_schema_owner;

--
-- Name: guard_capacity_claim_tenant_context(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_capacity_claim_tenant_context() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_context_organization_id uuid;
    v_is_runtime_app boolean := false;
BEGIN
    IF current_user = 'request_engine_app' THEN
        v_is_runtime_app := true;
    ELSE
        SELECT
            pg_catalog.pg_has_role(current_user, 'request_engine_app', 'MEMBER')
            AND NOT role_row.rolsuper
            AND NOT role_row.rolbypassrls
          INTO v_is_runtime_app
          FROM pg_catalog.pg_roles AS role_row
         WHERE role_row.rolname = current_user;
    END IF;

    IF COALESCE(v_is_runtime_app, false) THEN
        v_context_organization_id := request_engine.current_organization_id();
        IF v_context_organization_id IS NULL
           OR NEW.organization_id IS DISTINCT FROM v_context_organization_id
        THEN
            RAISE EXCEPTION 'capacity claim organization context mismatch'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_capacity_claim_tenant_context() OWNER TO request_engine_schema_owner;

--
-- Name: guard_capacity_claim_terminal_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_capacity_claim_terminal_transition() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF OLD.status = 'replaced' THEN
        IF NEW.status <> 'replaced'
           OR NEW.released_at IS DISTINCT FROM OLD.released_at
           OR NEW.replaced_by_claim_id IS DISTINCT FROM OLD.replaced_by_claim_id
        THEN
            RAISE EXCEPTION 'terminal CapacityClaim % cannot be rewritten', OLD.id
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'released' THEN
        IF NEW.status NOT IN ('released', 'replaced') THEN
            RAISE EXCEPTION 'terminal CapacityClaim % cannot reactivate from released to %',
                OLD.id, NEW.status
                USING ERRCODE = '23514';
        END IF;
        IF NEW.released_at IS DISTINCT FROM OLD.released_at THEN
            RAISE EXCEPTION 'released CapacityClaim % release timestamp is immutable', OLD.id
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'released'
           AND NEW.replaced_by_claim_id IS DISTINCT FROM OLD.replaced_by_claim_id
        THEN
            RAISE EXCEPTION 'released CapacityClaim % replacement edge requires replaced status', OLD.id
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_capacity_claim_terminal_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_capacity_hold_provenance_update(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_capacity_hold_provenance_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM request_engine.slot_offers
         WHERE organization_id = OLD.organization_id
           AND capacity_hold_id = OLD.id
    ) AND (
        OLD.organization_id IS DISTINCT FROM NEW.organization_id
        OR OLD.offering_version_id IS DISTINCT FROM NEW.offering_version_id
        OR OLD.subject_party_id IS DISTINCT FROM NEW.subject_party_id
        OR OLD.location_id IS DISTINCT FROM NEW.location_id
        OR OLD.during IS DISTINCT FROM NEW.during
        OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
        OR OLD.created_at IS DISTINCT FROM NEW.created_at
    ) THEN
        RAISE EXCEPTION 'SlotOffer source state is no longer valid: CapacityHold booking provenance is immutable after SlotOffer reference'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_capacity_hold_provenance_update() OWNER TO request_engine_schema_owner;

--
-- Name: guard_communication_escalations(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_communication_escalations() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'communication escalations is an append-only ledger'
        USING ERRCODE = '23514';
END
$$;


ALTER FUNCTION request_engine.guard_communication_escalations() OWNER TO request_engine_schema_owner;

--
-- Name: guard_discovery_handoff_latest_version(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_discovery_definer
--

CREATE FUNCTION request_engine.guard_discovery_handoff_latest_version() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_handoff_id uuid;
    v_offering_id uuid;
    v_latest_id uuid;
    v_latest_bookable boolean;
BEGIN
    BEGIN
        v_handoff_id := NULLIF(
            current_setting('request_engine.discovery_handoff_id', true), ''
        )::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid discovery handoff context' USING ERRCODE = '22023';
    END;
    IF v_handoff_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT dp.offering_id
      INTO v_offering_id
      FROM request_engine.discovery_booking_handoffs h
      JOIN request_engine.discovery_publications dp
        ON dp.organization_id = h.organization_id
       AND dp.id = h.publication_id
     WHERE h.id = v_handoff_id
       AND h.organization_id = NEW.organization_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    PERFORM 1
      FROM request_engine.offerings o
     WHERE o.organization_id = NEW.organization_id
       AND o.id = v_offering_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    SELECT ov.id, ov.bookable
      INTO v_latest_id, v_latest_bookable
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = NEW.organization_id
       AND ov.offering_id = v_offering_id
     ORDER BY ov.version DESC
     LIMIT 1;
    IF NOT FOUND OR v_latest_id <> NEW.offering_version_id OR NOT v_latest_bookable THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_discovery_handoff_latest_version() OWNER TO request_engine_discovery_definer;

--
-- Name: guard_discovery_handoff_reservation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_discovery_definer
--

CREATE FUNCTION request_engine.guard_discovery_handoff_reservation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_handoff_id uuid;
    v_handoff request_engine.discovery_booking_handoffs%ROWTYPE;
    v_publication request_engine.discovery_publications%ROWTYPE;
    v_mapping request_engine.offering_service_classifications%ROWTYPE;
BEGIN
    BEGIN
        v_handoff_id := NULLIF(
            current_setting('request_engine.discovery_handoff_id', true), ''
        )::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid discovery handoff context' USING ERRCODE = '22023';
    END;
    IF v_handoff_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT * INTO v_handoff
      FROM request_engine.discovery_booking_handoffs
     WHERE id = v_handoff_id
       AND organization_id = NEW.organization_id
     FOR UPDATE;
    IF NOT FOUND OR v_handoff.expires_at <= clock_timestamp()
       OR v_handoff.consumed_reservation_id IS NOT NULL THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_mapping
      FROM request_engine.offering_service_classifications
     WHERE organization_id = v_handoff.organization_id
       AND id = v_handoff.mapping_id
       AND status = 'active'
       AND revision = v_handoff.mapping_revision
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_publication
      FROM request_engine.discovery_publications
     WHERE organization_id = v_handoff.organization_id
       AND id = v_handoff.publication_id
       AND status = 'active'
       AND revision = v_handoff.publication_revision
       AND NEW.during <@ effective_during
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'discovery option stale' USING ERRCODE = '40001';
    END IF;

    IF NEW.offering_version_id <> v_handoff.offering_version_id
       OR NEW.location_id IS DISTINCT FROM v_handoff.location_id
       OR lower(NEW.during) <> (v_handoff.selection->>'start_at')::timestamptz
       OR upper(NEW.during) <> (v_handoff.selection->>'end_at')::timestamptz THEN
        RAISE EXCEPTION 'discovery option does not match Reservation' USING ERRCODE = '23514';
    END IF;

    UPDATE request_engine.discovery_booking_handoffs
       SET consumed_reservation_id = NEW.id
     WHERE id = v_handoff.id;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_discovery_handoff_reservation() OWNER TO request_engine_discovery_definer;

--
-- Name: guard_exact_revision_step(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_exact_revision_step() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_exact_revision_step() OWNER TO request_engine_schema_owner;

--
-- Name: guard_f2_mapping_lifecycle(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_f2_mapping_lifecycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.organization_id <> NEW.organization_id OR OLD.offering_id <> NEW.offering_id THEN
        RAISE EXCEPTION 'OfferingServiceClassification scope cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked OfferingServiceClassification cannot be reactivated'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_f2_mapping_lifecycle() OWNER TO request_engine_schema_owner;

--
-- Name: guard_f2_publication_broad_specific_overlap(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_f2_publication_broad_specific_overlap() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_lock_key bigint;
BEGIN
    v_lock_key := hashtextextended(
        NEW.organization_id::text || ':' || NEW.offering_id::text || ':' || NEW.location_id::text,
        0
    );
    PERFORM pg_advisory_xact_lock(v_lock_key);
    IF NEW.status = 'active' AND EXISTS (
        SELECT 1
          FROM request_engine.discovery_publications p
         WHERE p.organization_id = NEW.organization_id
           AND p.offering_id = NEW.offering_id
           AND p.location_id = NEW.location_id
           AND p.id <> NEW.id
           AND p.status = 'active'
           AND p.effective_during && NEW.effective_during
           AND (p.resource_id IS NULL OR NEW.resource_id IS NULL)
    ) THEN
        RAISE EXCEPTION 'broad and resource-specific discovery publications cannot overlap'
            USING ERRCODE = '23P01';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_f2_publication_broad_specific_overlap() OWNER TO request_engine_schema_owner;

--
-- Name: guard_f2_publication_lifecycle(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_f2_publication_lifecycle() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_f2_publication_lifecycle() OWNER TO request_engine_schema_owner;

--
-- Name: guard_hold_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_hold_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_hold_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_linked_capacity_claim_provenance(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_linked_capacity_claim_provenance() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_linked boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_claim_links link
         WHERE link.capacity_claim_id = OLD.id
    ) INTO v_linked;

    IF NOT v_linked THEN
        RETURN NEW;
    END IF;

    IF OLD.id IS DISTINCT FROM NEW.id
       OR OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.requirement_id IS DISTINCT FROM NEW.requirement_id
       OR OLD.hold_id IS DISTINCT FROM NEW.hold_id
       OR OLD.during IS DISTINCT FROM NEW.during
       OR OLD.quantity IS DISTINCT FROM NEW.quantity
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'linked CapacityClaim material provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.reservation_id IS NOT NULL
       AND NEW.reservation_id IS DISTINCT FROM OLD.reservation_id
    THEN
        RAISE EXCEPTION 'linked CapacityClaim Reservation provenance cannot be rewritten'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.reservation_id IS NULL
       AND NEW.reservation_id IS NOT NULL
       AND (OLD.status <> 'active' OR NEW.status <> 'active')
    THEN
        RAISE EXCEPTION 'only an active linked Hold claim may be promoted to a Reservation'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_linked_capacity_claim_provenance() OWNER TO request_engine_schema_owner;

--
-- Name: guard_live_capacity_projection_policy(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_live_capacity_projection_policy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'LiveCapacityProjectionPolicy is durable configuration; deactivate it'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.service_queue_id IS DISTINCT FROM NEW.service_queue_id THEN
        RAISE EXCEPTION 'LiveCapacityProjectionPolicy identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'LiveCapacityProjectionPolicy revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_live_capacity_projection_policy() OWNER TO request_engine_schema_owner;

--
-- Name: guard_live_capacity_workload_estimate_policy(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_live_capacity_workload_estimate_policy() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'LiveCapacityWorkloadEstimatePolicy is durable configuration; deactivate it'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.workload_classification_id IS DISTINCT FROM NEW.workload_classification_id THEN
        RAISE EXCEPTION 'LiveCapacityWorkloadEstimatePolicy identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'LiveCapacityWorkloadEstimatePolicy revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at := clock_timestamp();
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_live_capacity_workload_estimate_policy() OWNER TO request_engine_schema_owner;

--
-- Name: guard_live_resource_occupation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_live_resource_occupation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_validate_assignment boolean;
BEGIN
    PERFORM 1 FROM request_engine.resources
     WHERE organization_id = NEW.organization_id AND id = NEW.resource_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % does not exist', NEW.resource_id USING ERRCODE = '23503';
    END IF;

    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_validate_assignment := TG_OP = 'INSERT';
        IF TG_OP = 'UPDATE' THEN
            v_validate_assignment := NEW.resource_id IS DISTINCT FROM OLD.resource_id
                OR NEW.location_id IS DISTINCT FROM OLD.location_id
                OR NEW.started_at IS DISTINCT FROM OLD.started_at;
        END IF;
        IF v_validate_assignment AND NOT EXISTS (
            SELECT 1 FROM request_engine.resource_location_assignments a
             WHERE a.organization_id = NEW.organization_id
               AND a.resource_id = NEW.resource_id
               AND a.location_id = NEW.location_id
               AND a.status = 'active'
               AND a.effective_during @> NEW.started_at
        ) THEN
            RAISE EXCEPTION 'Resource % is not assigned to Location % at execution time',
                NEW.resource_id, NEW.location_id USING ERRCODE = '23514';
        END IF;
        IF NEW.status IN ('active', 'paused') AND EXISTS (
            SELECT 1 FROM request_engine.resource_activities a
             WHERE a.organization_id = NEW.organization_id
               AND a.resource_id = NEW.resource_id AND a.ended_at IS NULL
        ) THEN
            RAISE EXCEPTION 'Resource % has an open ResourceActivity', NEW.resource_id
                USING ERRCODE = '23P01';
        END IF;
    ELSIF TG_TABLE_NAME = 'resource_activities' THEN
        v_validate_assignment := TG_OP = 'INSERT';
        IF TG_OP = 'UPDATE' THEN
            v_validate_assignment := NEW.resource_id IS DISTINCT FROM OLD.resource_id
                OR NEW.location_id IS DISTINCT FROM OLD.location_id
                OR NEW.started_at IS DISTINCT FROM OLD.started_at;
        END IF;
        IF v_validate_assignment AND NEW.location_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM request_engine.resource_location_assignments a
             WHERE a.organization_id = NEW.organization_id
               AND a.resource_id = NEW.resource_id
               AND a.location_id = NEW.location_id
               AND a.status = 'active'
               AND a.effective_during @> NEW.started_at
        ) THEN
            RAISE EXCEPTION 'Resource % is not assigned to Location % at activity start',
                NEW.resource_id, NEW.location_id USING ERRCODE = '23514';
        END IF;
        IF NEW.ended_at IS NULL AND EXISTS (
            SELECT 1 FROM request_engine.service_sessions s
             WHERE s.organization_id = NEW.organization_id
               AND s.resource_id = NEW.resource_id AND s.status IN ('active', 'paused')
        ) THEN
            RAISE EXCEPTION 'Resource % has a live ServiceSession', NEW.resource_id
                USING ERRCODE = '23P01';
        END IF;
    ELSE
        RAISE EXCEPTION 'guard_live_resource_occupation attached to unsupported relation %',
            TG_TABLE_NAME USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_live_resource_occupation() OWNER TO request_engine_schema_owner;

--
-- Name: guard_location_operational_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_location_operational_revision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_material_change boolean;
BEGIN
    v_material_change := NEW.active IS DISTINCT FROM OLD.active
        OR NEW.timezone IS DISTINCT FROM OLD.timezone;
    IF v_material_change THEN
        IF NEW.operational_revision = OLD.operational_revision THEN
            NEW.operational_revision := OLD.operational_revision + 1;
        ELSIF NEW.operational_revision <> OLD.operational_revision + 1 THEN
            RAISE EXCEPTION 'Location operational_revision must advance exactly one step for a material availability change'
                USING ERRCODE = '23514';
        END IF;
    ELSIF NEW.operational_revision NOT IN (OLD.operational_revision, OLD.operational_revision + 1) THEN
        RAISE EXCEPTION 'Location operational_revision cannot jump from % to %',
            OLD.operational_revision, NEW.operational_revision USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_location_operational_revision() OWNER TO request_engine_schema_owner;

--
-- Name: guard_operational_recovery_escalation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_operational_recovery_escalation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'OperationalRecoveryEscalation is immutable'
        USING ERRCODE = '23514';
END
$$;


ALTER FUNCTION request_engine.guard_operational_recovery_escalation() OWNER TO request_engine_schema_owner;

--
-- Name: guard_operational_recovery_execution(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_operational_recovery_execution() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'OperationalRecoveryExecution is append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.proposal_id IS DISTINCT FROM NEW.proposal_id
       OR OLD.reservation_id IS DISTINCT FROM NEW.reservation_id
       OR OLD.executed_by_principal_id IS DISTINCT FROM NEW.executed_by_principal_id
       OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
       OR OLD.command_fingerprint IS DISTINCT FROM NEW.command_fingerprint
       OR OLD.source_fingerprint IS DISTINCT FROM NEW.source_fingerprint
       OR OLD.proposal_fingerprint IS DISTINCT FROM NEW.proposal_fingerprint
       OR OLD.original_reservation_revision IS DISTINCT FROM NEW.original_reservation_revision
       OR OLD.target IS DISTINCT FROM NEW.target
       OR OLD.notification_requested IS DISTINCT FROM NEW.notification_requested
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'OperationalRecoveryExecution identity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status = 'prepared'
       AND NEW.status IN ('succeeded', 'rejected')
       AND NEW.communication_task_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF OLD.status = 'succeeded'
       AND NEW.status = 'succeeded'
       AND OLD.communication_task_id IS NULL
       AND NEW.communication_task_id IS NOT NULL
       AND OLD.resulting_reservation_revision IS NOT DISTINCT FROM
           NEW.resulting_reservation_revision
       AND OLD.failure_code IS NOT DISTINCT FROM NEW.failure_code
       AND OLD.completed_at IS NOT DISTINCT FROM NEW.completed_at THEN
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'invalid OperationalRecoveryExecution transition % -> %',
        OLD.status, NEW.status USING ERRCODE = '23514';
END
$$;


ALTER FUNCTION request_engine.guard_operational_recovery_execution() OWNER TO request_engine_schema_owner;

--
-- Name: guard_operational_recovery_proposal(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_operational_recovery_proposal() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'OperationalRecoveryProposal is immutable'
        USING ERRCODE = '23514';
END
$$;


ALTER FUNCTION request_engine.guard_operational_recovery_proposal() OWNER TO request_engine_schema_owner;

--
-- Name: guard_operational_workload_classification(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_operational_workload_classification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'OperationalWorkloadClassification is append-preserving; deactivate it'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.workload_key IS DISTINCT FROM NEW.workload_key THEN
        RAISE EXCEPTION 'OperationalWorkloadClassification identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF NOT OLD.active AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'inactive OperationalWorkloadClassification is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'OperationalWorkloadClassification revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_operational_workload_classification() OWNER TO request_engine_schema_owner;

--
-- Name: guard_party_administrative_identifier_facts(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_party_administrative_identifier_facts() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.party_id IS DISTINCT FROM NEW.party_id
        OR OLD.kind IS DISTINCT FROM NEW.kind
        OR OLD.issuer IS DISTINCT FROM NEW.issuer
        OR OLD.normalized_issuer IS DISTINCT FROM NEW.normalized_issuer
        OR OLD.value IS DISTINCT FROM NEW.value
        OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value
    ) THEN
        RAISE EXCEPTION 'party administrative identifier facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_party_administrative_identifier_facts() OWNER TO request_engine_schema_owner;

--
-- Name: guard_party_contact_point_verification(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_party_contact_point_verification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND OLD.verified IS TRUE
       AND NEW.verified IS NOT TRUE THEN
        RAISE EXCEPTION 'party contact point verification is monotone upward'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_party_contact_point_verification() OWNER TO request_engine_schema_owner;

--
-- Name: guard_party_identity_documents(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_party_identity_documents() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_party_kind text;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.kind IS DISTINCT FROM NEW.kind
        OR OLD.authority IS DISTINCT FROM NEW.authority
        OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value
    ) THEN
        RAISE EXCEPTION 'party identity document facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    SELECT p.party_kind INTO v_party_kind
    FROM request_engine.parties p
    WHERE p.organization_id = NEW.organization_id AND p.id = NEW.party_id;
    IF v_party_kind IS NULL OR NOT (
        (v_party_kind = 'person' AND NEW.kind IN ('cedula', 'passport'))
        OR (v_party_kind = 'organization' AND NEW.kind = 'rnc')
    ) THEN
        RAISE EXCEPTION 'strong identifier kind is incompatible with Party kind'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_party_identity_documents() OWNER TO request_engine_schema_owner;

--
-- Name: guard_party_identity_revisions(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_party_identity_revisions() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'party identity revisions is an append-only ledger'
        USING ERRCODE = '23514';
END
$$;


ALTER FUNCTION request_engine.guard_party_identity_revisions() OWNER TO request_engine_schema_owner;

--
-- Name: guard_party_kind_immutable(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_party_kind_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.party_kind IS DISTINCT FROM NEW.party_kind THEN
        RAISE EXCEPTION 'Party kind is immutable' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_party_kind_immutable() OWNER TO request_engine_schema_owner;

--
-- Name: guard_person_shared_capacity_cardinality(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_person_shared_capacity_cardinality() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_identity_kind text;
    v_identity_status text;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT identity_kind, status
      INTO v_identity_kind, v_identity_status
      FROM request_engine.global_identities
     WHERE id = NEW.global_identity_id
     FOR UPDATE;

    IF NOT FOUND OR v_identity_status <> 'active' THEN
        RAISE EXCEPTION 'SharedCapacityIdentity requires an active GlobalIdentity'
            USING ERRCODE = '22023';
    END IF;

    IF v_identity_kind = 'person' AND EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_identities existing
         WHERE existing.global_identity_id = NEW.global_identity_id
           AND existing.status = 'active'
           AND existing.id <> NEW.id
    ) THEN
        RAISE EXCEPTION 'person GlobalIdentity already has an active SharedCapacityIdentity'
            USING ERRCODE = '23505';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_person_shared_capacity_cardinality() OWNER TO request_engine_schema_owner;

--
-- Name: guard_principal_contacts(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_principal_contacts() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.channel IS DISTINCT FROM NEW.channel
           OR OLD.normalized_value IS DISTINCT FROM NEW.normalized_value THEN
            RAISE EXCEPTION
                'staff administrative contact facts are immutable; register a new contact instead'
                USING ERRCODE = '23514';
        END IF;
        IF OLD.verified IS TRUE
           AND NEW.verified IS NOT TRUE THEN
            RAISE EXCEPTION
                'staff administrative contact verification is monotone upward'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_principal_contacts() OWNER TO request_engine_schema_owner;

--
-- Name: guard_promoted_capacity_claim_owner(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_promoted_capacity_claim_owner() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_matches boolean;
BEGIN
    IF NEW.status <> 'active'
       OR NEW.hold_id IS NULL
       OR NEW.reservation_id IS NULL
    THEN
        RETURN NEW;
    END IF;

    SELECT EXISTS (
        SELECT 1
          FROM request_engine.capacity_holds h
          JOIN request_engine.reservations r
            ON r.organization_id = h.organization_id
         WHERE h.organization_id = NEW.organization_id
           AND h.id = NEW.hold_id
           AND r.id = NEW.reservation_id
           AND h.offering_version_id = r.offering_version_id
           AND h.subject_party_id = r.subject_party_id
           AND h.location_id IS NOT DISTINCT FROM r.location_id
           AND h.during = r.during
    ) INTO v_matches;

    IF NOT v_matches THEN
        RAISE EXCEPTION 'promoted CapacityClaim Hold/Reservation provenance mismatch'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_promoted_capacity_claim_owner() OWNER TO request_engine_schema_owner;

--
-- Name: guard_queue_entry_recall_hold(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_queue_entry_recall_hold() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QueueEntry recall holds are append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.condition_kind IS DISTINCT FROM NEW.condition_kind
       OR OLD.until_at IS DISTINCT FROM NEW.until_at
       OR OLD.event_key IS DISTINCT FROM NEW.event_key
       OR OLD.reason IS DISTINCT FROM NEW.reason
       OR OLD.created_by_principal_id IS DISTINCT FROM NEW.created_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'QueueEntry recall hold facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.released_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'released QueueEntry recall hold is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_queue_entry_recall_hold() OWNER TO request_engine_schema_owner;

--
-- Name: guard_queue_entry_skip(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_queue_entry_skip() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'QueueEntry skips are append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.reason IS DISTINCT FROM NEW.reason
       OR OLD.created_by_principal_id IS DISTINCT FROM NEW.created_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'QueueEntry skip facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.consumed_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'consumed QueueEntry skip is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_queue_entry_skip() OWNER TO request_engine_schema_owner;

--
-- Name: guard_queue_entry_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_queue_entry_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_queue_entry_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_reminder_plan_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_reminder_plan_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_reminder_plan_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_request_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_request_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_request_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_reservation_arrival_estimate(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_reservation_arrival_estimate() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'reservation arrival estimate history is append-preserving'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.reservation_id IS DISTINCT FROM NEW.reservation_id
       OR OLD.estimated_arrival_at IS DISTINCT FROM NEW.estimated_arrival_at
       OR OLD.source_kind IS DISTINCT FROM NEW.source_kind
       OR OLD.asserted_by_principal_id IS DISTINCT FROM NEW.asserted_by_principal_id
       OR OLD.asserted_at IS DISTINCT FROM NEW.asserted_at THEN
        RAISE EXCEPTION 'reservation arrival estimate facts are immutable'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.superseded_at IS NOT NULL
       AND NEW.superseded_at IS DISTINCT FROM OLD.superseded_at THEN
        RAISE EXCEPTION 'superseded reservation arrival estimate is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_reservation_arrival_estimate() OWNER TO request_engine_schema_owner;

--
-- Name: guard_reservation_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_reservation_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_reservation_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_resource_activity_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_resource_activity_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id
       OR OLD.activity_kind IS DISTINCT FROM NEW.activity_kind
       OR OLD.started_at IS DISTINCT FROM NEW.started_at THEN
        RAISE EXCEPTION 'ResourceActivity identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.ended_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ended ResourceActivity is immutable' USING ERRCODE = '23514';
    END IF;
    IF NEW IS DISTINCT FROM OLD AND NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'ResourceActivity revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_resource_activity_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_resource_commitment_sensitive_change(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_resource_commitment_sensitive_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_live_claims bigint;
BEGIN
    IF NEW.capacity_model = OLD.capacity_model
       AND NEW.capacity_units = OLD.capacity_units
       AND NEW.active = OLD.active THEN
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
           (
               c.reservation_id IS NOT NULL
               AND r.status = 'confirmed'
               AND upper(c.during) > clock_timestamp()
           ) OR
           (
               c.reservation_id IS NULL
               AND h.status = 'active'
               AND h.expires_at > clock_timestamp()
           )
       );

    IF v_live_claims > 0 THEN
        RAISE EXCEPTION
            'Resource % has live commitments; capacity/active change requires explicit handling',
            OLD.id
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_resource_commitment_sensitive_change() OWNER TO request_engine_schema_owner;

--
-- Name: guard_resource_location_assignment(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_resource_location_assignment() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
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
    IF EXISTS (
        SELECT 1
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = OLD.organization_id
           AND c.resource_location_assignment_id = OLD.id
           AND NOT (NEW.effective_during @> c.during)
    ) THEN
        RAISE EXCEPTION 'ResourceLocationAssignment % effective range cannot exclude existing CapacityClaim provenance', OLD.id
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_resource_location_assignment() OWNER TO request_engine_schema_owner;

--
-- Name: guard_service_session_interruption_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_service_session_interruption_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ServiceSessionInterruption is append-preserving'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.id IS DISTINCT FROM NEW.id
       OR OLD.service_session_id IS DISTINCT FROM NEW.service_session_id
       OR OLD.kind IS DISTINCT FROM NEW.kind
       OR OLD.started_at IS DISTINCT FROM NEW.started_at
       OR OLD.started_by_principal_id IS DISTINCT FROM NEW.started_by_principal_id
       OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'ServiceSessionInterruption historical identity is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.ended_at IS NOT NULL AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ended ServiceSessionInterruption is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.ended_at IS NULL AND (
        NEW.ended_at IS NULL OR NEW.ended_by_principal_id IS NULL
    ) AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION
            'ServiceSessionInterruption may only transition atomically from open to ended'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_service_session_interruption_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_service_session_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_service_session_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.queue_entry_id IS DISTINCT FROM NEW.queue_entry_id
       OR OLD.resource_id IS DISTINCT FROM NEW.resource_id
       OR OLD.location_id IS DISTINCT FROM NEW.location_id THEN
        RAISE EXCEPTION 'ServiceSession execution identity cannot be retargeted'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.status = 'completed' AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'completed ServiceSession is immutable'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.status <> OLD.status AND NOT (
        (OLD.status = 'active' AND NEW.status IN ('paused', 'completed')) OR
        (OLD.status = 'paused' AND NEW.status = 'active')
    ) THEN
        RAISE EXCEPTION 'invalid ServiceSession transition from % to %', OLD.status, NEW.status
            USING ERRCODE = '23514';
    END IF;
    IF NEW.revision <> OLD.revision + 1 AND NEW IS DISTINCT FROM OLD THEN
        RAISE EXCEPTION 'ServiceSession revision must advance exactly one step'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.started_at IS DISTINCT FROM OLD.started_at THEN
        RAISE EXCEPTION 'ServiceSession started_at is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_service_session_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_shared_capacity_binding(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_shared_capacity_binding() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF OLD.shared_capacity_identity_id <> NEW.shared_capacity_identity_id
       OR OLD.organization_id <> NEW.organization_id
       OR OLD.resource_id <> NEW.resource_id
       OR OLD.valid_from <> NEW.valid_from
       OR OLD.authorized_by <> NEW.authorized_by
       OR OLD.authorization_reason <> NEW.authorization_reason
       OR OLD.created_at <> NEW.created_at
    THEN
        RAISE EXCEPTION 'SharedCapacityBinding identity and creation provenance are immutable'
            USING ERRCODE = '55000';
    END IF;

    IF OLD.status = 'revoked' AND NEW.status <> 'revoked' THEN
        RAISE EXCEPTION 'revoked SharedCapacityBinding cannot be reactivated'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'SharedCapacityBinding revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_shared_capacity_binding() OWNER TO request_engine_schema_owner;

--
-- Name: guard_shared_capacity_rebinding(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_shared_capacity_rebinding() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM request_engine.capacity_claims c
          JOIN request_engine.shared_capacity_claim_links link
            ON link.capacity_claim_id = c.id
          LEFT JOIN request_engine.reservations r
            ON r.organization_id = c.organization_id
           AND r.id = c.reservation_id
          LEFT JOIN request_engine.capacity_holds h
            ON h.organization_id = c.organization_id
           AND h.id = c.hold_id
         WHERE c.organization_id = NEW.organization_id
           AND c.resource_id = NEW.resource_id
           AND link.shared_capacity_identity_id <> NEW.shared_capacity_identity_id
           AND c.status = 'active'
           AND (
               (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
               OR
               (c.reservation_id IS NULL AND h.status = 'active'
                AND h.expires_at > clock_timestamp())
           )
    ) THEN
        RAISE EXCEPTION 'Resource has live commitments bound to another shared capacity root'
            USING ERRCODE = '55000';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_shared_capacity_rebinding() OWNER TO request_engine_schema_owner;

--
-- Name: guard_slot_offer_live_hold(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_slot_offer_live_hold() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_hold_status text;
    v_hold_expires timestamptz;
    v_hold_offering_version_id uuid;
    v_hold_subject_party_id uuid;
    v_hold_location_id uuid;
    v_hold_during tstzrange;
    v_opportunity_status text;
    v_opportunity_offering_version_id uuid;
    v_opportunity_location_id uuid;
    v_opportunity_during tstzrange;
    v_waitlist_status text;
    v_waitlist_subject_party_id uuid;
    v_waitlist_offering_id uuid;
    v_waitlist_location_id uuid;
    v_version_offering_id uuid;
BEGIN
    IF NEW.status <> 'offered' THEN
        RETURN NEW;
    END IF;

    -- Serialize the semantic source state in the same order as Queue issuance:
    -- Opportunity -> WaitlistEntry -> Hold. FK checks alone do not prevent a
    -- concurrent status transition after this trigger has observed a live row.
    PERFORM 1
      FROM request_engine.slot_opportunities
     WHERE organization_id = NEW.organization_id
       AND id = NEW.slot_opportunity_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
      FROM request_engine.waitlist_entries
     WHERE organization_id = NEW.organization_id
       AND id = NEW.waitlist_entry_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    PERFORM 1
      FROM request_engine.capacity_holds
     WHERE organization_id = NEW.organization_id
       AND id = NEW.capacity_hold_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    SELECT h.status,
           h.expires_at,
           h.offering_version_id,
           h.subject_party_id,
           h.location_id,
           h.during,
           o.status,
           o.offering_version_id,
           o.location_id,
           o.during,
           w.status,
           w.subject_party_id,
           w.offering_id,
           w.location_id,
           ov.offering_id
      INTO v_hold_status,
           v_hold_expires,
           v_hold_offering_version_id,
           v_hold_subject_party_id,
           v_hold_location_id,
           v_hold_during,
           v_opportunity_status,
           v_opportunity_offering_version_id,
           v_opportunity_location_id,
           v_opportunity_during,
           v_waitlist_status,
           v_waitlist_subject_party_id,
           v_waitlist_offering_id,
           v_waitlist_location_id,
           v_version_offering_id
      FROM request_engine.capacity_holds h
      JOIN request_engine.slot_opportunities o
        ON o.organization_id = h.organization_id
       AND o.id = NEW.slot_opportunity_id
      JOIN request_engine.waitlist_entries w
        ON w.organization_id = h.organization_id
       AND w.id = NEW.waitlist_entry_id
      JOIN request_engine.offering_versions ov
        ON ov.organization_id = o.organization_id
       AND ov.id = o.offering_version_id
     WHERE h.organization_id = NEW.organization_id
       AND h.id = NEW.capacity_hold_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'SlotOffer references an invalid booking intent'
            USING ERRCODE = '23514';
    END IF;

    IF v_opportunity_status <> 'open'
       OR v_waitlist_status <> 'active'
       OR v_hold_status <> 'active'
       OR v_hold_expires <= clock_timestamp()
    THEN
        RAISE EXCEPTION 'offered SlotOffer requires live source state'
            USING ERRCODE = '23514';
    END IF;

    IF v_hold_subject_party_id <> v_waitlist_subject_party_id
       OR v_hold_offering_version_id <> v_opportunity_offering_version_id
       OR v_waitlist_offering_id <> v_version_offering_id
       OR v_hold_location_id IS DISTINCT FROM v_opportunity_location_id
       OR (
           v_waitlist_location_id IS NOT NULL
           AND v_waitlist_location_id IS DISTINCT FROM v_opportunity_location_id
       )
       OR v_hold_during <> v_opportunity_during
    THEN
        RAISE EXCEPTION 'SlotOffer Hold, WaitlistEntry and SlotOpportunity provenance mismatch'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.expires_at > v_hold_expires
       OR NEW.expires_at > lower(v_opportunity_during)
    THEN
        RAISE EXCEPTION 'SlotOffer cannot outlive its Hold or opportunity start'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_slot_offer_live_hold() OWNER TO request_engine_schema_owner;

--
-- Name: guard_slot_offer_provenance_update(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_slot_offer_provenance_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF OLD.organization_id IS DISTINCT FROM NEW.organization_id
       OR OLD.slot_opportunity_id IS DISTINCT FROM NEW.slot_opportunity_id
       OR OLD.waitlist_entry_id IS DISTINCT FROM NEW.waitlist_entry_id
       OR OLD.capacity_hold_id IS DISTINCT FROM NEW.capacity_hold_id
       OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
       OR OLD.created_at IS DISTINCT FROM NEW.created_at
    THEN
        RAISE EXCEPTION 'SlotOffer booking provenance is immutable'
            USING ERRCODE = '55000';
    END IF;

    IF NEW.revision < OLD.revision THEN
        RAISE EXCEPTION 'SlotOffer revision cannot move backwards'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.status IS DISTINCT FROM OLD.status
       AND NEW.revision <= OLD.revision
    THEN
        RAISE EXCEPTION 'SlotOffer lifecycle transition requires revision advance'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_slot_offer_provenance_update() OWNER TO request_engine_schema_owner;

--
-- Name: guard_slot_offer_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_slot_offer_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_slot_offer_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_slot_opportunity_provenance_update(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_slot_opportunity_provenance_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM request_engine.slot_offers
         WHERE organization_id = OLD.organization_id
           AND slot_opportunity_id = OLD.id
    ) AND (
        OLD.organization_id IS DISTINCT FROM NEW.organization_id
        OR OLD.offering_version_id IS DISTINCT FROM NEW.offering_version_id
        OR OLD.location_id IS DISTINCT FROM NEW.location_id
        OR OLD.source_reservation_id IS DISTINCT FROM NEW.source_reservation_id
        OR OLD.source_event_id IS DISTINCT FROM NEW.source_event_id
        OR OLD.during IS DISTINCT FROM NEW.during
        OR OLD.created_at IS DISTINCT FROM NEW.created_at
    ) THEN
        RAISE EXCEPTION 'SlotOffer source state is no longer valid: SlotOpportunity booking provenance is immutable after SlotOffer reference'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_slot_opportunity_provenance_update() OWNER TO request_engine_schema_owner;

--
-- Name: guard_slot_opportunity_transition(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_slot_opportunity_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.guard_slot_opportunity_transition() OWNER TO request_engine_schema_owner;

--
-- Name: guard_waitlist_entry_provenance_update(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_waitlist_entry_provenance_update() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM request_engine.slot_offers
         WHERE organization_id = OLD.organization_id
           AND waitlist_entry_id = OLD.id
    ) AND (
        OLD.organization_id IS DISTINCT FROM NEW.organization_id
        OR OLD.offering_id IS DISTINCT FROM NEW.offering_id
        OR OLD.subject_party_id IS DISTINCT FROM NEW.subject_party_id
        OR OLD.location_id IS DISTINCT FROM NEW.location_id
        OR OLD.preferred_resource_id IS DISTINCT FROM NEW.preferred_resource_id
        OR OLD.earliest_start IS DISTINCT FROM NEW.earliest_start
        OR OLD.latest_start IS DISTINCT FROM NEW.latest_start
        OR OLD.created_at IS DISTINCT FROM NEW.created_at
    ) THEN
        RAISE EXCEPTION 'SlotOffer source state is no longer valid: WaitlistEntry booking provenance is immutable after SlotOffer reference'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.guard_waitlist_entry_provenance_update() OWNER TO request_engine_schema_owner;

--
-- Name: has_active_discovery_mapping(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_discovery_definer
--

CREATE FUNCTION request_engine.has_active_discovery_mapping(p_classification_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT EXISTS (
        SELECT 1
          FROM request_engine.offering_service_classifications m
         WHERE m.service_classification_id = p_classification_id
           AND m.status = 'active'
    )
$$;


ALTER FUNCTION request_engine.has_active_discovery_mapping(p_classification_id uuid) OWNER TO request_engine_discovery_definer;

--
-- Name: identity_exchange_country_code_v1(text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.identity_exchange_country_code_v1(p_code text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path TO 'pg_catalog'
    AS $$
SELECT p_code = ANY(string_to_array(
'AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW', ' '))
$$;


ALTER FUNCTION request_engine.identity_exchange_country_code_v1(p_code text) OWNER TO request_engine_schema_owner;

--
-- Name: identity_exchange_existing_party_v1(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.identity_exchange_existing_party_v1(p_candidate_id uuid, p_principal_id uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_party uuid;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity adoption actor context mismatch' USING ERRCODE = '42501';
    END IF;
    SELECT b.party_id INTO v_party
    FROM request_engine.identity_exchange_candidates c
    JOIN request_engine.organization_party_bindings b
      ON b.organization_id = c.organization_id
     AND b.portable_party_id = c.portable_party_id AND b.active
    WHERE c.id = p_candidate_id AND c.organization_id = v_org
      AND c.created_by_principal_id = p_principal_id LIMIT 1;
    RETURN v_party;
END
$$;


ALTER FUNCTION request_engine.identity_exchange_existing_party_v1(p_candidate_id uuid, p_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: identity_exchange_identifier_valid_v1(text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.identity_exchange_identifier_valid_v1(p_kind text, p_authority text) RETURNS boolean
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
SELECT (p_kind = 'cedula' AND p_authority = 'DO:JCE')
    OR (p_kind = 'rnc' AND p_authority = 'DO:DGII')
    OR (p_kind = 'passport' AND request_engine.identity_exchange_country_code_v1(p_authority))
$$;


ALTER FUNCTION request_engine.identity_exchange_identifier_valid_v1(p_kind text, p_authority text) OWNER TO request_engine_schema_owner;

--
-- Name: identity_exchange_subject_kind_v1(text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.identity_exchange_subject_kind_v1(p_kind text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    SET search_path TO 'pg_catalog'
    AS $$
SELECT CASE WHEN p_kind IN ('cedula','passport') THEN 'person'
            WHEN p_kind = 'rnc' THEN 'organization' END
$$;


ALTER FUNCTION request_engine.identity_exchange_subject_kind_v1(p_kind text) OWNER TO request_engine_schema_owner;

--
-- Name: initialize_queue_entry_times(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.initialize_queue_entry_times() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_now timestamptz;
BEGIN
    IF NEW.arrived_at IS NULL AND NEW.admitted_at IS NULL THEN
        v_now := clock_timestamp();
        NEW.arrived_at := v_now;
        NEW.admitted_at := v_now;
    ELSIF NEW.arrived_at IS NULL THEN
        NEW.arrived_at := NEW.admitted_at;
    ELSIF NEW.admitted_at IS NULL THEN
        NEW.admitted_at := NEW.arrived_at;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.initialize_queue_entry_times() OWNER TO request_engine_schema_owner;

--
-- Name: initialize_service_queue_intake_control(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.initialize_service_queue_intake_control() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    INSERT INTO request_engine.service_queue_intake_controls (
        organization_id, service_queue_id
    ) VALUES (NEW.organization_id, NEW.id)
    ON CONFLICT DO NOTHING;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.initialize_service_queue_intake_control() OWNER TO request_engine_schema_owner;

--
-- Name: issue_discovery_booking_handoff(text, uuid, bigint, uuid, bigint, uuid, uuid, jsonb, timestamp with time zone); Type: FUNCTION; Schema: request_engine; Owner: request_engine_discovery_definer
--

CREATE FUNCTION request_engine.issue_discovery_booking_handoff(p_token_hash text, p_publication_id uuid, p_expected_publication_revision bigint, p_mapping_id uuid, p_expected_mapping_revision bigint, p_offering_version_id uuid, p_location_id uuid, p_selection jsonb, p_expires_at timestamp with time zone) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
DECLARE
    v_publication request_engine.discovery_publications%ROWTYPE;
    v_mapping request_engine.offering_service_classifications%ROWTYPE;
    v_latest_version_id uuid;
    v_latest_bookable boolean;
    v_start timestamptz;
    v_end timestamptz;
    v_selection_offering_version uuid;
    v_selection_location uuid;
    v_duration integer;
    v_amount numeric;
    v_location_revision bigint;
    v_id uuid;
BEGIN
    IF p_token_hash IS NULL OR p_token_hash !~ '^[0-9a-f]{64}$'
       OR p_selection IS NULL
       OR COALESCE(jsonb_typeof(p_selection), '') <> 'object'
       OR COALESCE(jsonb_typeof(p_selection->'resources'), '') <> 'array'
       OR NULLIF(btrim(p_selection->>'currency'), '') IS NULL
       OR (p_selection->>'currency') !~ '^[A-Z]{3}$'
       OR NULLIF(btrim(p_selection->>'configuration_fingerprint'), '') IS NULL THEN
        RAISE EXCEPTION 'invalid discovery handoff payload' USING ERRCODE = '22023';
    END IF;
    IF jsonb_array_length(p_selection->'resources') = 0 THEN
        RAISE EXCEPTION 'discovery handoff resources are required' USING ERRCODE = '22023';
    END IF;
    IF p_expected_publication_revision < 1 OR p_expected_mapping_revision < 1 THEN
        RAISE EXCEPTION 'invalid discovery handoff observation' USING ERRCODE = '22023';
    END IF;
    IF p_expires_at <= clock_timestamp()
       OR p_expires_at > clock_timestamp() + interval '15 minutes' THEN
        RAISE EXCEPTION 'invalid discovery handoff expiry' USING ERRCODE = '22023';
    END IF;
    BEGIN
        v_start := (p_selection->>'start_at')::timestamptz;
        v_end := (p_selection->>'end_at')::timestamptz;
        v_selection_offering_version := (p_selection->>'offering_version_id')::uuid;
        v_selection_location := (p_selection->>'location_id')::uuid;
        v_duration := (p_selection->>'planned_duration_minutes')::integer;
        v_amount := (p_selection->>'amount')::numeric;
        v_location_revision := (p_selection->>'location_operational_revision')::bigint;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'invalid discovery handoff selection' USING ERRCODE = '22023';
    END;
    IF v_end <= v_start
       OR v_duration <= 0
       OR v_amount < 0
       OR v_location_revision <= 0
       OR v_selection_offering_version <> p_offering_version_id
       OR v_selection_location <> p_location_id THEN
        RAISE EXCEPTION 'discovery handoff selection mismatch' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO v_publication
      FROM request_engine.discovery_publications
     WHERE id = p_publication_id
       AND status = 'active'
       AND revision = p_expected_publication_revision
       AND tstzrange(v_start, v_end, '[)') <@ effective_during
     FOR SHARE;
    IF NOT FOUND OR v_publication.location_id <> p_location_id THEN
        RAISE EXCEPTION 'discovery publication unavailable' USING ERRCODE = '40001';
    END IF;

    SELECT * INTO v_mapping
      FROM request_engine.offering_service_classifications
     WHERE organization_id = v_publication.organization_id
       AND offering_id = v_publication.offering_id
       AND id = p_mapping_id
       AND revision = p_expected_mapping_revision
       AND status = 'active'
     FOR SHARE;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1
          FROM request_engine.service_classifications sc
         WHERE sc.id = v_mapping.service_classification_id
           AND sc.status = 'active'
    ) THEN
        RAISE EXCEPTION 'discovery mapping unavailable' USING ERRCODE = '40001';
    END IF;

    SELECT ov.id, ov.bookable
      INTO v_latest_version_id, v_latest_bookable
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = v_publication.organization_id
       AND ov.offering_id = v_publication.offering_id
     ORDER BY ov.version DESC
     LIMIT 1;
    IF NOT FOUND OR v_latest_version_id <> p_offering_version_id OR NOT v_latest_bookable THEN
        RAISE EXCEPTION 'offering version unavailable' USING ERRCODE = '40001';
    END IF;

    IF v_publication.resource_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
          FROM jsonb_array_elements(p_selection->'resources') item
         WHERE item->>'resource_id' = v_publication.resource_id::text
    ) THEN
        RAISE EXCEPTION 'discovery selection escaped publication scope' USING ERRCODE = '23514';
    END IF;

    INSERT INTO request_engine.discovery_booking_handoffs (
        token_hash, organization_id, publication_id, publication_revision,
        mapping_id, mapping_revision, offering_version_id, location_id,
        selection, expires_at
    ) VALUES (
        p_token_hash, v_publication.organization_id, v_publication.id, v_publication.revision,
        v_mapping.id, v_mapping.revision, p_offering_version_id, p_location_id,
        p_selection, p_expires_at
    ) RETURNING id INTO v_id;
    RETURN v_id;
END
$_$;


ALTER FUNCTION request_engine.issue_discovery_booking_handoff(p_token_hash text, p_publication_id uuid, p_expected_publication_revision bigint, p_mapping_id uuid, p_expected_mapping_revision bigint, p_offering_version_id uuid, p_location_id uuid, p_selection jsonb, p_expires_at timestamp with time zone) OWNER TO request_engine_discovery_definer;

--
-- Name: lock_booking_context_terms_resource(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.lock_booking_context_terms_resource() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.lock_booking_context_terms_resource() OWNER TO request_engine_schema_owner;

--
-- Name: lock_current_party_authority(uuid, uuid, uuid, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) RETURNS TABLE(representation_id uuid, authority_kind text, valid_from timestamp with time zone, valid_until timestamp with time zone)
    LANGUAGE sql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
    SELECT
        r.id,
        r.authority_kind,
        r.valid_from,
        r.valid_until
    FROM request_engine.representations r
    JOIN request_engine.principals p
      ON p.organization_id = r.organization_id
     AND p.id = r.principal_id
    JOIN request_engine.parties party
      ON party.organization_id = r.organization_id
     AND party.id = r.represented_party_id
    CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
    WHERE p_scope_key <> ''
      AND r.organization_id = p_organization_id
      AND r.principal_id = p_principal_id
      AND r.represented_party_id = p_represented_party_id
      AND r.scope_key = p_scope_key
      AND r.status = 'active'
      AND p.active
      AND party.active
      AND r.valid_from <= clock.db_now
      AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
    ORDER BY r.valid_from DESC, r.id DESC
    LIMIT 1
    FOR SHARE OF r, p, party
$$;


ALTER FUNCTION request_engine.lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) OWNER TO request_engine_schema_owner;

--
-- Name: lock_offering_version_booking_terms_root(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.lock_offering_version_booking_terms_root() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
              FROM request_engine.offering_versions ov
              JOIN request_engine.offerings o
                ON o.organization_id = ov.organization_id
               AND o.id = ov.offering_id
             WHERE ov.organization_id = v_org
               AND ov.id = v_offering_version
             FOR UPDATE OF o;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'OfferingVersion % not found while changing base booking terms',
                    v_offering_version USING ERRCODE = '23503';
            END IF;

            RETURN COALESCE(NEW, OLD);
        END
        $$;


ALTER FUNCTION request_engine.lock_offering_version_booking_terms_root() OWNER TO request_engine_schema_owner;

--
-- Name: lookup_active_service_classification(text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.lookup_active_service_classification(p_key text) RETURNS TABLE(id uuid, classification_key text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT sc.id, sc.classification_key
      FROM request_engine.service_classifications sc
     WHERE sc.classification_key = p_key
       AND sc.status = 'active'
$$;


ALTER FUNCTION request_engine.lookup_active_service_classification(p_key text) OWNER TO request_engine_schema_owner;

--
-- Name: lookup_service_classification(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.lookup_service_classification(p_id uuid) RETURNS TABLE(id uuid, classification_key text, status text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT sc.id, sc.classification_key, sc.status
      FROM request_engine.service_classifications sc
     WHERE sc.id = p_id
$$;


ALTER FUNCTION request_engine.lookup_service_classification(p_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: publish_portable_party_v1(uuid, text, text, text, text[], uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.publish_portable_party_v1(p_party_id uuid, p_kind text, p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_party_kind text;
    v_bound_identity uuid;
    v_identifier_identity uuid;
    v_identity uuid;
    v_bound_party uuid;
    v_name text;
    v_contacts jsonb;
    v_insurance jsonb;
    v_profile jsonb := '{}'::jsonb;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    v_party_kind := request_engine.identity_exchange_subject_kind_v1(p_kind);
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity exchange actor context mismatch' USING ERRCODE = '42501';
    END IF;
    IF v_party_kind IS NULL
       OR NOT request_engine.identity_exchange_identifier_valid_v1(p_kind, p_authority)
       OR p_fingerprint !~ '^[0-9a-f]{64}$'
       OR cardinality(p_consent_fields) = 0
       OR NOT ('display_name' = ANY(p_consent_fields))
       OR EXISTS (SELECT 1 FROM unnest(p_consent_fields) AS field
                  WHERE field <> ALL(ARRAY['display_name','phone','email','insurance_member']))
       OR (v_party_kind = 'organization' AND 'insurance_member' = ANY(p_consent_fields)) THEN
        RAISE EXCEPTION 'invalid portable profile contract' USING ERRCODE = '22023';
    END IF;

    SELECT p.display_name INTO v_name
    FROM request_engine.parties p
    JOIN request_engine.party_identity_documents d
      ON d.organization_id = p.organization_id AND d.party_id = p.id
     AND d.kind = p_kind AND d.authority = p_authority AND d.active
    WHERE p.organization_id = v_org AND p.id = p_party_id AND p.active
      AND p.party_kind = v_party_kind LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active Party with compatible scoped identity is required'
            USING ERRCODE = '22023';
    END IF;

    SELECT coalesce(jsonb_agg(jsonb_build_object('channel', c.channel, 'value', c.normalized_value)
        ORDER BY c.id), '[]'::jsonb) INTO v_contacts
    FROM request_engine.party_contact_points c
    WHERE c.organization_id = v_org AND c.party_id = p_party_id AND c.active
      AND ((c.channel IN ('phone','whatsapp') AND 'phone' = ANY(p_consent_fields))
        OR (c.channel = 'email' AND 'email' = ANY(p_consent_fields)));
    SELECT coalesce(jsonb_agg(jsonb_build_object('issuer', a.issuer, 'value', a.value)
        ORDER BY a.id), '[]'::jsonb) INTO v_insurance
    FROM request_engine.party_administrative_identifiers a
    WHERE v_party_kind = 'person' AND a.organization_id = v_org AND a.party_id = p_party_id
      AND a.active AND a.kind = 'insurance_member'
      AND 'insurance_member' = ANY(p_consent_fields);
    v_profile := jsonb_build_object('display_name', v_name);
    IF 'phone' = ANY(p_consent_fields) OR 'email' = ANY(p_consent_fields) THEN
        v_profile := v_profile || jsonb_build_object('contact_points', v_contacts);
    END IF;
    IF v_party_kind = 'person' AND 'insurance_member' = ANY(p_consent_fields) THEN
        v_profile := v_profile || jsonb_build_object('insurance_identifiers', v_insurance);
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        v_party_kind || ':' || p_kind || ':' || p_authority || ':' || p_fingerprint, 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(v_org::text || ':' || p_party_id::text, 0));
    SELECT b.portable_party_id INTO v_bound_identity
    FROM request_engine.organization_party_bindings b
    WHERE b.organization_id = v_org AND b.party_id = p_party_id AND b.active FOR UPDATE;
    SELECT i.portable_party_id INTO v_identifier_identity
    FROM request_engine.portable_party_identifiers i
    JOIN request_engine.portable_party_identities p ON p.id = i.portable_party_id AND p.active
    WHERE i.party_kind = v_party_kind AND i.kind = p_kind AND i.authority = p_authority
      AND i.fingerprint = p_fingerprint AND i.active FOR UPDATE OF i;
    IF v_bound_identity IS NOT NULL AND v_identifier_identity IS NOT NULL
       AND v_bound_identity <> v_identifier_identity THEN
        RAISE EXCEPTION 'document would join two portable identities' USING ERRCODE = '23505';
    END IF;
    v_identity := coalesce(v_bound_identity, v_identifier_identity);
    IF v_identity IS NULL THEN
        INSERT INTO request_engine.portable_party_identities(party_kind)
        VALUES (v_party_kind) RETURNING id INTO v_identity;
    ELSIF NOT EXISTS (SELECT 1 FROM request_engine.portable_party_identities p
                      WHERE p.id = v_identity AND p.party_kind = v_party_kind AND p.active) THEN
        RAISE EXCEPTION 'portable identity Party kind mismatch' USING ERRCODE = '23514';
    END IF;
    IF v_identifier_identity IS NULL THEN
        INSERT INTO request_engine.portable_party_identifiers(
            portable_party_id, party_kind, kind, authority, fingerprint)
        VALUES (v_identity, v_party_kind, p_kind, p_authority, p_fingerprint);
    END IF;
    INSERT INTO request_engine.portable_party_profiles(
        portable_party_id, publisher_organization_id, profile)
    VALUES (v_identity, v_org, v_profile)
    ON CONFLICT (portable_party_id, publisher_organization_id) DO UPDATE
    SET profile = EXCLUDED.profile, active = true, updated_at = clock_timestamp();
    SELECT b.party_id INTO v_bound_party
    FROM request_engine.organization_party_bindings b
    WHERE b.organization_id = v_org AND b.portable_party_id = v_identity AND b.active FOR UPDATE;
    IF v_bound_party IS NOT NULL AND v_bound_party <> p_party_id THEN
        RAISE EXCEPTION 'portable identity already belongs to another local Party'
            USING ERRCODE = '23505';
    END IF;
    IF v_bound_identity IS NULL THEN
        INSERT INTO request_engine.organization_party_bindings(
            organization_id, party_id, portable_party_id, proof_kind,
            consented_fields, created_by_principal_id)
        VALUES (v_org, p_party_id, v_identity, 'operator_document_witness',
                p_consent_fields, p_principal_id);
    ELSE
        UPDATE request_engine.organization_party_bindings
        SET consented_fields = p_consent_fields, updated_at = clock_timestamp()
        WHERE organization_id = v_org AND party_id = p_party_id AND active;
    END IF;
    RETURN true;
END
$_$;


ALTER FUNCTION request_engine.publish_portable_party_v1(p_party_id uuid, p_kind text, p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_discovery_booking_handoff(text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_discovery_definer
--

CREATE FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text) RETURNS TABLE(handoff_id uuid, organization_id uuid, selection jsonb)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT h.id, h.organization_id, h.selection
      FROM request_engine.discovery_booking_handoffs h
     WHERE h.token_hash = p_token_hash
       AND h.organization_id = request_engine.current_organization_id()
       AND (h.consumed_reservation_id IS NOT NULL OR h.expires_at > now())
$$;


ALTER FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text) OWNER TO request_engine_discovery_definer;

--
-- Name: reject_immutable_mutation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.reject_immutable_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = '55000';
END
$$;


ALTER FUNCTION request_engine.reject_immutable_mutation() OWNER TO request_engine_schema_owner;

--
-- Name: reject_queue_entry_operator_selection_mutation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.reject_queue_entry_operator_selection_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION 'QueueEntry operator selections are immutable facts'
        USING ERRCODE = '23514';
END
$$;


ALTER FUNCTION request_engine.reject_queue_entry_operator_selection_mutation() OWNER TO request_engine_schema_owner;

--
-- Name: require_trusted_actor_context(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.require_trusted_actor_context(p_organization_id uuid) RETURNS uuid
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_principal_id uuid;
BEGIN
    v_organization_id := request_engine.current_organization_id();
    v_principal_id := request_engine.current_authenticated_principal_id();

    IF v_organization_id IS NULL OR v_principal_id IS NULL THEN
        RAISE EXCEPTION 'trusted actor context is required'
            USING ERRCODE = '42501';
    END IF;
    IF v_organization_id <> p_organization_id THEN
        RAISE EXCEPTION 'organization does not match trusted actor context'
            USING ERRCODE = '42501';
    END IF;
    RETURN v_principal_id;
END
$$;


ALTER FUNCTION request_engine.require_trusted_actor_context(p_organization_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: resolve_current_party_authority(uuid, uuid, uuid, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) RETURNS TABLE(representation_id uuid, authority_kind text, valid_from timestamp with time zone, valid_until timestamp with time zone)
    LANGUAGE sql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
    SELECT
        r.id,
        r.authority_kind,
        r.valid_from,
        r.valid_until
    FROM request_engine.representations r
    JOIN request_engine.principals p
      ON p.organization_id = r.organization_id
     AND p.id = r.principal_id
    JOIN request_engine.parties party
      ON party.organization_id = r.organization_id
     AND party.id = r.represented_party_id
    CROSS JOIN LATERAL (SELECT clock_timestamp() AS db_now) clock
    WHERE p_scope_key <> ''
      AND r.organization_id = p_organization_id
      AND r.principal_id = p_principal_id
      AND r.represented_party_id = p_represented_party_id
      AND r.scope_key = p_scope_key
      AND r.status = 'active'
      AND p.active
      AND party.active
      AND r.valid_from <= clock.db_now
      AND (r.valid_until IS NULL OR r.valid_until > clock.db_now)
    ORDER BY r.valid_from DESC, r.id DESC
    LIMIT 1
$$;


ALTER FUNCTION request_engine.resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) OWNER TO request_engine_schema_owner;

--
-- Name: search_discovery_candidates_v2(text, double precision, double precision, integer, timestamp with time zone, timestamp with time zone, integer); Type: FUNCTION; Schema: request_engine; Owner: request_engine_discovery_definer
--

CREATE FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) RETURNS TABLE(publication_id uuid, publication_revision bigint, mapping_id uuid, mapping_revision bigint, organization_id uuid, organization_key text, organization_display_name text, offering_id uuid, offering_key text, offering_display_name text, offering_version_id uuid, location_id uuid, location_key text, location_display_name text, location_address_line1 text, location_address_line2 text, location_locality text, location_administrative_area text, location_postal_code text, location_country_code text, resource_id uuid, provider_visibility text, provider_key text, provider_display_name text, provider_role_label text, provider_profile_image_ref text, publication_start timestamp with time zone, publication_end timestamp with time zone, distance_meters double precision)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
BEGIN
    IF p_classification_key IS NULL
       OR p_origin_latitude IS NULL
       OR p_origin_longitude IS NULL
       OR p_radius_meters IS NULL
       OR p_window_start IS NULL
       OR p_window_end IS NULL
       OR p_limit IS NULL
       OR p_classification_key !~ '^[a-z0-9]+(_[a-z0-9]+)*$'
       OR p_origin_latitude NOT BETWEEN -90 AND 90
       OR p_origin_longitude NOT BETWEEN -180 AND 180
       OR p_radius_meters NOT BETWEEN 1 AND 100000
       OR p_window_end <= p_window_start
       OR p_window_end - p_window_start > interval '7 days'
       OR p_limit NOT BETWEEN 1 AND 201 THEN
        RAISE EXCEPTION 'invalid discovery search contract' USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH eligible AS (
        SELECT
            dp.id AS publication_id,
            dp.revision AS publication_revision,
            map.id AS mapping_id,
            map.revision AS mapping_revision,
            org.id AS organization_id,
            org.organization_key,
            org.display_name AS organization_display_name,
            o.id AS offering_id,
            o.offering_key,
            o.display_name AS offering_display_name,
            latest.id AS offering_version_id,
            l.id AS location_id,
            l.location_key,
            l.display_name AS location_display_name,
            l.address_line1 AS location_address_line1,
            l.address_line2 AS location_address_line2,
            l.locality AS location_locality,
            l.administrative_area AS location_administrative_area,
            l.postal_code AS location_postal_code,
            l.country_code AS location_country_code,
            dp.resource_id,
            dp.provider_visibility,
            CASE WHEN dp.provider_visibility = 'public'
                THEN r.resource_key END AS provider_key,
            CASE WHEN dp.provider_visibility = 'public'
                THEN rpp.display_name END AS provider_display_name,
            CASE WHEN dp.provider_visibility = 'public'
                THEN rpp.role_label END AS provider_role_label,
            CASE WHEN dp.provider_visibility = 'public'
                THEN rpp.profile_image_ref END AS provider_profile_image_ref,
            lower(dp.effective_during) AS publication_start,
            upper(dp.effective_during) AS publication_end,
            6371008.8 * 2 * asin(sqrt(LEAST(1.0, GREATEST(0.0,
                power(sin(radians((l.latitude::double precision - p_origin_latitude) / 2)), 2)
                + cos(radians(p_origin_latitude))
                * cos(radians(l.latitude::double precision))
                * power(sin(radians((l.longitude::double precision - p_origin_longitude) / 2)), 2)
            )))) AS distance_meters
        FROM request_engine.discovery_publications dp
        JOIN request_engine.offering_service_classifications map
          ON map.organization_id = dp.organization_id
         AND map.offering_id = dp.offering_id
         AND map.status = 'active'
        JOIN request_engine.service_classifications sc
          ON sc.id = map.service_classification_id
         AND sc.status = 'active'
         AND sc.classification_key = p_classification_key
        JOIN request_engine.organizations org
          ON org.id = dp.organization_id
         AND org.operational_status = 'active'
        JOIN request_engine.offerings o
          ON o.organization_id = dp.organization_id
         AND o.id = dp.offering_id
         AND o.active
        JOIN LATERAL (
            SELECT ov.id, ov.bookable
              FROM request_engine.offering_versions ov
             WHERE ov.organization_id = o.organization_id
               AND ov.offering_id = o.id
             ORDER BY ov.version DESC
             LIMIT 1
        ) latest ON latest.bookable
        JOIN request_engine.locations l
          ON l.organization_id = dp.organization_id
         AND l.id = dp.location_id
         AND l.active
         AND l.latitude IS NOT NULL
         AND l.longitude IS NOT NULL
        LEFT JOIN request_engine.resources r
          ON r.organization_id = dp.organization_id
         AND r.id = dp.resource_id
        LEFT JOIN request_engine.resource_public_profiles rpp
          ON rpp.organization_id = dp.organization_id
         AND rpp.resource_id = dp.resource_id
         AND rpp.active
        WHERE dp.status = 'active'
          AND dp.effective_during && tstzrange(p_window_start, p_window_end, '[)')
          AND (dp.resource_id IS NULL OR r.active)
          AND (
              dp.provider_visibility = 'hidden'
              OR (rpp.resource_id IS NOT NULL AND rpp.display_name IS NOT NULL)
          )
    )
    SELECT e.*
      FROM eligible e
     WHERE e.distance_meters <= p_radius_meters
     ORDER BY
        e.distance_meters,
        e.organization_id,
        e.location_id,
        e.offering_id,
        e.publication_id
     LIMIT p_limit;
END
$_$;


ALTER FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) OWNER TO request_engine_discovery_definer;

--
-- Name: stamp_shared_capacity_authority_event_context(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.stamp_shared_capacity_authority_event_context() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
BEGIN
    NEW.details := COALESCE(NEW.details, '{}'::jsonb) || pg_catalog.jsonb_strip_nulls(
        pg_catalog.jsonb_build_object(
            'database_session_user', session_user,
            'authenticated_principal_id',
                NULLIF(current_setting('request_engine.authenticated_principal_id', true), ''),
            'correlation_id',
                NULLIF(current_setting('request_engine.correlation_id', true), ''),
            'principal_kind',
                NULLIF(current_setting('request_engine.principal_kind', true), ''),
            'authentication_method',
                NULLIF(current_setting('request_engine.authentication_method', true), '')
        )
    );
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.stamp_shared_capacity_authority_event_context() OWNER TO request_engine_schema_owner;

--
-- Name: touch_updated_at(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.touch_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.touch_updated_at() OWNER TO request_engine_schema_owner;

--
-- Name: validate_offering_version_delivery_policy(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.validate_offering_version_delivery_policy() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    v_access jsonb;
    v_item jsonb;
    v_access_key text;
    v_kind text;
    v_provider text;
    v_provisioning text;
    v_public_data jsonb;
    v_seen_keys text[] := ARRAY[]::text[];
BEGIN
    IF jsonb_typeof(NEW.delivery_policy) <> 'object' THEN
        RAISE EXCEPTION 'delivery_policy must be a JSON object'
            USING ERRCODE = '23514';
    END IF;

    IF NOT NEW.delivery_policy ? 'access' THEN
        RETURN NEW;
    END IF;

    v_access := NEW.delivery_policy -> 'access';
    IF jsonb_typeof(v_access) <> 'array' THEN
        RAISE EXCEPTION 'delivery_policy.access must be an array'
            USING ERRCODE = '23514';
    END IF;

    FOR v_item IN
        SELECT value
        FROM jsonb_array_elements(v_access) AS access_item(value)
    LOOP
        IF jsonb_typeof(v_item) <> 'object' THEN
            RAISE EXCEPTION 'delivery_policy.access entries must be objects'
                USING ERRCODE = '23514';
        END IF;

        IF NOT v_item ? 'key' OR jsonb_typeof(v_item -> 'key') <> 'string' THEN
            RAISE EXCEPTION 'delivery_policy.access key must be a string'
                USING ERRCODE = '23514';
        END IF;
        v_access_key := v_item ->> 'key';
        IF v_access_key = '' OR btrim(v_access_key) <> v_access_key THEN
            RAISE EXCEPTION 'delivery_policy.access key must be a non-empty trimmed string'
                USING ERRCODE = '23514';
        END IF;
        IF v_access_key = ANY(v_seen_keys) THEN
            RAISE EXCEPTION 'delivery_policy.access contains duplicate key %', v_access_key
                USING ERRCODE = '23514';
        END IF;
        v_seen_keys := array_append(v_seen_keys, v_access_key);

        IF NOT v_item ? 'kind' OR jsonb_typeof(v_item -> 'kind') <> 'string' THEN
            RAISE EXCEPTION 'delivery_policy.access kind must be a string'
                USING ERRCODE = '23514';
        END IF;
        v_kind := v_item ->> 'kind';
        IF v_kind NOT IN (
            'video_link',
            'phone',
            'physical_location',
            'instructions',
            'external_session'
        ) THEN
            RAISE EXCEPTION 'delivery_policy.access kind is unsupported: %', v_kind
                USING ERRCODE = '23514';
        END IF;

        v_provider := NULL;
        IF v_item ? 'provider' THEN
            IF jsonb_typeof(v_item -> 'provider') <> 'string' THEN
                RAISE EXCEPTION 'delivery_policy.access provider must be a string'
                    USING ERRCODE = '23514';
            END IF;
            v_provider := v_item ->> 'provider';
            IF v_provider = '' OR btrim(v_provider) <> v_provider THEN
                RAISE EXCEPTION
                    'delivery_policy.access provider must be a non-empty trimmed string'
                    USING ERRCODE = '23514';
            END IF;
        END IF;

        v_provisioning := 'immediate';
        IF v_item ? 'provisioning' THEN
            IF jsonb_typeof(v_item -> 'provisioning') <> 'string' THEN
                RAISE EXCEPTION 'delivery_policy.access provisioning must be a string'
                    USING ERRCODE = '23514';
            END IF;
            v_provisioning := v_item ->> 'provisioning';
        END IF;
        IF v_provisioning NOT IN ('immediate', 'manual') THEN
            RAISE EXCEPTION 'delivery_policy.access provisioning is unsupported: %', v_provisioning
                USING ERRCODE = '23514';
        END IF;

        v_public_data := '{}'::jsonb;
        IF v_item ? 'public_data' THEN
            IF jsonb_typeof(v_item -> 'public_data') <> 'object' THEN
                RAISE EXCEPTION 'delivery_policy.access public_data must be an object'
                    USING ERRCODE = '23514';
            END IF;
            v_public_data := v_item -> 'public_data';
        END IF;

        IF v_provisioning = 'immediate'
           AND v_provider IS NULL
           AND v_public_data = '{}'::jsonb
        THEN
            RAISE EXCEPTION
                'immediate static delivery access requires non-empty public_data'
                USING ERRCODE = '23514';
        END IF;
    END LOOP;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.validate_offering_version_delivery_policy() OWNER TO request_engine_schema_owner;

--
-- Name: recovery_source_revision(uuid, uuid); Type: FUNCTION; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) RETURNS bigint
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT revision
    FROM request_engine.recovery_source_revisions
    WHERE organization_id = p_organization_id
      AND service_queue_id = p_service_queue_id
$$;


ALTER FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) OWNER TO request_engine_schema_owner;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: outbox_messages; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.outbox_messages (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    event_type text NOT NULL,
    schema_version integer DEFAULT 1 NOT NULL,
    aggregate_kind text,
    aggregate_id uuid,
    payload jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 12 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_error_class text,
    occurred_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    delivered_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    replay_count integer DEFAULT 0 NOT NULL,
    last_replayed_at timestamp with time zone,
    correlation_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT outbox_messages_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT outbox_messages_check CHECK (((status = 'leased'::text) = ((claim_token IS NOT NULL) AND (lease_until IS NOT NULL)))),
    CONSTRAINT outbox_messages_check1 CHECK (((status <> 'delivered'::text) OR (delivered_at IS NOT NULL))),
    CONSTRAINT outbox_messages_correlation_data_object_ck CHECK ((jsonb_typeof(correlation_data) = 'object'::text)),
    CONSTRAINT outbox_messages_event_type_check CHECK ((event_type <> ''::text)),
    CONSTRAINT outbox_messages_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT outbox_messages_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT outbox_messages_replay_count_check CHECK ((replay_count >= 0)),
    CONSTRAINT outbox_messages_schema_version_check CHECK ((schema_version > 0)),
    CONSTRAINT outbox_messages_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'leased'::text, 'delivered'::text, 'dead'::text])))
);


ALTER TABLE request_engine.outbox_messages OWNER TO request_engine_schema_owner;

--
-- Name: provider_events; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.provider_events (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    provider_key text NOT NULL,
    connection_key text NOT NULL,
    provider_event_id text NOT NULL,
    payload_hash text NOT NULL,
    payload jsonb NOT NULL,
    status text DEFAULT 'received'::text NOT NULL,
    received_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    processed_at timestamp with time zone,
    error_class text,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_error_class text,
    replay_count integer DEFAULT 0 NOT NULL,
    last_replayed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT provider_events_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT provider_events_connection_key_check CHECK ((connection_key <> ''::text)),
    CONSTRAINT provider_events_lease_shape_check CHECK (((status = 'leased'::text) = ((claim_token IS NOT NULL) AND (lease_until IS NOT NULL)))),
    CONSTRAINT provider_events_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT provider_events_payload_hash_check CHECK ((payload_hash <> ''::text)),
    CONSTRAINT provider_events_provider_event_id_check CHECK ((provider_event_id <> ''::text)),
    CONSTRAINT provider_events_provider_key_check CHECK ((provider_key <> ''::text)),
    CONSTRAINT provider_events_replay_count_check CHECK ((replay_count >= 0)),
    CONSTRAINT provider_events_status_v4_check CHECK ((status = ANY (ARRAY['received'::text, 'leased'::text, 'processed'::text, 'rejected'::text, 'dead'::text]))),
