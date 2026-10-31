                USING ERRCODE = '55000';
        END
        $$;


ALTER FUNCTION request_engine.guard_platform_configuration_revision() OWNER TO request_engine_schema_owner;

--
-- Name: guard_platform_instance(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_platform_instance() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Platform instance is not deletable' USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.singleton_key, NEW.id, NEW.created_at,
                       NEW.built_in_native_authority_id, NEW.built_in_workload_authority_id)
                   IS DISTINCT FROM
                   ROW(OLD.singleton_key, OLD.id, OLD.created_at,
                       OLD.built_in_native_authority_id, OLD.built_in_workload_authority_id)
                THEN
                    RAISE EXCEPTION 'Platform instance identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.state = 'claimed' AND NEW.state <> 'claimed' THEN
                    RAISE EXCEPTION 'Platform instance claim is one-way'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.state = OLD.state THEN
                    IF NEW.revision <> OLD.revision
                       OR NEW.claimed_at IS DISTINCT FROM OLD.claimed_at
                       OR NEW.initial_owner_principal_id
                          IS DISTINCT FROM OLD.initial_owner_principal_id
                       OR NEW.claim_provenance IS DISTINCT FROM OLD.claim_provenance
                    THEN
                        RAISE EXCEPTION
                            'Only an unclaimed-to-claimed transition may change Instance state'
                            USING ERRCODE = '55000';
                    END IF;
                    RETURN NEW;
                END IF;
                IF NOT (OLD.state = 'unclaimed' AND NEW.state = 'claimed') THEN
                    RAISE EXCEPTION 'Invalid platform instance state transition'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Platform instance claim must increment revision once'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_platform_instance() OWNER TO request_engine_schema_owner;

--
-- Name: guard_platform_secret_binding(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_platform_secret_binding() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                RETURN NEW;
            END IF;
            IF ROW(NEW.id, NEW.purpose, NEW.backend, NEW.secret_id, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.purpose, OLD.backend, OLD.secret_id, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Platform secret binding identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'active'
               AND NEW.backend_version > OLD.backend_version
               AND NEW.revision = OLD.revision + 1
               AND NEW.rotated_at IS NOT NULL
               AND (OLD.rotated_at IS NULL OR NEW.rotated_at >= OLD.rotated_at)
               AND NEW.revoked_at IS NULL
            THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'active'
               AND NEW.status = 'revoked'
               AND NEW.backend_version = OLD.backend_version
               AND NEW.revision = OLD.revision + 1
               AND NEW.rotated_at IS NOT DISTINCT FROM OLD.rotated_at
               AND NEW.revoked_at IS NOT NULL
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'Invalid platform secret binding transition'
                USING ERRCODE = '55000';
        END
        $$;


ALTER FUNCTION request_engine.guard_platform_secret_binding() OWNER TO request_engine_schema_owner;

--
-- Name: guard_principal_authority_grant(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_principal_authority_grant() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_org uuid;
            v_plane text;
            v_active boolean;
            v_grantor_active boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Principal authority grants are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.organization_id, NEW.principal_id, NEW.principal_plane,
                       NEW.authority_plane, NEW.capability_key, NEW.delegable,
                       NEW.granted_by_principal_id, NEW.provenance_kind,
                       NEW.provenance_reference, NEW.granted_at)
                   IS DISTINCT FROM
                   ROW(OLD.organization_id, OLD.principal_id, OLD.principal_plane,
                       OLD.authority_plane, OLD.capability_key, OLD.delegable,
                       OLD.granted_by_principal_id, OLD.provenance_kind,
                       OLD.provenance_reference, OLD.granted_at)
                   OR OLD.status <> 'active' OR NEW.status <> 'revoked'
                   OR NEW.revision <> OLD.revision + 1
                THEN
                    RAISE EXCEPTION
                        'Principal authority grant may only transition active to revoked'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;

            SELECT organization_id, principal_plane, active
              INTO v_org, v_plane, v_active
              FROM request_engine.principals WHERE id = NEW.principal_id;
            IF NOT FOUND OR NOT v_active THEN
                RAISE EXCEPTION 'Authority target Principal must be active'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.organization_id IS DISTINCT FROM v_org OR NEW.principal_plane <> v_plane THEN
                RAISE EXCEPTION 'Authority grant scope must match target Principal scope'
                    USING ERRCODE = '23514';
            END IF;
            IF (v_plane = 'platform' AND NEW.authority_plane <> 'platform')
               OR (v_plane = 'tenant' AND NEW.authority_plane = 'platform')
            THEN
                RAISE EXCEPTION 'Authority plane is incompatible with target Principal plane'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.granted_by_principal_id IS NOT NULL THEN
                SELECT active INTO v_grantor_active FROM request_engine.principals
                 WHERE id = NEW.granted_by_principal_id;
                IF NOT FOUND OR NOT v_grantor_active THEN
                    RAISE EXCEPTION 'Grantor Principal must be active' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_principal_authority_grant() OWNER TO request_engine_schema_owner;

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
-- Name: guard_principal_security_identity(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_principal_security_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_security_fact_changed boolean;
        BEGIN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.principal_plane IS DISTINCT FROM OLD.principal_plane
            THEN
                RAISE EXCEPTION 'Principal authority plane and tenant cannot be retargeted'
                    USING ERRCODE = '55000';
            END IF;

            v_security_fact_changed :=
                NEW.active IS DISTINCT FROM OLD.active
                OR NEW.principal_kind IS DISTINCT FROM OLD.principal_kind
                OR NEW.external_subject IS DISTINCT FROM OLD.external_subject;

            IF NEW.authority_revision = OLD.authority_revision THEN
                IF v_security_fact_changed THEN
                    NEW.authority_revision := OLD.authority_revision + 1;
                END IF;
            ELSIF NEW.authority_revision <> OLD.authority_revision + 1 THEN
                RAISE EXCEPTION 'Principal authority_revision must advance exactly one step'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_principal_security_identity() OWNER TO request_engine_schema_owner;

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
-- Name: guard_setup_session(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_setup_session() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status = 'pending' THEN
                    RAISE EXCEPTION 'Pending setup sessions cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(NEW.id, NEW.instance_id, NEW.token_digest, NEW.token_fingerprint,
                       NEW.mode, NEW.created_at, NEW.expires_at)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.instance_id, OLD.token_digest, OLD.token_fingerprint,
                       OLD.mode, OLD.created_at, OLD.expires_at)
                THEN
                    RAISE EXCEPTION 'Setup session identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF OLD.status <> 'pending' THEN
                    RAISE EXCEPTION 'Setup session terminal state is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.status NOT IN ('consumed', 'expired', 'revoked') THEN
                    RAISE EXCEPTION 'Invalid setup session state transition'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1 THEN
                    RAISE EXCEPTION 'Setup session revision must increment exactly once'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_setup_session() OWNER TO request_engine_schema_owner;

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
-- Name: guard_staff_invitation(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_staff_invitation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.revision <> 1 OR NEW.generation <> 1 OR NEW.status <> 'pending'
                    OR NEW.invited_by_principal_id IS DISTINCT FROM
                request_cmd.assert_staff_invitation_manager() THEN
                    RAISE EXCEPTION 'Invalid invitation creation' USING ERRCODE = '42501';
                END IF;
            ELSE
                IF OLD.status <> 'pending' OR NEW.revision <> OLD.revision + 1
                    OR (NEW.id,NEW.organization_id,NEW.email,
                        NEW.invited_by_principal_id,NEW.created_at,NEW.provenance_reference)
                        IS DISTINCT FROM
                (OLD.id,OLD.organization_id,OLD.email,
                    OLD.invited_by_principal_id,OLD.created_at,OLD.provenance_reference) THEN
                    RAISE EXCEPTION 'Invalid invitation lifecycle' USING ERRCODE = '23514';
                END IF;
                IF NEW.status = 'accepted' THEN
                    IF current_user <> 'request_engine_schema_owner' THEN
                        RAISE EXCEPTION 'Acceptance requires subject proof' USING ERRCODE = '42501';
                    END IF;
                ELSE
                    PERFORM request_cmd.assert_staff_invitation_manager();
                END IF;
                IF NEW.status = 'pending' THEN
                    IF NEW.generation <> OLD.generation + 1 OR NEW.token_digest =
                OLD.token_digest THEN
                        RAISE EXCEPTION 'Resend must rotate proof' USING ERRCODE = '23514';
                    END IF;
                ELSIF NEW.generation <> OLD.generation OR NEW.token_digest <> OLD.token_digest
                    OR NEW.expires_at <> OLD.expires_at THEN
                    RAISE EXCEPTION 'Terminal transition may not replace proof' USING ERRCODE =
                '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$;


ALTER FUNCTION request_engine.guard_staff_invitation() OWNER TO request_engine_schema_owner;

--
-- Name: guard_staff_invitation_proposal(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_staff_invitation_proposal() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE v_decider uuid;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.revision <> 1 OR NEW.status <> 'pending'
                    OR NEW.proposed_by_principal_id IS DISTINCT FROM
                        request_cmd.assert_staff_invitation_proposer() THEN
                    RAISE EXCEPTION 'Invalid staff invitation proposal' USING ERRCODE = '42501';
                END IF;
                RETURN NEW;
            END IF;
            -- Only a current HUMAN staff.invite manager decides; agents fail here.
            v_decider := request_cmd.assert_staff_invitation_manager();
            IF NEW.decided_by_principal_id IS DISTINCT FROM v_decider THEN
                RAISE EXCEPTION 'Decision must record the current manager'
                    USING ERRCODE = '42501';
            END IF;
            IF OLD.status <> 'pending' OR NEW.status NOT IN ('approved','rejected')
                OR NEW.revision <> OLD.revision + 1
                OR (NEW.id,NEW.organization_id,NEW.email,NEW.display_name,NEW.note,
                    NEW.proposed_by_principal_id,NEW.provenance_reference,NEW.created_at)
                    IS DISTINCT FROM
                   (OLD.id,OLD.organization_id,OLD.email,OLD.display_name,OLD.note,
                    OLD.proposed_by_principal_id,OLD.provenance_reference,OLD.created_at) THEN
                RAISE EXCEPTION 'Invalid staff invitation proposal decision'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.status = 'approved' AND NOT EXISTS(
                SELECT 1 FROM request_engine.staff_invitations AS i
                 WHERE i.id = NEW.invitation_id AND i.organization_id = NEW.organization_id
                   AND i.email = NEW.email AND i.invited_by_principal_id = v_decider
                   AND i.status = 'pending') THEN
                RAISE EXCEPTION 'Approval must link the decider''s pending invitation'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;


ALTER FUNCTION request_engine.guard_staff_invitation_proposal() OWNER TO request_engine_schema_owner;

--
-- Name: guard_staff_membership(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_staff_membership() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_principal_org uuid;
            v_principal_plane text;
            v_principal_kind text;
            v_binding_org uuid;
            v_binding_principal uuid;
            v_anchor_org uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Staff memberships are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF ROW(
                    NEW.id,
                    NEW.organization_id,
                    NEW.principal_id,
                    NEW.identity_binding_id,
                    NEW.authority_anchor_party_id,
                    NEW.established_by_principal_id,
                    NEW.provenance_kind,
                    NEW.provenance_reference,
                    NEW.created_at
                ) IS DISTINCT FROM ROW(
                    OLD.id,
                    OLD.organization_id,
                    OLD.principal_id,
                    OLD.identity_binding_id,
                    OLD.authority_anchor_party_id,
                    OLD.established_by_principal_id,
                    OLD.provenance_kind,
                    OLD.provenance_reference,
                    OLD.created_at
                ) THEN
                    RAISE EXCEPTION 'Staff membership identity is immutable'
                        USING ERRCODE = '55000';
                END IF;
                IF NEW.revision <> OLD.revision + 1
                   OR NOT (
                       (OLD.status = 'invited'
                           AND NEW.status IN ('active', 'revoked'))
                       OR (OLD.status = 'active'
                           AND NEW.status IN ('suspended', 'revoked'))
                       OR (OLD.status = 'suspended'
                           AND NEW.status IN ('active', 'revoked'))
                   )
                THEN
                    RAISE EXCEPTION 'Invalid Staff membership state transition'
                        USING ERRCODE = '55000';
                END IF;
            END IF;

            SELECT organization_id, principal_plane, principal_kind
              INTO v_principal_org, v_principal_plane, v_principal_kind
              FROM request_engine.principals
             WHERE id = NEW.principal_id;
            IF NOT FOUND
               OR v_principal_org IS DISTINCT FROM NEW.organization_id
               OR v_principal_plane <> 'tenant'
               OR v_principal_kind <> 'human'
            THEN
                RAISE EXCEPTION 'Staff membership requires a tenant HUMAN Principal'
                    USING ERRCODE = '23514';
            END IF;

            SELECT organization_id, principal_id
              INTO v_binding_org, v_binding_principal
              FROM request_engine.identity_bindings
             WHERE id = NEW.identity_binding_id;
            IF NOT FOUND
               OR v_binding_org IS DISTINCT FROM NEW.organization_id
               OR v_binding_principal <> NEW.principal_id
            THEN
                RAISE EXCEPTION 'Staff membership binding scope is invalid'
                    USING ERRCODE = '23514';
            END IF;

            SELECT organization_id INTO v_anchor_org
              FROM request_engine.parties
             WHERE id = NEW.authority_anchor_party_id;
            IF NOT FOUND OR v_anchor_org <> NEW.organization_id THEN
                RAISE EXCEPTION 'Staff membership authority anchor is invalid'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_staff_membership() OWNER TO request_engine_schema_owner;

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
-- Name: guard_workload_credential(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_workload_credential() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_identity_active boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Workload credentials are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            SELECT status = 'active'
              INTO v_identity_active
              FROM request_engine.workload_identities
             WHERE id = NEW.workload_identity_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Workload identity does not exist'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'active' AND NOT v_identity_active THEN
                    RAISE EXCEPTION 'Active credential requires active workload identity'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(
                NEW.workload_identity_id,
                NEW.token_digest,
                NEW.token_fingerprint,
                NEW.created_at,
                NEW.expires_at
            ) IS DISTINCT FROM ROW(
                OLD.workload_identity_id,
                OLD.token_digest,
                OLD.token_fingerprint,
                OLD.created_at,
                OLD.expires_at
            ) THEN
                RAISE EXCEPTION 'Workload credential identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = NEW.status THEN
                IF NEW.revision <> OLD.revision
                   OR NEW.revoked_at IS DISTINCT FROM OLD.revoked_at
                   OR (
                       OLD.last_used_at IS NOT NULL
                       AND (NEW.last_used_at IS NULL OR NEW.last_used_at < OLD.last_used_at)
                   )
                THEN
                    RAISE EXCEPTION 'Invalid workload credential update'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status <> 'active' OR NEW.status <> 'revoked'
               OR NEW.revision <> OLD.revision + 1
               OR NEW.revoked_at IS NULL
            THEN
                RAISE EXCEPTION 'Invalid workload credential transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_workload_credential() OWNER TO request_engine_schema_owner;

--
-- Name: guard_workload_identity(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.guard_workload_identity() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Workload identities are append-preserving'
                    USING ERRCODE = '55000';
            END IF;
            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = NEW.identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'workload' THEN
                RAISE EXCEPTION 'Workload identity requires workload authority'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'INSERT' THEN
                IF NEW.status = 'active' AND v_authority_status <> 'active' THEN
                    RAISE EXCEPTION 'Active workload identity requires active authority'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF ROW(NEW.identity_authority_id, NEW.workload_kind, NEW.created_at)
               IS DISTINCT FROM
               ROW(OLD.identity_authority_id, OLD.workload_kind, OLD.created_at)
            THEN
                RAISE EXCEPTION 'Workload identity facts are immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF OLD.status = NEW.status THEN
                IF NEW.revision <> OLD.revision
                   OR NEW.disabled_at IS DISTINCT FROM OLD.disabled_at
                   OR NEW.updated_at < OLD.updated_at
                THEN
                    RAISE EXCEPTION 'Invalid workload identity update'
                        USING ERRCODE = '55000';
                END IF;
                RETURN NEW;
            END IF;
            IF OLD.status <> 'active' OR NEW.status <> 'disabled'
               OR NEW.revision <> OLD.revision + 1
               OR NEW.disabled_at IS NULL
            THEN
                RAISE EXCEPTION 'Invalid workload identity transition'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.guard_workload_identity() OWNER TO request_engine_schema_owner;

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
-- Name: invite_native_staff(uuid, uuid, uuid, uuid, uuid, uuid, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.invite_native_staff(p_membership_id uuid, p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_authority_anchor_party_id uuid, p_provenance_reference text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority_anchor_party_id uuid;
            v_existing record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager('staff.invite');
            IF p_principal_id = v_actor_id
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Invalid staff invitation input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT root_fact.organization_party_id
              INTO v_authority_anchor_party_id
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = v_org_id;
            IF v_authority_anchor_party_id IS NULL THEN
                RAISE EXCEPTION 'Tenant root authority anchor is unavailable'
                    USING ERRCODE = '23514';
            END IF;

            SELECT principal_id, identity_binding_id, authority_anchor_party_id
              INTO v_existing
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id;
            IF FOUND THEN
                IF v_existing.principal_id <> p_principal_id
                   OR v_existing.identity_binding_id <> p_binding_id
                   OR v_existing.authority_anchor_party_id <> v_authority_anchor_party_id
                THEN
                    RAISE EXCEPTION 'Staff invitation replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.identity_binding_id;
            END IF;

            IF NOT request_auth.lock_credentialed_native_identity(
                p_identity_authority_id,
                p_native_identity_id
            ) THEN
                RAISE EXCEPTION 'Staff invitation requires a credentialed Native identity'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.principals (
                id,
                organization_id,
                principal_plane,
                principal_kind,
                external_subject
            ) VALUES (
                p_principal_id,
                v_org_id,
                'tenant',
                'human',
                'native:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id,
                organization_id,
                principal_id,
                principal_plane,
                identity_authority_id,
                subject_id,
                status
            ) VALUES (
                p_binding_id,
                v_org_id,
                p_principal_id,
                'tenant',
                p_identity_authority_id,
                p_native_identity_id::text,
                'pending'
            );
            INSERT INTO request_engine.staff_memberships (
                id,
                organization_id,
                principal_id,
                identity_binding_id,
                authority_anchor_party_id,
                status,
                established_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_membership_id,
                v_org_id,
                p_principal_id,
                p_binding_id,
                v_authority_anchor_party_id,
                'invited',
                v_actor_id,
                'staff_invitation',
                btrim(p_provenance_reference)
            );
            RETURN p_binding_id;
        END
        $$;


ALTER FUNCTION request_engine.invite_native_staff(p_membership_id uuid, p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_authority_anchor_party_id uuid, p_provenance_reference text) OWNER TO request_engine_schema_owner;

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
-- Name: lock_tenant_staff_root(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.lock_tenant_staff_root() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM id
              FROM request_engine.staff_memberships
             WHERE organization_id = request_engine.current_organization_id()
               AND status = 'active'
             ORDER BY principal_id
             FOR UPDATE;
        END
        $$;


ALTER FUNCTION request_engine.lock_tenant_staff_root() OWNER TO request_engine_schema_owner;

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
-- Name: notify_outbox_change(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.notify_outbox_change() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'pg_temp'
    AS $$
DECLARE
    v_organization_id uuid;
BEGIN
    FOR v_organization_id IN
        SELECT DISTINCT organization_id FROM new_outbox_rows
    LOOP
        PERFORM pg_notify(
            'request_engine_changes',
            v_organization_id::text || ':' || pg_current_xact_id()::text
        );
    END LOOP;
    RETURN NULL;
END
$$;


ALTER FUNCTION request_engine.notify_outbox_change() OWNER TO request_engine_schema_owner;

--
-- Name: notify_platform_secret_runtime_change(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.notify_platform_secret_runtime_change() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_config record;
        BEGIN
            IF ROW(NEW.backend_version, NEW.revision, NEW.status)
               IS NOT DISTINCT FROM
               ROW(OLD.backend_version, OLD.revision, OLD.status)
            THEN
                RETURN NEW;
            END IF;

            FOR v_config IN
                SELECT configuration_kind, revision
                  FROM request_engine.platform_configuration_revisions
                 WHERE secret_binding_id = NEW.id
                   AND state = 'active'
            LOOP
                PERFORM pg_catalog.pg_notify(
                    'request_engine_platform_configuration',
                    jsonb_build_object(
                        'configuration_kind', v_config.configuration_kind,
                        'revision', v_config.revision,
                        'secret_binding_revision', NEW.revision,
                        'secret_backend_version', NEW.backend_version,
                        'secret_status', NEW.status
                    )::text
                );
            END LOOP;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.notify_platform_secret_runtime_change() OWNER TO request_engine_schema_owner;

--
-- Name: principal_is_effective_tenant_controller(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.principal_is_effective_tenant_controller(p_organization_id uuid, p_principal_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_binding record;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            PERFORM 1
              FROM request_engine.principals AS principal
             WHERE principal.id = p_principal_id
               AND principal.principal_plane = 'tenant'
               AND principal.active;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.principal_id = p_principal_id
               AND membership.status = 'active';
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF (
                SELECT count(DISTINCT grant_row.capability_key)
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.organization_id = p_organization_id
                   AND grant_row.principal_id = p_principal_id
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key IN (
                       'staff.manage_membership',
                       'staff.manage_authority',
                       'identity.bind'
                   )
            ) <> 3 THEN
                RETURN false;
            END IF;

            FOR v_binding IN
                SELECT binding.identity_authority_id, binding.subject_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.organization_id = p_organization_id
                   AND binding.principal_id = p_principal_id
                   AND binding.principal_plane = 'tenant'
                   AND binding.status = 'active'
                 ORDER BY binding.id
            LOOP
                SELECT authority.kind, authority.status
                  INTO v_authority_kind, v_authority_status
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.id = v_binding.identity_authority_id;
                IF NOT FOUND OR v_authority_status <> 'active' THEN
                    CONTINUE;
                END IF;

                IF v_authority_kind = 'native' THEN
                    PERFORM 1
                      FROM request_engine.native_identities AS identity
                      JOIN request_engine.native_credentials AS credential
                        ON credential.native_identity_id = identity.id
                       AND credential.kind = 'password'
                       AND credential.status = 'active'
                     WHERE identity.identity_authority_id = v_binding.identity_authority_id
                       AND identity.id::text = v_binding.subject_id
                       AND identity.status = 'active';
                    IF FOUND THEN
                        RETURN true;
                    END IF;
                ELSIF v_authority_kind = 'oidc' THEN
                    -- A configured external authenticator counts; upstream network
                    -- reachability and token revocation are not observable here.
                    RETURN true;
                END IF;
            END LOOP;

            RETURN false;
        END
        $$;


ALTER FUNCTION request_engine.principal_is_effective_tenant_controller(p_organization_id uuid, p_principal_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: project_managed_oidc_authority(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.project_managed_oidc_authority() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_issuer text;
            v_jwks_uri text;
            v_audience text;
            v_configuration_ref text;
        BEGIN
            IF NEW.configuration_kind <> 'identity.oidc'
               OR NEW.provider_kind <> 'oidc'
               OR NEW.state = OLD.state
            THEN
                RETURN NEW;
            END IF;

            v_issuer := NEW.configuration ->> 'issuer';
            v_jwks_uri := NEW.configuration ->> 'jwks_uri';
            v_audience := NEW.configuration ->> 'audience';

            IF v_issuer IS NULL OR btrim(v_issuer) = ''
               OR v_jwks_uri IS NULL OR btrim(v_jwks_uri) = ''
               OR v_audience IS NULL OR btrim(v_audience) = ''
               OR NEW.secret_binding_id IS NOT NULL
            THEN
                RAISE EXCEPTION 'Managed OIDC configuration is malformed'
                    USING ERRCODE = '23514';
            END IF;

            v_configuration_ref := jsonb_build_object(
                'jwks_uri', v_jwks_uri,
                'audience', v_audience,
                'managed_configuration_revision', NEW.revision
            )::text;

            IF NEW.state = 'active' THEN
                INSERT INTO request_engine.identity_authorities (
                    kind,
                    issuer_or_environment,
                    status,
                    configuration_ref
                ) VALUES (
                    'oidc',
                    v_issuer,
                    'active',
                    v_configuration_ref
                )
                ON CONFLICT (kind, issuer_or_environment)
                DO UPDATE SET
                    status = 'active',
                    configuration_ref = EXCLUDED.configuration_ref,
                    revision = request_engine.identity_authorities.revision + 1;
            ELSIF OLD.state = 'active' AND NEW.state IN ('superseded', 'disabled') THEN
                UPDATE request_engine.identity_authorities AS authority
                   SET status = 'disabled',
                       revision = authority.revision + 1
                 WHERE authority.kind = 'oidc'
                   AND authority.issuer_or_environment = v_issuer
                   AND authority.status = 'active'
                   AND NOT EXISTS (
                       SELECT 1
                         FROM request_engine.platform_configuration_revisions AS cfg
                        WHERE cfg.configuration_kind = 'identity.oidc'
                          AND cfg.provider_kind = 'oidc'
                          AND cfg.state = 'active'
                          AND cfg.id <> NEW.id
                          AND cfg.configuration ->> 'issuer' = v_issuer
                   );
            END IF;

            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.project_managed_oidc_authority() OWNER TO request_engine_schema_owner;

--
-- Name: provision_agent(uuid, uuid, uuid, uuid, uuid, bytea, text, timestamp with time zone, text, text, uuid, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.provision_agent(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_display_name text, p_purpose text, p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority record;
            v_existing request_engine.agent_profiles%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager('agent.provision');
            IF p_principal_id = v_actor_id
               OR p_sponsor_principal_id = p_principal_id
               OR length(btrim(p_provenance_reference)) = 0
               OR length(btrim(p_display_name)) = 0
               OR length(btrim(p_purpose)) = 0
               OR p_operating_mode NOT IN ('autonomous', 'assisted')
               OR p_credential_expires_at IS NULL
               OR p_credential_expires_at <= clock_timestamp()
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
            THEN
                RAISE EXCEPTION 'Invalid agent provisioning input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_existing
              FROM request_engine.agent_profiles
             WHERE principal_id = p_principal_id;
            IF FOUND THEN
                IF ROW(
                    v_existing.organization_id,
                    v_existing.workload_identity_id,
                    v_existing.display_name,
                    v_existing.purpose,
                    v_existing.sponsor_principal_id,
                    v_existing.operating_mode
                ) IS DISTINCT FROM ROW(
                    v_org_id,
                    p_workload_identity_id,
                    p_display_name,
                    p_purpose,
                    p_sponsor_principal_id,
                    p_operating_mode
                ) THEN
                    RAISE EXCEPTION 'Agent provisioning replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.revision;
            END IF;

            IF EXISTS (
                SELECT 1 FROM request_engine.principals
                 WHERE id = p_principal_id
            ) OR EXISTS (
                SELECT 1 FROM request_engine.workload_identities
                 WHERE id = p_workload_identity_id
            ) OR EXISTS (
                SELECT 1 FROM request_engine.workload_credentials
                 WHERE id = p_credential_id
            ) THEN
                RAISE EXCEPTION 'Agent provisioning identifiers already exist'
                    USING ERRCODE = '23505';
            END IF;

            SELECT kind, status
              INTO v_authority
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
             FOR SHARE;
            IF NOT FOUND
               OR v_authority.kind <> 'workload'
               OR v_authority.status <> 'active'
            THEN
                RAISE EXCEPTION 'Agent provisioning requires an active workload authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.principals (
                id,
                organization_id,
                principal_plane,
                principal_kind,
                external_subject
            ) VALUES (
                p_principal_id,
                v_org_id,
                'tenant',
                'agent',
                'workload:' || p_workload_identity_id::text
            );

            INSERT INTO request_engine.workload_identities (
                id,
                identity_authority_id,
                workload_kind,
                status
            ) VALUES (
                p_workload_identity_id,
                p_identity_authority_id,
                'agent',
                'active'
            );

            INSERT INTO request_engine.workload_credentials (
                id,
                workload_identity_id,
                token_digest,
                token_fingerprint,
                status,
                expires_at
            ) VALUES (
                p_credential_id,
                p_workload_identity_id,
                p_token_digest,
                p_token_fingerprint,
                'active',
                p_credential_expires_at
            );

            INSERT INTO request_engine.identity_bindings (
                id,
                organization_id,
                principal_id,
                principal_plane,
                identity_authority_id,
                subject_id,
                status
            ) VALUES (
                p_binding_id,
                v_org_id,
                p_principal_id,
                'tenant',
                p_identity_authority_id,
                p_workload_identity_id::text,
                'pending'
            );

            INSERT INTO request_engine.agent_profiles (
                principal_id,
                organization_id,
                display_name,
                purpose,
                sponsor_principal_id,
                status,
                operating_mode,
                workload_identity_id,
                established_by_principal_id,
                provenance_kind,
                provenance_reference
            ) VALUES (
                p_principal_id,
                v_org_id,
                btrim(p_display_name),
                btrim(p_purpose),
                p_sponsor_principal_id,
                'pending',
                p_operating_mode,
                p_workload_identity_id,
                v_actor_id,
                'agent_provisioning',
                btrim(p_provenance_reference)
            );
            RETURN 1;
        END
        $_$;


ALTER FUNCTION request_engine.provision_agent(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_display_name text, p_purpose text, p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: provision_integration(uuid, uuid, uuid, uuid, uuid, bytea, text, timestamp with time zone, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.provision_integration(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := 'integration.provision';
            BEGIN
                PERFORM request_engine.acquire_identity_topology_share();
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                
                IF EXISTS (SELECT 1 FROM request_engine.principals WHERE id = p_principal_id)
                THEN
                    RAISE EXCEPTION 'Provisioning identifier already exists'
                        USING ERRCODE = '23505';
                END IF;
            
                IF 'provision' <> 'provision' THEN
                    SELECT authority_revision INTO v_before
                      FROM request_engine.principals
                     WHERE id = p_principal_id
                       AND organization_id = request_engine.current_organization_id()
                       AND principal_kind = 'integration' AND principal_plane = 'tenant'
                     FOR UPDATE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'Integration Principal not found' USING ERRCODE = 'P0002';
                    END IF;
                END IF;
                v_revision := request_engine.provision_integration_state(p_principal_id, p_binding_id, p_workload_identity_id, p_credential_id, p_identity_authority_id, p_token_digest, p_token_fingerprint, p_credential_expires_at, p_provenance_reference);
                IF 'provision' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, 'provision', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $$;


ALTER FUNCTION request_engine.provision_integration(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: provision_integration_state(uuid, uuid, uuid, uuid, uuid, bytea, text, timestamp with time zone, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.provision_integration_state(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_authority record;
            v_existing request_engine.principals%ROWTYPE;
            v_existing_binding record;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager(
                'integration.provision'
            );
            IF p_principal_id = v_actor_id
               OR length(btrim(p_provenance_reference)) = 0
               OR p_credential_expires_at IS NULL
               OR p_credential_expires_at <= clock_timestamp()
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
            THEN
                RAISE EXCEPTION 'Invalid integration provisioning input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT * INTO v_existing
              FROM request_engine.principals
             WHERE id = p_principal_id;
            IF FOUND THEN
                IF v_existing.principal_kind <> 'integration'
                   OR v_existing.organization_id IS DISTINCT FROM v_org_id
                THEN
                    RAISE EXCEPTION 'Integration provisioning replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                SELECT * INTO v_existing_binding
                  FROM request_engine.identity_bindings
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'Integration provisioning replay conflicts'
                        USING ERRCODE = '23505';
                END IF;
                RETURN v_existing.authority_revision;
            END IF;

            IF EXISTS (
                SELECT 1 FROM request_engine.workload_identities
                 WHERE id = p_workload_identity_id
            ) OR EXISTS (
                SELECT 1 FROM request_engine.workload_credentials
                 WHERE id = p_credential_id
            ) THEN
                RAISE EXCEPTION 'Integration provisioning identifiers already exist'
                    USING ERRCODE = '23505';
            END IF;

            SELECT kind, status
              INTO v_authority
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
             FOR SHARE;
            IF NOT FOUND
               OR v_authority.kind <> 'workload'
               OR v_authority.status <> 'active'
            THEN
                RAISE EXCEPTION
                    'Integration provisioning requires an active workload authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.principals (
                id,
                organization_id,
                principal_plane,
                principal_kind,
                external_subject
            ) VALUES (
                p_principal_id,
                v_org_id,
                'tenant',
                'integration',
                'workload:' || p_workload_identity_id::text
            );

            INSERT INTO request_engine.workload_identities (
                id,
                identity_authority_id,
                workload_kind,
                status
            ) VALUES (
                p_workload_identity_id,
                p_identity_authority_id,
                'integration',
                'active'
            );

            INSERT INTO request_engine.workload_credentials (
                id,
                workload_identity_id,
                token_digest,
                token_fingerprint,
                status,
                expires_at
            ) VALUES (
                p_credential_id,
                p_workload_identity_id,
                p_token_digest,
                p_token_fingerprint,
                'active',
                p_credential_expires_at
            );

            INSERT INTO request_engine.identity_bindings (
                id,
                organization_id,
                principal_id,
                principal_plane,
                identity_authority_id,
                subject_id,
                status
            ) VALUES (
                p_binding_id,
                v_org_id,
                p_principal_id,
                'tenant',
                p_identity_authority_id,
                p_workload_identity_id::text,
                'pending'
            );

            SELECT authority_revision
              INTO v_existing.authority_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_existing.authority_revision;
        END
        $_$;


ALTER FUNCTION request_engine.provision_integration_state(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) OWNER TO request_engine_schema_owner;

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
-- Name: read_identity_link_intent(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.read_identity_link_intent(p_intent_id uuid) RETURNS TABLE(intent_id uuid, actor_principal_id uuid, target_authority_id uuid, target_authority_kind text, actor_binding_revision bigint, status text, expires_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT i.id,
                   i.actor_principal_id,
                   i.target_authority_id,
                   a.kind,
                   i.actor_binding_revision,
                   i.status,
                   i.expires_at
              FROM request_engine.identity_link_intents AS i
              JOIN request_engine.identity_authorities AS a
                ON a.id = i.target_authority_id
             WHERE i.id = p_intent_id
               AND i.organization_id = request_engine.current_organization_id()
        $$;


ALTER FUNCTION request_engine.read_identity_link_intent(p_intent_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_onboarding_identity_facts(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.read_onboarding_identity_facts(p_organization_id uuid) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_active_controller_id uuid;
            v_effective_controller_id uuid;
            v_policy_subject_id uuid;
            v_recorded_policy_key text;
            v_policy_revision integer;
            v_policy_grants jsonb;
            v_policy_ready boolean := false;
            v_staff_available boolean := false;
            v_authority_revision bigint;
        BEGIN
            IF p_organization_id IS NULL OR p_organization_id IS DISTINCT FROM v_org_id THEN
                RAISE EXCEPTION 'Onboarding identity facts are tenant-scoped'
                    USING ERRCODE = '42501';
            END IF;

            SELECT membership.principal_id INTO v_active_controller_id
              FROM request_engine.staff_memberships AS membership
              JOIN request_engine.principals AS principal
                ON principal.id = membership.principal_id
               AND principal.principal_plane = 'tenant' AND principal.active
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND (SELECT count(DISTINCT grant_row.capability_key)
                      FROM request_engine.principal_authority_grants AS grant_row
                     WHERE grant_row.organization_id = p_organization_id
                       AND grant_row.principal_id = membership.principal_id
                       AND grant_row.status = 'active'
                       AND grant_row.capability_key IN (
                           'staff.manage_membership','staff.manage_authority','identity.bind'
                       )) = 3
             ORDER BY membership.principal_id LIMIT 1;

            SELECT membership.principal_id INTO v_effective_controller_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                   p_organization_id, membership.principal_id
               )
             ORDER BY membership.principal_id LIMIT 1;

            SELECT COALESCE(
                (SELECT adoption.target_policy_key
                   FROM request_engine.controller_policy_adoption_facts AS adoption
                  WHERE adoption.organization_id = p_organization_id
                  ORDER BY adoption.applied_at DESC, adoption.id DESC LIMIT 1),
                root_fact.initial_controller_policy_key
            ), root_fact.controller_principal_id
              INTO v_recorded_policy_key, v_policy_subject_id
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = p_organization_id;

            IF v_recorded_policy_key IS NOT NULL THEN
                SELECT policy.revision, policy.grants
                  INTO v_policy_revision, v_policy_grants
                  FROM request_engine.initial_controller_policies AS policy
                 WHERE policy.policy_key = v_recorded_policy_key;
                IF FOUND AND EXISTS (
                    SELECT 1 FROM request_engine.staff_memberships membership
                    JOIN request_engine.principals principal
                      ON principal.id=membership.principal_id
                     AND principal.principal_plane='tenant' AND principal.active
                    WHERE membership.organization_id=p_organization_id
                      AND membership.principal_id=v_policy_subject_id
                      AND membership.status='active'
                ) THEN
                    v_policy_ready := NOT EXISTS (
                        SELECT 1 FROM jsonb_to_recordset(v_policy_grants)
                            AS g(capability_key text, authority_plane text, delegable boolean)
                         WHERE NOT EXISTS (
                             SELECT 1 FROM request_engine.principal_authority_grants AS active
                              WHERE active.organization_id = p_organization_id
                                AND active.principal_id = v_policy_subject_id
                                AND active.capability_key = g.capability_key
                                AND active.authority_plane = g.authority_plane
                                AND active.delegable = g.delegable
                                AND active.status = 'active'
                         )
                    );
                END IF;
            END IF;

            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS membership_grant
                  JOIN request_engine.principal_authority_grants AS authority_grant
                    ON authority_grant.organization_id = membership_grant.organization_id
                   AND authority_grant.principal_id = membership_grant.principal_id
                   AND authority_grant.capability_key = 'staff.manage_authority'
                   AND authority_grant.status = 'active'
                  JOIN request_engine.principals AS principal
                    ON principal.id = membership_grant.principal_id
                   AND principal.principal_plane = 'tenant' AND principal.active
                 WHERE membership_grant.organization_id = p_organization_id
                   AND membership_grant.capability_key = 'staff.manage_membership'
                   AND membership_grant.status = 'active'
            ) INTO v_staff_available;

            -- This revision accompanies current_policy_ready, which is evaluated
            -- against the immutable original controller. Do not report another
            -- active controller's revision for that policy subject.
            IF v_policy_subject_id IS NOT NULL THEN
                SELECT principal.authority_revision INTO v_authority_revision
                  FROM request_engine.principals AS principal
                 WHERE principal.id = v_policy_subject_id;
            END IF;

            RETURN jsonb_build_object(
                'identity', jsonb_build_object(
                    'active_controller', v_active_controller_id IS NOT NULL,
                    'authenticatable_controller', v_effective_controller_id IS NOT NULL
                ),
                'tenant_control', jsonb_build_object(
                    'current_policy_ready', v_policy_ready,
                    'recorded_policy_key', v_recorded_policy_key
                ),
                'staff_administration', jsonb_build_object('available', v_staff_available),
                'observed_at', to_char(clock_timestamp() AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
                'controller_authority_revision', v_authority_revision,
                'policy_revision', v_policy_revision
            );
        END
        $$;


