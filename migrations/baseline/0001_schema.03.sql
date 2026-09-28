    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_identity uuid;
    v_identity_kind text;
    v_local_kind text;
    v_binding uuid;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity binding actor context mismatch' USING ERRCODE = '42501';
    END IF;
    SELECT c.portable_party_id, i.party_kind INTO v_identity, v_identity_kind
    FROM request_engine.identity_exchange_candidates c
    JOIN request_engine.portable_party_identities i ON i.id = c.portable_party_id AND i.active
    WHERE c.id = p_candidate_id AND c.organization_id = v_org
      AND c.created_by_principal_id = p_principal_id AND c.consumed_at IS NOT NULL;
    SELECT p.party_kind INTO v_local_kind FROM request_engine.parties p
    WHERE p.organization_id = v_org AND p.id = p_party_id AND p.active;
    IF v_identity IS NULL OR v_local_kind IS NULL OR v_local_kind <> v_identity_kind THEN
        RAISE EXCEPTION 'candidate and local Party are not kind-compatible' USING ERRCODE = '22023';
    END IF;
    INSERT INTO request_engine.organization_party_bindings(
        organization_id, party_id, portable_party_id, proof_kind,
        consented_fields, created_by_principal_id)
    VALUES (v_org, p_party_id, v_identity, 'operator_document_witness',
            p_consent_fields, p_principal_id)
    RETURNING id INTO v_binding;
    RETURN v_binding;
END
$$;


ALTER FUNCTION request_engine.bind_consumed_identity_candidate_v1(p_candidate_id uuid, p_party_id uuid, p_consent_fields text[], p_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: bump_capacity_claim_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_capacity_claim_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_resource_id uuid;
    v_reservation_id uuid;
    v_queue_id uuid;
    v_scope integer;
    v_scopes integer := 1;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_resource_id := OLD.resource_id;
        v_reservation_id := OLD.reservation_id;
    ELSE
        IF TG_OP = 'UPDATE'
           AND (NEW.organization_id, NEW.resource_id, NEW.hold_id,
                NEW.reservation_id, NEW.during, NEW.quantity, NEW.status)
               IS NOT DISTINCT FROM
               (OLD.organization_id, OLD.resource_id, OLD.hold_id,
                OLD.reservation_id, OLD.during, OLD.quantity, OLD.status) THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'UPDATE'
           AND (OLD.organization_id, OLD.resource_id, OLD.hold_id, OLD.reservation_id)
               IS DISTINCT FROM
               (NEW.organization_id, NEW.resource_id, NEW.hold_id, NEW.reservation_id) THEN
            v_scopes := 2;
        END IF;
        v_organization_id := NEW.organization_id;
        v_resource_id := NEW.resource_id;
        v_reservation_id := NEW.reservation_id;
    END IF;

    FOR v_scope IN 1..v_scopes LOOP
        IF v_scope = 2 THEN
            v_organization_id := OLD.organization_id;
            v_resource_id := OLD.resource_id;
            v_reservation_id := OLD.reservation_id;
        END IF;
        FOR v_queue_id IN
            SELECT p.service_queue_id
            FROM request_engine.live_capacity_projection_policies p
            WHERE p.organization_id = v_organization_id
              AND p.resource_id = v_resource_id
              AND (
                  v_reservation_id IS NULL
                  OR p.location_id = (
                      SELECT r.location_id
                      FROM request_engine.reservations r
                      WHERE r.organization_id = v_organization_id
                        AND r.id = v_reservation_id
                  )
              )
        LOOP
            PERFORM request_engine.bump_recovery_source_revision(
                v_organization_id, v_queue_id
            );
        END LOOP;
    END LOOP;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_capacity_claim_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_direct_queue_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_direct_queue_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM request_engine.bump_recovery_source_revision(
            OLD.organization_id,
            OLD.service_queue_id
        );
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE'
       AND (OLD.organization_id, OLD.service_queue_id)
           IS DISTINCT FROM (NEW.organization_id, NEW.service_queue_id) THEN
        PERFORM request_engine.bump_recovery_source_revision(
            OLD.organization_id,
            OLD.service_queue_id
        );
    END IF;

    PERFORM request_engine.bump_recovery_source_revision(
        NEW.organization_id,
        NEW.service_queue_id
    );
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_direct_queue_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_estimate_policy_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_estimate_policy_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
    ELSE
        v_organization_id := NEW.organization_id;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = v_organization_id
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_estimate_policy_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_intake_control_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_intake_control_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF NEW.accepting IS NOT DISTINCT FROM OLD.accepting
               AND NEW.reason IS NOT DISTINCT FROM OLD.reason
               AND NEW.effective_until IS NOT DISTINCT FROM OLD.effective_until THEN
                RETURN NULL;
            END IF;
            PERFORM request_engine.bump_recovery_source_revision(
                NEW.organization_id,
                NEW.service_queue_id
            );
            RETURN NULL;
        END
        $$;


ALTER FUNCTION request_engine.bump_intake_control_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_interruption_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_interruption_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_session_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_session_id := OLD.service_session_id;
    ELSE
        v_organization_id := NEW.organization_id;
        v_session_id := NEW.service_session_id;
    END IF;
    SELECT q.service_queue_id INTO v_queue_id
    FROM request_engine.service_sessions s
    JOIN request_engine.queue_entries q
      ON q.organization_id = s.organization_id AND q.id = s.queue_entry_id
    WHERE s.organization_id = v_organization_id AND s.id = v_session_id;
    PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_interruption_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_location_operational_revision_from_child(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_location_operational_revision_from_child() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_org uuid;
    v_location uuid;
BEGIN
    IF TG_OP = 'UPDATE' AND (
        OLD.organization_id <> NEW.organization_id OR OLD.location_id <> NEW.location_id
    ) THEN
        RAISE EXCEPTION '% rows cannot move between Locations', TG_TABLE_NAME USING ERRCODE = '23514';
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
     WHERE organization_id = v_org AND id = v_location;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Location % not found while changing operational availability', v_location
            USING ERRCODE = '23503';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$;


ALTER FUNCTION request_engine.bump_location_operational_revision_from_child() OWNER TO request_engine_schema_owner;

--
-- Name: bump_location_revision_recovery_sources(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_location_revision_recovery_sources() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_queue_id uuid;
BEGIN
    IF NEW.operational_revision IS NOT DISTINCT FROM OLD.operational_revision THEN
        RETURN NEW;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = NEW.organization_id
          AND location_id = NEW.id
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(
            NEW.organization_id,
            v_queue_id
        );
    END LOOP;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_location_revision_recovery_sources() OWNER TO request_engine_schema_owner;

--
-- Name: bump_principal_authority_from_grant(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_principal_authority_from_grant() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            UPDATE request_engine.principals
               SET authority_revision = authority_revision + 1
             WHERE id = NEW.principal_id;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.bump_principal_authority_from_grant() OWNER TO request_engine_schema_owner;

--
-- Name: bump_principal_authority_from_identity_binding(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_principal_authority_from_identity_binding() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'INSERT' AND NEW.status <> 'active' THEN
                RETURN NEW;
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.status = OLD.status THEN
                RETURN NEW;
            END IF;
            UPDATE request_engine.principals
               SET authority_revision = authority_revision + 1
             WHERE id = NEW.principal_id;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.bump_principal_authority_from_identity_binding() OWNER TO request_engine_schema_owner;

--
-- Name: bump_principal_authority_from_representation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_principal_authority_from_representation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                UPDATE request_engine.principals
                   SET authority_revision = authority_revision + 1
                 WHERE organization_id = OLD.organization_id
                   AND id = OLD.principal_id;
                RETURN OLD;
            END IF;

            IF TG_OP = 'UPDATE'
               AND (
                   NEW.organization_id IS DISTINCT FROM OLD.organization_id
                   OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
               )
            THEN
                UPDATE request_engine.principals
                   SET authority_revision = authority_revision + 1
                 WHERE organization_id = OLD.organization_id
                   AND id = OLD.principal_id;
            END IF;

            UPDATE request_engine.principals
               SET authority_revision = authority_revision + 1
             WHERE organization_id = NEW.organization_id
               AND id = NEW.principal_id;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.bump_principal_authority_from_representation() OWNER TO request_engine_schema_owner;

--
-- Name: bump_recovery_source_revision(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_revision bigint;
    v_context text := COALESCE(
        current_setting('request_engine.organization_id', true),
        ''
    );
BEGIN
    IF p_service_queue_id IS NULL THEN
        RETURN;
    END IF;

    IF v_context <> '' AND v_context <> p_organization_id::text THEN
        RAISE EXCEPTION
            'bump_recovery_source_revision rejects foreign tenant authority'
            USING ERRCODE = '23514';
    END IF;

    INSERT INTO request_engine.recovery_source_revisions (
        organization_id, service_queue_id, revision, updated_at
    ) VALUES (
        p_organization_id, p_service_queue_id, 1, clock_timestamp()
    )
    ON CONFLICT (organization_id, service_queue_id)
    DO UPDATE SET
        revision = request_engine.recovery_source_revisions.revision + 1,
        updated_at = clock_timestamp()
    RETURNING revision INTO v_revision;

    PERFORM request_cmd.schedule_recovery_reassessment(
        p_organization_id,
        p_service_queue_id,
        v_revision
    );
END
$$;


ALTER FUNCTION request_engine.bump_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: bump_reservation_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_reservation_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_location_id uuid;
    v_reservation_id uuid;
    v_queue_id uuid;
    v_scope integer;
    v_scopes integer := 1;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_location_id := OLD.location_id;
        v_reservation_id := OLD.id;
    ELSE
        IF TG_OP = 'UPDATE'
           AND (NEW.location_id, NEW.during, NEW.status)
               IS NOT DISTINCT FROM
               (OLD.location_id, OLD.during, OLD.status) THEN
            RETURN NEW;
        END IF;
        IF TG_OP = 'UPDATE'
           AND (OLD.organization_id, OLD.location_id)
               IS DISTINCT FROM
               (NEW.organization_id, NEW.location_id) THEN
            v_scopes := 2;
        END IF;
        v_organization_id := NEW.organization_id;
        v_location_id := NEW.location_id;
        v_reservation_id := NEW.id;
    END IF;

    FOR v_scope IN 1..v_scopes LOOP
        IF v_scope = 2 THEN
            v_organization_id := OLD.organization_id;
            v_location_id := OLD.location_id;
        END IF;
        FOR v_queue_id IN
            SELECT DISTINCT p.service_queue_id
            FROM request_engine.live_capacity_projection_policies p
            JOIN request_engine.capacity_claims c
              ON c.organization_id = p.organization_id
             AND c.resource_id = p.resource_id
            WHERE p.organization_id = v_organization_id
              AND p.location_id = v_location_id
              AND c.reservation_id = v_reservation_id
              AND c.status = 'active'
        LOOP
            PERFORM request_engine.bump_recovery_source_revision(
                v_organization_id, v_queue_id
            );
        END LOOP;
    END LOOP;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_reservation_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_resource_activity_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_resource_activity_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_resource_id uuid;
    v_location_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_resource_id := OLD.resource_id;
        v_location_id := OLD.location_id;
    ELSE
        v_organization_id := NEW.organization_id;
        v_resource_id := NEW.resource_id;
        v_location_id := NEW.location_id;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = v_organization_id
          AND resource_id = v_resource_id
          AND (v_location_id IS NULL OR location_id = v_location_id)
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_resource_activity_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_resource_availability_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_resource_availability_revision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.bump_resource_availability_revision() OWNER TO request_engine_schema_owner;

--
-- Name: bump_resource_from_assignment(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_resource_from_assignment() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
     WHERE organization_id = v_org AND id = v_resource;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % not found while changing contextual assignment', v_resource
            USING ERRCODE = '23503';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$;


ALTER FUNCTION request_engine.bump_resource_from_assignment() OWNER TO request_engine_schema_owner;

--
-- Name: bump_resource_from_assignment_child(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_resource_from_assignment_child() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
    SELECT resource_id INTO v_resource
      FROM request_engine.resource_location_assignments
     WHERE organization_id = v_org AND id = v_assignment;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ResourceLocationAssignment % not found while changing availability', v_assignment
            USING ERRCODE = '23503';
    END IF;
    UPDATE request_engine.resources
       SET availability_revision = availability_revision + 1,
           updated_at = clock_timestamp()
     WHERE organization_id = v_org AND id = v_resource;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource % not found while changing contextual availability', v_resource
            USING ERRCODE = '23503';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$;


ALTER FUNCTION request_engine.bump_resource_from_assignment_child() OWNER TO request_engine_schema_owner;

--
-- Name: bump_resource_revision_recovery_sources(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_resource_revision_recovery_sources() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_queue_id uuid;
BEGIN
    IF NEW.availability_revision IS NOT DISTINCT FROM OLD.availability_revision THEN
        RETURN NEW;
    END IF;
    FOR v_queue_id IN
        SELECT service_queue_id
        FROM request_engine.live_capacity_projection_policies
        WHERE organization_id = NEW.organization_id
          AND resource_id = NEW.id
    LOOP
        PERFORM request_engine.bump_recovery_source_revision(
            NEW.organization_id,
            v_queue_id
        );
    END LOOP;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_resource_revision_recovery_sources() OWNER TO request_engine_schema_owner;

--
-- Name: bump_service_session_recovery_source_revision(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bump_service_session_recovery_source_revision() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
    v_queue_entry_id uuid;
    v_queue_id uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_organization_id := OLD.organization_id;
        v_queue_entry_id := OLD.queue_entry_id;
    ELSE
        v_organization_id := NEW.organization_id;
        v_queue_entry_id := NEW.queue_entry_id;
    END IF;
    SELECT service_queue_id INTO v_queue_id
    FROM request_engine.queue_entries
    WHERE organization_id = v_organization_id AND id = v_queue_entry_id;
    PERFORM request_engine.bump_recovery_source_revision(v_organization_id, v_queue_id);
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.bump_service_session_recovery_source_revision() OWNER TO request_engine_schema_owner;

--
-- Name: check_capacity_owner_completeness(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.check_capacity_owner_completeness() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
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
$$;


ALTER FUNCTION request_engine.check_capacity_owner_completeness() OWNER TO request_engine_schema_owner;

--
-- Name: check_offered_slot_offer_source_consistency(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.check_offered_slot_offer_source_consistency() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_offer_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'slot_offers' THEN
        PERFORM request_engine.assert_offered_slot_offer_source_consistency(
            NEW.organization_id,
            NEW.id
        );
    ELSIF TG_TABLE_NAME = 'capacity_holds' THEN
        FOR v_offer_id IN
            SELECT so.id
              FROM request_engine.slot_offers so
             WHERE so.organization_id = NEW.organization_id
               AND so.capacity_hold_id = NEW.id
               AND so.status = 'offered'
        LOOP
            PERFORM request_engine.assert_offered_slot_offer_source_consistency(
                NEW.organization_id,
                v_offer_id
            );
        END LOOP;
    ELSIF TG_TABLE_NAME = 'waitlist_entries' THEN
        FOR v_offer_id IN
            SELECT so.id
              FROM request_engine.slot_offers so
             WHERE so.organization_id = NEW.organization_id
               AND so.waitlist_entry_id = NEW.id
               AND so.status = 'offered'
        LOOP
            PERFORM request_engine.assert_offered_slot_offer_source_consistency(
                NEW.organization_id,
                v_offer_id
            );
        END LOOP;
    ELSIF TG_TABLE_NAME = 'slot_opportunities' THEN
        FOR v_offer_id IN
            SELECT so.id
              FROM request_engine.slot_offers so
             WHERE so.organization_id = NEW.organization_id
               AND so.slot_opportunity_id = NEW.id
               AND so.status = 'offered'
        LOOP
            PERFORM request_engine.assert_offered_slot_offer_source_consistency(
                NEW.organization_id,
                v_offer_id
            );
        END LOOP;
    END IF;

    RETURN NULL;
END
$$;


ALTER FUNCTION request_engine.check_offered_slot_offer_source_consistency() OWNER TO request_engine_schema_owner;

--
-- Name: confirm_identity_link_intent(uuid, bigint, uuid, uuid, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.confirm_identity_link_intent(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_native_identity_id uuid, p_binding_id uuid, p_provenance_reference text) RETURNS TABLE(binding_id uuid, principal_id uuid, binding_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_intent request_engine.identity_link_intents%ROWTYPE;
            v_binding request_engine.identity_bindings%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_binding_id IS NULL THEN
                RAISE EXCEPTION 'Identity link confirmation identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_expected_actor_binding_revision IS NULL
               OR p_expected_actor_binding_revision < 1 THEN
                RAISE EXCEPTION 'A positive actor binding revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link confirmation provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_intent
              FROM request_engine.identity_link_intents
             WHERE id = p_intent_id
               AND organization_id = v_org_id
               AND actor_principal_id = v_actor_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity link intent not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_intent.status <> 'pending' THEN
                RAISE EXCEPTION 'Identity link intent is no longer pending'
                    USING ERRCODE = '55000';
            END IF;
            IF v_intent.expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Identity link intent has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF p_expected_actor_binding_revision <> v_intent.actor_binding_revision THEN
                RAISE EXCEPTION 'Identity link intent actor binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT * INTO v_binding
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_intent.actor_binding_id
               AND binding.organization_id = v_org_id
               AND binding.principal_id = v_actor_id
               AND binding.principal_plane = 'tenant'
               AND binding.status = 'active'
             FOR UPDATE;
            IF NOT FOUND OR v_binding.revision <> v_intent.actor_binding_revision THEN
                RAISE EXCEPTION 'Actor identity binding is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF NOT request_auth.lock_credentialed_native_identity(
                v_intent.target_authority_id, p_native_identity_id
            ) THEN
                RAISE EXCEPTION 'Native identity proof is no longer valid'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS existing
                 WHERE existing.identity_authority_id = v_intent.target_authority_id
                   AND existing.subject_id = p_native_identity_id::text
                   AND existing.organization_id = v_org_id
                   AND existing.status <> 'revoked'
            ) THEN
                RAISE EXCEPTION 'Native identity is already linked in this tenant'
                    USING ERRCODE = '23505';
            END IF;

            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                p_binding_id, v_org_id, v_actor_id, 'tenant',
                v_intent.target_authority_id, p_native_identity_id::text, 'active'
            );

            UPDATE request_engine.identity_link_intents
               SET status = 'consumed',
                   consumed_at = clock_timestamp(),
                   resulting_binding_id = p_binding_id
             WHERE id = p_intent_id;

            INSERT INTO request_engine.identity_link_facts (
                actor_principal_id, organization_id, capability_key, action,
                intent_id, target_authority_id, subject_id, binding_id,
                nonce_digest, provenance_reference
            ) VALUES (
                v_actor_id, v_org_id, 'identity.link_self', 'linked',
                p_intent_id, v_intent.target_authority_id,
                p_native_identity_id::text, p_binding_id, v_intent.nonce_digest,
                btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_binding_id, v_actor_id, 1::bigint;
        END
        $$;


ALTER FUNCTION request_engine.confirm_identity_link_intent(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_native_identity_id uuid, p_binding_id uuid, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: confirm_identity_link_subject(uuid, bigint, text, uuid, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.confirm_identity_link_subject(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_subject_id text, p_binding_id uuid, p_provenance_reference text) RETURNS TABLE(binding_id uuid, principal_id uuid, binding_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_intent request_engine.identity_link_intents%ROWTYPE;
            v_authority request_engine.identity_authorities%ROWTYPE;
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_subject_id text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL OR p_binding_id IS NULL THEN
                RAISE EXCEPTION 'Identity link confirmation identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_expected_actor_binding_revision IS NULL
               OR p_expected_actor_binding_revision < 1 THEN
                RAISE EXCEPTION 'A positive actor binding revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_subject_id IS NULL
               OR length(btrim(p_subject_id)) NOT BETWEEN 1 AND 320 THEN
                RAISE EXCEPTION 'Identity link subject is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link confirmation provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            v_subject_id := btrim(p_subject_id);

            SELECT * INTO v_intent
              FROM request_engine.identity_link_intents
             WHERE id = p_intent_id
               AND organization_id = v_org_id
               AND actor_principal_id = v_actor_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity link intent not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_intent.status <> 'pending' THEN
                RAISE EXCEPTION 'Identity link intent is no longer pending'
                    USING ERRCODE = '55000';
            END IF;
            IF v_intent.expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Identity link intent has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF p_expected_actor_binding_revision <> v_intent.actor_binding_revision THEN
                RAISE EXCEPTION 'Identity link intent actor binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT * INTO v_binding
              FROM request_engine.identity_bindings AS binding
             WHERE binding.id = v_intent.actor_binding_id
               AND binding.organization_id = v_org_id
               AND binding.principal_id = v_actor_id
               AND binding.principal_plane = 'tenant'
               AND binding.status = 'active'
             FOR UPDATE;
            IF NOT FOUND OR v_binding.revision <> v_intent.actor_binding_revision THEN
                RAISE EXCEPTION 'Actor identity binding is stale'
                    USING ERRCODE = '40001';
            END IF;

            SELECT * INTO v_authority
              FROM request_engine.identity_authorities
             WHERE id = v_intent.target_authority_id
             FOR SHARE;
            IF NOT FOUND OR v_authority.status <> 'active' THEN
                RAISE EXCEPTION 'Target identity authority is not active'
                    USING ERRCODE = '23514';
            END IF;
            IF v_authority.kind = 'native' THEN
                RAISE EXCEPTION 'Native identity linking uses the native confirmation path'
                    USING ERRCODE = '55000';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS existing
                 WHERE existing.identity_authority_id = v_intent.target_authority_id
                   AND existing.subject_id = v_subject_id
                   AND existing.organization_id = v_org_id
                   AND existing.status <> 'revoked'
            ) THEN
                RAISE EXCEPTION 'Identity subject is already linked in this tenant'
                    USING ERRCODE = '23505';
            END IF;

            INSERT INTO request_engine.identity_bindings (
                id, organization_id, principal_id, principal_plane,
                identity_authority_id, subject_id, status
            ) VALUES (
                p_binding_id, v_org_id, v_actor_id, 'tenant',
                v_intent.target_authority_id, v_subject_id, 'active'
            );

            UPDATE request_engine.identity_link_intents
               SET status = 'consumed',
                   consumed_at = clock_timestamp(),
                   resulting_binding_id = p_binding_id
             WHERE id = p_intent_id;

            INSERT INTO request_engine.identity_link_facts (
                actor_principal_id, organization_id, capability_key, action,
                intent_id, target_authority_id, subject_id, binding_id,
                nonce_digest, provenance_reference
            ) VALUES (
                v_actor_id, v_org_id, 'identity.link_self', 'linked',
                p_intent_id, v_intent.target_authority_id, v_subject_id,
                p_binding_id, v_intent.nonce_digest, btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_binding_id, v_actor_id, 1::bigint;
        END
        $$;


ALTER FUNCTION request_engine.confirm_identity_link_subject(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_subject_id text, p_binding_id uuid, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: consume_identity_exchange_candidate_v1(uuid, text, text, text, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) RETURNS TABLE(profile jsonb)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_identity uuid;
    v_party_kind text;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id THEN
        RAISE EXCEPTION 'identity adoption actor context mismatch' USING ERRCODE = '42501';
    END IF;
    SELECT c.portable_party_id, p.party_kind INTO v_identity, v_party_kind
    FROM request_engine.identity_exchange_candidates c
    JOIN request_engine.portable_party_identities p ON p.id = c.portable_party_id AND p.active
    WHERE c.id = p_candidate_id AND c.organization_id = v_org
      AND c.created_by_principal_id = p_principal_id AND c.kind = p_kind
      AND c.authority = p_authority AND c.fingerprint = p_fingerprint
      AND c.consumed_at IS NULL AND c.expires_at > clock_timestamp()
    FOR UPDATE OF c;
    IF v_identity IS NULL THEN RETURN; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(v_org::text || ':' || v_identity::text, 0));
    IF NOT EXISTS (SELECT 1 FROM request_engine.identity_exchange_candidates c
                   WHERE c.id = p_candidate_id AND c.organization_id = v_org
                     AND c.created_by_principal_id = p_principal_id
                     AND c.consumed_at IS NULL AND c.expires_at > clock_timestamp()) THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM request_engine.organization_party_bindings b
               WHERE b.organization_id = v_org AND b.portable_party_id = v_identity AND b.active) THEN
        RAISE EXCEPTION 'portable identity already adopted by organization'
            USING ERRCODE = '23505', CONSTRAINT = 'organization_party_binding_identity_uq';
    END IF;
    UPDATE request_engine.identity_exchange_candidates SET consumed_at = clock_timestamp()
    WHERE id = p_candidate_id AND organization_id = v_org;
    RETURN QUERY SELECT jsonb_build_object(
        'contact_points', coalesce((
            SELECT jsonb_agg(DISTINCT item.value)
            FROM request_engine.portable_party_profiles pp
            CROSS JOIN LATERAL jsonb_array_elements(
                coalesce(pp.profile->'contact_points', '[]'::jsonb)) item(value)
            WHERE pp.portable_party_id = v_identity AND pp.active
        ), '[]'::jsonb),
        'insurance_identifiers', CASE WHEN v_party_kind = 'person' THEN coalesce((
            SELECT jsonb_agg(DISTINCT item.value)
            FROM request_engine.portable_party_profiles pp
            CROSS JOIN LATERAL jsonb_array_elements(
                coalesce(pp.profile->'insurance_identifiers', '[]'::jsonb)) item(value)
            WHERE pp.portable_party_id = v_identity AND pp.active
        ), '[]'::jsonb) ELSE '[]'::jsonb END
    );
END
$$;


ALTER FUNCTION request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: create_delegation(uuid, uuid, uuid, text, text[], timestamp with time zone, timestamp with time zone, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.create_delegation(p_id uuid, p_delegator_principal_id uuid, p_delegate_principal_id uuid, p_purpose text, p_allowed_capabilities text[], p_not_before timestamp with time zone, p_expires_at timestamp with time zone, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_capability text;
            v_plane text;
        BEGIN
            v_actor_id := current_setting(
                'request_engine.authenticated_principal_id', true
            )::uuid;
            IF v_actor_id IS NULL
               OR v_actor_id <> p_delegator_principal_id
               OR p_delegator_principal_id = p_delegate_principal_id
               OR length(btrim(p_purpose)) = 0
               OR length(btrim(p_provenance_reference)) = 0
               OR p_not_before IS NULL
               OR p_expires_at IS NULL
               OR p_expires_at <= p_not_before
               OR cardinality(COALESCE(p_allowed_capabilities, ARRAY[]::text[])) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(p_allowed_capabilities) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(p_allowed_capabilities) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(p_allowed_capabilities) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Invalid delegation input' USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap FROM unnest(p_allowed_capabilities) AS cap
            LOOP
                SELECT authority_plane
                  INTO v_plane
                  FROM request_engine.principal_authority_grants
                 WHERE organization_id = v_org_id
                   AND principal_id = v_actor_id
                   AND capability_key = v_capability
                   AND status = 'active'
                   AND delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane <> 'operational' THEN
                    RAISE EXCEPTION
                        'Delegation exceeds the delegator operational ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            INSERT INTO request_engine.delegations (
                id,
                organization_id,
                delegator_principal_id,
                delegate_principal_id,
                purpose,
                allowed_capabilities,
                not_before,
                expires_at,
                provenance_reference
            ) VALUES (
                p_id,
                v_org_id,
                p_delegator_principal_id,
                p_delegate_principal_id,
                btrim(p_purpose),
                p_allowed_capabilities,
                p_not_before,
                p_expires_at,
                btrim(p_provenance_reference)
            );
            RETURN 1;
        END
        $$;


ALTER FUNCTION request_engine.create_delegation(p_id uuid, p_delegator_principal_id uuid, p_delegate_principal_id uuid, p_purpose text, p_allowed_capabilities text[], p_not_before timestamp with time zone, p_expires_at timestamp with time zone, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: create_identity_exchange_candidate_v1(text, text, text, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) RETURNS TABLE(candidate_ref uuid, candidate_expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
DECLARE
    v_org uuid;
    v_actor uuid;
    v_party_kind text;
    v_identity uuid;
BEGIN
    v_org := nullif(current_setting('request_engine.organization_id', true), '')::uuid;
    v_actor := nullif(current_setting('request_engine.authenticated_principal_id', true), '')::uuid;
    v_party_kind := request_engine.identity_exchange_subject_kind_v1(p_kind);
    IF v_org IS NULL OR v_actor IS NULL OR v_actor <> p_principal_id
       OR v_party_kind IS NULL
       OR NOT request_engine.identity_exchange_identifier_valid_v1(p_kind, p_authority)
       OR p_fingerprint !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid identity match context' USING ERRCODE = '42501';
    END IF;
    SELECT i.portable_party_id INTO v_identity
    FROM request_engine.portable_party_identifiers i
    JOIN request_engine.portable_party_identities p ON p.id = i.portable_party_id AND p.active
    WHERE i.party_kind = v_party_kind AND i.kind = p_kind AND i.authority = p_authority
      AND i.fingerprint = p_fingerprint AND i.active
      AND EXISTS (SELECT 1 FROM request_engine.portable_party_profiles pr
                  WHERE pr.portable_party_id = i.portable_party_id AND pr.active)
      AND NOT EXISTS (SELECT 1 FROM request_engine.organization_party_bindings b
                      WHERE b.organization_id = v_org
                        AND b.portable_party_id = i.portable_party_id AND b.active);
    IF v_identity IS NULL THEN
        RETURN QUERY SELECT NULL::uuid, NULL::timestamptz;
        RETURN;
    END IF;
    RETURN QUERY INSERT INTO request_engine.identity_exchange_candidates(
        organization_id, portable_party_id, kind, authority, fingerprint, created_by_principal_id)
    VALUES (v_org, v_identity, p_kind, p_authority, p_fingerprint, p_principal_id)
    RETURNING id, expires_at;
END
$_$;


ALTER FUNCTION request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: create_identity_link_intent(uuid, uuid, uuid, text, integer, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.create_identity_link_intent(p_intent_id uuid, p_actor_binding_id uuid, p_target_authority_id uuid, p_nonce_digest text, p_ttl_seconds integer, p_provenance_reference text) RETURNS TABLE(intent_id uuid, expires_at timestamp with time zone, target_authority_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_expires_at timestamptz;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.link_self');

            IF p_intent_id IS NULL
               OR p_actor_binding_id IS NULL
               OR p_target_authority_id IS NULL THEN
                RAISE EXCEPTION 'Identity link intent identifiers are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_ttl_seconds IS NULL OR p_ttl_seconds < 60 OR p_ttl_seconds > 900 THEN
                RAISE EXCEPTION 'Identity link intent TTL must be between 60 and 900 seconds'
                    USING ERRCODE = '22023';
            END IF;
            IF p_nonce_digest IS NULL OR p_nonce_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity link intent nonce digest is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 400 THEN
                RAISE EXCEPTION 'Identity link intent provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_binding
              FROM request_engine.identity_bindings
             WHERE id = p_actor_binding_id
               AND organization_id = v_org_id
               AND principal_id = v_actor_id
               AND principal_plane = 'tenant'
               AND status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active actor identity binding not found'
                    USING ERRCODE = 'P0002';
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities
             WHERE id = p_target_authority_id
               AND status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Target identity authority is not active'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.identity_link_intents AS intent
               SET status = 'expired'
             WHERE intent.organization_id = v_org_id
               AND intent.actor_principal_id = v_actor_id
               AND intent.status = 'pending'
               AND intent.expires_at <= clock_timestamp();

            IF EXISTS (
                SELECT 1
                  FROM request_engine.identity_link_intents AS intent
                 WHERE intent.actor_principal_id = v_actor_id
                   AND intent.target_authority_id = p_target_authority_id
                   AND intent.status = 'pending'
                   AND intent.expires_at > clock_timestamp()
            ) THEN
                RAISE EXCEPTION 'A live Identity link intent already exists for this authority'
                    USING ERRCODE = '23505';
            END IF;

            v_expires_at := clock_timestamp()
                + make_interval(secs => p_ttl_seconds);
            INSERT INTO request_engine.identity_link_intents (
                id, organization_id, actor_principal_id, actor_binding_id,
                target_authority_id, actor_binding_revision, nonce_digest,
                status, expires_at, provenance_reference
            ) VALUES (
                p_intent_id, v_org_id, v_actor_id, p_actor_binding_id,
                p_target_authority_id, v_binding.revision, p_nonce_digest,
                'pending', v_expires_at, btrim(p_provenance_reference)
            );

            INSERT INTO request_engine.identity_link_facts (
                actor_principal_id, organization_id, capability_key, action,
                intent_id, target_authority_id, nonce_digest,
                provenance_reference
            ) VALUES (
                v_actor_id, v_org_id, 'identity.link_self', 'intent_created',
                p_intent_id, p_target_authority_id, p_nonce_digest,
                btrim(p_provenance_reference)
            );

            RETURN QUERY SELECT p_intent_id, v_expires_at, p_target_authority_id;
        END
        $_$;


ALTER FUNCTION request_engine.create_identity_link_intent(p_intent_id uuid, p_actor_binding_id uuid, p_target_authority_id uuid, p_nonce_digest text, p_ttl_seconds integer, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: current_authenticated_principal_id(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.current_authenticated_principal_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$
    SELECT NULLIF(current_setting('request_engine.authenticated_principal_id', true), '')::uuid
$$;


ALTER FUNCTION request_engine.current_authenticated_principal_id() OWNER TO request_engine_schema_owner;

--
-- Name: current_correlation_id(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.current_correlation_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$
    SELECT NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
$$;


ALTER FUNCTION request_engine.current_correlation_id() OWNER TO request_engine_schema_owner;

--
-- Name: current_organization_id(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.current_organization_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$
    SELECT NULLIF(current_setting('request_engine.organization_id', true), '')::uuid
$$;


ALTER FUNCTION request_engine.current_organization_id() OWNER TO request_engine_schema_owner;

--
-- Name: derive_authentication_assurance(text[], boolean, boolean); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.derive_authentication_assurance(p_methods text[], p_user_verified boolean, p_recovery_derived boolean) RETURNS text
    LANGUAGE sql IMMUTABLE
    SET search_path TO 'pg_catalog'
    AS $$
            SELECT CASE
                WHEN p_methods IS NULL OR cardinality(p_methods) = 0 THEN NULL
                WHEN p_recovery_derived OR 'recovery_code' = ANY(p_methods)
                    THEN 'recovery'
                WHEN 'webauthn' = ANY(p_methods) AND p_user_verified
                    THEN 'phishing_resistant'
                WHEN cardinality(p_methods)
                     - (CASE WHEN 'recovery_code' = ANY(p_methods) THEN 1 ELSE 0 END) >= 2
                    THEN 'mfa'
                ELSE 'single_factor'
            END
        $$;


ALTER FUNCTION request_engine.derive_authentication_assurance(p_methods text[], p_user_verified boolean, p_recovery_derived boolean) OWNER TO request_engine_schema_owner;

--
-- Name: guard_agent_profile(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_agent_profile() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_principal record;
            v_sponsor record;
            v_workload_kind text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Agent profiles are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.principal_id,
                    NEW.organization_id,
                    NEW.display_name,
                    NEW.purpose,
                    NEW.sponsor_principal_id,
                    NEW.operating_mode,
                    NEW.workload_identity_id,
                    NEW.established_by_principal_id,
                    NEW.provenance_kind,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.principal_id,
                    OLD.organization_id,
                    OLD.display_name,
                    OLD.purpose,
                    OLD.sponsor_principal_id,
                    OLD.operating_mode,
                    OLD.workload_identity_id,
                    OLD.established_by_principal_id,
                    OLD.provenance_kind,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Agent profile identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status = NEW.status THEN
                    RAISE EXCEPTION 'Invalid Agent profile update'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       (OLD.status = 'pending'
                           AND NEW.status IN ('active', 'revoked'))
                       OR (OLD.status = 'active'
                           AND NEW.status IN ('suspended', 'revoked'))
                       OR (OLD.status = 'suspended'
                           AND NEW.status IN ('active', 'revoked'))
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Agent profile state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT principal_plane, principal_kind, organization_id, active
              INTO v_principal
              FROM request_engine.principals
             WHERE id = NEW.principal_id;
            IF NOT FOUND
               OR v_principal.principal_plane <> 'tenant'
               OR v_principal.principal_kind <> 'agent'
               OR v_principal.organization_id IS DISTINCT FROM NEW.organization_id
            THEN
                RAISE EXCEPTION 'Agent profile requires a tenant AGENT Principal'
                    USING ERRCODE = '23514';
            END IF;
            IF (
                NEW.status = 'active' AND NOT v_principal.active
            ) OR (
                NEW.status IN ('suspended', 'revoked') AND v_principal.active
            ) THEN
                RAISE EXCEPTION 'Agent profile status contradicts Principal state'
                    USING ERRCODE = '23514';
            END IF;

            SELECT principal_plane, principal_kind, organization_id, active
              INTO v_sponsor
              FROM request_engine.principals
             WHERE id = NEW.sponsor_principal_id;
            IF NOT FOUND
               OR v_sponsor.principal_plane <> 'tenant'
               OR v_sponsor.principal_kind <> 'human'
               OR v_sponsor.organization_id IS DISTINCT FROM NEW.organization_id
               OR NOT v_sponsor.active
               OR NEW.sponsor_principal_id = NEW.principal_id
            THEN
                RAISE EXCEPTION 'Agent sponsor must be an active tenant HUMAN Principal'
                    USING ERRCODE = '23514';
            END IF;

            SELECT workload_kind
              INTO v_workload_kind
              FROM request_engine.workload_identities
             WHERE id = NEW.workload_identity_id;
            IF NOT FOUND OR v_workload_kind <> 'agent' THEN
                RAISE EXCEPTION 'Agent profile requires an agent workload identity'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_agent_profile() OWNER TO request_engine_schema_owner;

--
-- Name: guard_authority_reference_tenant(); Type: FUNCTION; Schema: request_engine; Owner: request_platform_control_definer
--

CREATE FUNCTION request_engine.guard_authority_reference_tenant() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_ids uuid[];
            v_actor_id uuid;
            v_actor_org uuid;
            v_platform_only boolean := false;
        BEGIN
            CASE TG_TABLE_NAME
                WHEN 'organization_provisioning_facts',
                     'organization_root_provisioning_facts' THEN
                    v_actor_ids := ARRAY[NEW.provisioned_by_principal_id];
                    v_platform_only := true;
                WHEN 'staff_memberships' THEN
                    v_actor_ids := ARRAY[NEW.established_by_principal_id];
                    v_platform_only := NEW.provenance_kind = 'root_provisioning';
                WHEN 'principal_authority_grants' THEN
                    v_actor_ids := ARRAY[
                        NEW.granted_by_principal_id, NEW.revoked_by_principal_id
                    ];
                ELSE
                    RAISE EXCEPTION 'Unsupported authority reference relation'
                        USING ERRCODE = '23514';
            END CASE;
            FOREACH v_actor_id IN ARRAY v_actor_ids LOOP
                IF v_actor_id IS NULL THEN CONTINUE; END IF;
                SELECT organization_id INTO v_actor_org
                  FROM request_engine.principals WHERE id = v_actor_id;
                IF NOT FOUND
                   OR (v_platform_only AND v_actor_org IS NOT NULL)
                   OR (NOT v_platform_only AND v_actor_org IS NOT NULL
                       AND v_actor_org IS DISTINCT FROM NEW.organization_id)
                THEN
                    RAISE EXCEPTION 'Authority provenance cannot cross tenant boundaries'
                        USING ERRCODE = '23514';
                END IF;
                IF TG_TABLE_NAME = 'staff_memberships'
                   AND NOT v_platform_only AND v_actor_org IS NULL THEN
                    RAISE EXCEPTION 'Staff invitation requires tenant-local provenance'
                        USING ERRCODE = '23514';
                END IF;
            END LOOP;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_authority_reference_tenant() OWNER TO request_platform_control_definer;

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
-- Name: guard_delegation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_delegation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_delegate_kind text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Delegations are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.id,
                    NEW.organization_id,
                    NEW.delegator_principal_id,
                    NEW.delegate_principal_id,
                    NEW.purpose,
                    NEW.allowed_capabilities,
                    NEW.not_before,
                    NEW.expires_at,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.organization_id,
                    OLD.delegator_principal_id,
                    OLD.delegate_principal_id,
                    OLD.purpose,
                    OLD.allowed_capabilities,
                    OLD.not_before,
                    OLD.expires_at,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Delegation identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status = 'active' AND NEW.status = 'revoked' THEN
                    IF NEW.revision <> OLD.revision + 1 THEN
                        RAISE EXCEPTION 'Invalid delegation revocation'
                            USING ERRCODE = '55000';
                    END IF;
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'Invalid delegation state transition'
                    USING ERRCODE = '55000';
            END IF;

            SELECT principal_kind
              INTO v_delegate_kind
              FROM request_engine.principals
             WHERE organization_id = NEW.organization_id
               AND id = NEW.delegate_principal_id;
            IF NOT FOUND OR v_delegate_kind <> 'agent' THEN
                RAISE EXCEPTION 'Delegation delegate must be a tenant AGENT Principal'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_delegation() OWNER TO request_engine_schema_owner;

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
-- Name: guard_identity_binding(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_identity_binding() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_org uuid;
            v_plane text;
            v_principal_active boolean;
            v_authority_active boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Identity bindings are append-preserving' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.organization_id, NEW.principal_id, NEW.principal_plane,
                       NEW.identity_authority_id, NEW.subject_id, NEW.created_at)
                   IS DISTINCT FROM
                   ROW(OLD.organization_id, OLD.principal_id, OLD.principal_plane,
                       OLD.identity_authority_id, OLD.subject_id, OLD.created_at)
                THEN
                    RAISE EXCEPTION 'Identity binding identity and scope are immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.last_seen_at IS NOT NULL
                   AND (NEW.last_seen_at IS NULL OR NEW.last_seen_at < OLD.last_seen_at)
                THEN
                    RAISE EXCEPTION 'Identity binding last_seen_at cannot regress'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status = OLD.status THEN
                    IF NEW.revision <> OLD.revision
                       OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                       OR NEW.last_seen_at IS NOT DISTINCT FROM OLD.last_seen_at
                    THEN
                        RAISE EXCEPTION 'Only monotonic last_seen_at may change'
                            USING ERRCODE = '55000';
                    END IF;
                    RETURN NEW;
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       (OLD.status = 'pending' AND NEW.status IN ('active', 'revoked'))
                       OR (OLD.status = 'active' AND NEW.status IN ('suspended', 'revoked'))
                       OR (OLD.status = 'suspended' AND NEW.status IN ('active', 'revoked'))
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Identity binding state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT organization_id, principal_plane, active
              INTO v_org, v_plane, v_principal_active
              FROM request_engine.principals WHERE id = NEW.principal_id;
            IF NOT FOUND OR NEW.organization_id IS DISTINCT FROM v_org
               OR NEW.principal_plane <> v_plane
            THEN
                RAISE EXCEPTION 'Identity binding scope must match target Principal scope'
                    USING ERRCODE = '23514';
            END IF;
            SELECT status = 'active' INTO v_authority_active
              FROM request_engine.identity_authorities WHERE id = NEW.identity_authority_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity authority does not exist' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IN ('pending', 'active')
               AND (NOT v_principal_active OR NOT v_authority_active)
            THEN
                RAISE EXCEPTION 'Live Identity binding requires active authority and Principal'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_identity_binding() OWNER TO request_engine_schema_owner;

--
-- Name: guard_identity_link_intent(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_identity_link_intent() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Identity link intents are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF ROW(NEW.id, NEW.organization_id, NEW.actor_principal_id,
                   NEW.actor_binding_id, NEW.target_authority_id,
                   NEW.actor_binding_revision, NEW.nonce_digest, NEW.expires_at,
                   NEW.provenance_reference, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.organization_id, OLD.actor_principal_id,
                   OLD.actor_binding_id, OLD.target_authority_id,
                   OLD.actor_binding_revision, OLD.nonce_digest, OLD.expires_at,
                   OLD.provenance_reference, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Identity link intent identity and scope are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'pending' AND NEW.status = 'consumed'
               AND NEW.consumed_at IS NOT NULL
               AND NEW.resulting_binding_id IS NOT NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'pending' AND NEW.status IN ('revoked', 'expired') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Identity link intent mutation'
                USING ERRCODE = '55000';
        END
        $$;


ALTER FUNCTION request_engine.guard_identity_link_intent() OWNER TO request_engine_schema_owner;

--
-- Name: guard_integration_fact(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_integration_fact() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
        BEGIN
            RAISE EXCEPTION 'Integration provenance is immutable and append-preserving'
                USING ERRCODE = '55000';
        END $$;


ALTER FUNCTION request_engine.guard_integration_fact() OWNER TO request_engine_schema_owner;

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
-- Name: guard_native_credential(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_native_credential() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.kind, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.kind, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Native credential identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.verifier IS DISTINCT FROM OLD.verifier THEN
                -- Only a scrypt -> Argon2id upgrade is permitted, and only as an
                -- isolated verifier change.
                IF NOT (OLD.verifier LIKE 'scrypt$%' AND NEW.verifier LIKE '$argon2id$%') THEN
                    RAISE EXCEPTION 'Native credential verifier may only be upgraded'
                        USING ERRCODE = '55000';
                END IF;
                IF ROW(NEW.status, NEW.revision, NEW.rotated_at, NEW.revoked_at,
                       NEW.last_used_at)
                   IS DISTINCT FROM
                   ROW(OLD.status, OLD.revision, OLD.rotated_at, OLD.revoked_at,
                       OLD.last_used_at)
                THEN
                    RAISE EXCEPTION 'Native credential verifier upgrade must be isolated'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.status = OLD.status
               AND NEW.revision = OLD.revision
               AND NEW.rotated_at IS NOT DISTINCT FROM OLD.rotated_at
               AND NEW.revoked_at IS NOT DISTINCT FROM OLD.revoked_at
               AND (OLD.last_used_at IS NULL OR NEW.last_used_at >= OLD.last_used_at)
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'revoked'
               AND NEW.revision = OLD.revision + 1
               AND NEW.revoked_at IS NOT NULL
               AND NEW.last_used_at IS NOT DISTINCT FROM OLD.last_used_at
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native credential mutation' USING ERRCODE = '55000';
        END
        $_$;


ALTER FUNCTION request_engine.guard_native_credential() OWNER TO request_engine_schema_owner;

--
-- Name: guard_native_identity(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_native_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            SELECT kind, status INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = NEW.identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native' THEN
                RAISE EXCEPTION 'Native identity requires a Native identity authority'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF v_authority_status <> 'active' THEN
                    RAISE EXCEPTION 'Native identity authority must be active'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;

            IF ROW(NEW.id, NEW.identity_authority_id, NEW.login_handle, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.identity_authority_id, OLD.login_handle, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Native identity and login handle are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status <> 'active' THEN
                RAISE EXCEPTION 'Disabled Native identity is terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.status = 'disabled' THEN
                IF NEW.revision <> OLD.revision + 1
                   OR NEW.session_epoch <> OLD.session_epoch + 1
                   OR NEW.disabled_at IS NULL
                THEN
                    RAISE EXCEPTION 'Invalid Native identity disable transition'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF NEW.status = 'active'
               AND NEW.revision = OLD.revision + 1
               AND NEW.session_epoch = OLD.session_epoch + 1
               AND NEW.disabled_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native identity mutation' USING ERRCODE = '55000';
        END
        $$;


ALTER FUNCTION request_engine.guard_native_identity() OWNER TO request_engine_schema_owner;

--
-- Name: guard_native_recovery_intent(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_native_recovery_intent() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.native_identity_id, NEW.token_digest, NEW.token_fingerprint,
                   NEW.created_at, NEW.expires_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.native_identity_id, OLD.token_digest, OLD.token_fingerprint,
                   OLD.created_at, OLD.expires_at)
            THEN
                RAISE EXCEPTION 'Native recovery credential material is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'pending'
               AND (
                   (NEW.status = 'consumed' AND NEW.consumed_at IS NOT NULL
                    AND NEW.revoked_at IS NULL)
                   OR
                   (NEW.status = 'revoked' AND NEW.revoked_at IS NOT NULL
                    AND NEW.consumed_at IS NULL)
               )
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid Native recovery mutation' USING ERRCODE = '55000';
        END
        $$;


ALTER FUNCTION request_engine.guard_native_recovery_intent() OWNER TO request_engine_schema_owner;

--
-- Name: guard_native_session(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_native_session() RETURNS trigger
    LANGUAGE plpgsql
