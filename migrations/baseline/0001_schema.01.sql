--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6 (Debian 18.6-1.pgdg13+2)
-- Dumped by pg_dump version 18.6 (Debian 18.6-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: request_admin; Type: SCHEMA; Schema: -; Owner: request_engine_schema_owner
--

CREATE SCHEMA request_admin;


ALTER SCHEMA request_admin OWNER TO request_engine_schema_owner;

--
-- Name: request_cmd; Type: SCHEMA; Schema: -; Owner: request_engine_schema_owner
--

CREATE SCHEMA request_cmd;


ALTER SCHEMA request_cmd OWNER TO request_engine_schema_owner;

--
-- Name: request_engine; Type: SCHEMA; Schema: -; Owner: request_engine_schema_owner
--

CREATE SCHEMA request_engine;


ALTER SCHEMA request_engine OWNER TO request_engine_schema_owner;

--
-- Name: request_read; Type: SCHEMA; Schema: -; Owner: request_engine_schema_owner
--

CREATE SCHEMA request_read;


ALTER SCHEMA request_read OWNER TO request_engine_schema_owner;

--
-- Name: btree_gist; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public;


--
-- Name: EXTENSION btree_gist; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION btree_gist IS 'support for indexing common datatypes in GiST';


--
-- Name: activate_shared_capacity_binding(uuid, uuid, uuid, text, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.activate_shared_capacity_binding(p_organization_id uuid, p_resource_id uuid, p_shared_capacity_identity_id uuid, p_authority_ref text, p_reason text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_binding_id uuid;
    v_capacity_model text;
    v_conflict boolean;
BEGIN
    IF p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid SharedCapacityBinding authority request'
            USING ERRCODE = '22023';
    END IF;

    -- Canonical lock order: tenant-local Resource first, shared root second.
    SELECT capacity_model
      INTO v_capacity_model
      FROM request_engine.resources
     WHERE organization_id = p_organization_id
       AND id = p_resource_id
       AND active
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Resource is not active'
            USING ERRCODE = '22023';
    END IF;
    IF v_capacity_model <> 'exclusive' THEN
        RAISE EXCEPTION 'initial shared-capacity bindings require exclusive Resource capacity'
            USING ERRCODE = '22023';
    END IF;

    PERFORM 1
      FROM request_engine.shared_capacity_identities
     WHERE id = p_shared_capacity_identity_id
       AND status = 'active'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SharedCapacityIdentity is not active'
            USING ERRCODE = '22023';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM request_engine.shared_capacity_bindings
         WHERE organization_id = p_organization_id
           AND resource_id = p_resource_id
           AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'Resource already has an active SharedCapacityBinding'
            USING ERRCODE = '23505';
    END IF;

    -- Activating a binding must not turn already-valid commitments into an
    -- overlap.  Existing live claims on this Resource become linked only after
    -- this check succeeds while both serialization roots are held.
    SELECT EXISTS (
        SELECT 1
          FROM request_engine.capacity_claims local_claim
          JOIN request_engine.shared_capacity_claim_links foreign_link
            ON foreign_link.shared_capacity_identity_id = p_shared_capacity_identity_id
          JOIN request_engine.capacity_claims foreign_claim
            ON foreign_claim.id = foreign_link.capacity_claim_id
          LEFT JOIN request_engine.reservations local_reservation
            ON local_reservation.organization_id = local_claim.organization_id
           AND local_reservation.id = local_claim.reservation_id
          LEFT JOIN request_engine.capacity_holds local_hold
            ON local_hold.organization_id = local_claim.organization_id
           AND local_hold.id = local_claim.hold_id
          LEFT JOIN request_engine.reservations foreign_reservation
            ON foreign_reservation.organization_id = foreign_claim.organization_id
           AND foreign_reservation.id = foreign_claim.reservation_id
          LEFT JOIN request_engine.capacity_holds foreign_hold
            ON foreign_hold.organization_id = foreign_claim.organization_id
           AND foreign_hold.id = foreign_claim.hold_id
         WHERE local_claim.organization_id = p_organization_id
           AND local_claim.resource_id = p_resource_id
           AND local_claim.status = 'active'
           AND foreign_claim.status = 'active'
           AND foreign_claim.id <> local_claim.id
           AND foreign_claim.during && local_claim.during
           AND (
               (local_claim.reservation_id IS NOT NULL AND local_reservation.status = 'confirmed')
               OR
               (local_claim.reservation_id IS NULL AND local_hold.status = 'active'
                AND local_hold.expires_at > clock_timestamp())
           )
           AND (
               (foreign_claim.reservation_id IS NOT NULL AND foreign_reservation.status = 'confirmed')
               OR
               (foreign_claim.reservation_id IS NULL AND foreign_hold.status = 'active'
                AND foreign_hold.expires_at > clock_timestamp())
           )
    ) INTO v_conflict;

    IF v_conflict THEN
        RAISE EXCEPTION 'capacity unavailable'
            USING ERRCODE = '23P01';
    END IF;

    INSERT INTO request_engine.shared_capacity_bindings (
        shared_capacity_identity_id, organization_id, resource_id,
        authorized_by, authorization_reason
    ) VALUES (
        p_shared_capacity_identity_id, p_organization_id, p_resource_id,
        btrim(p_authority_ref), btrim(p_reason)
    )
    RETURNING id INTO v_binding_id;

    INSERT INTO request_engine.shared_capacity_claim_links (
        capacity_claim_id, shared_capacity_identity_id
    )
    SELECT c.id, p_shared_capacity_identity_id
      FROM request_engine.capacity_claims c
      LEFT JOIN request_engine.reservations r
        ON r.organization_id = c.organization_id
       AND r.id = c.reservation_id
      LEFT JOIN request_engine.capacity_holds h
        ON h.organization_id = c.organization_id
       AND h.id = c.hold_id
     WHERE c.organization_id = p_organization_id
       AND c.resource_id = p_resource_id
       AND c.status = 'active'
       AND (
           (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
           OR
           (c.reservation_id IS NULL AND h.status = 'active'
            AND h.expires_at > clock_timestamp())
       )
    ON CONFLICT (capacity_claim_id) DO NOTHING;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, shared_capacity_identity_id, binding_id,
        resource_organization_id, resource_id, authority_ref, reason
    ) VALUES (
        'binding.activated', p_shared_capacity_identity_id, v_binding_id,
        p_organization_id, p_resource_id, btrim(p_authority_ref), btrim(p_reason)
    );

    RETURN v_binding_id;
END
$$;


ALTER FUNCTION request_admin.activate_shared_capacity_binding(p_organization_id uuid, p_resource_id uuid, p_shared_capacity_identity_id uuid, p_authority_ref text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: create_global_identity(text, text, text, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.create_global_identity(p_identity_kind text, p_evidence_ref text, p_authority_ref text, p_reason text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_id uuid;
BEGIN
    IF p_identity_kind NOT IN ('person', 'organization')
       OR p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid GlobalIdentity authority request'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO request_engine.global_identities (
        identity_kind, evidence_ref, created_authority_ref, creation_reason
    ) VALUES (
        p_identity_kind, NULLIF(btrim(p_evidence_ref), ''), btrim(p_authority_ref), btrim(p_reason)
    )
    RETURNING id INTO v_id;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, global_identity_id, authority_ref, reason
    ) VALUES (
        'global_identity.created', v_id, btrim(p_authority_ref), btrim(p_reason)
    );

    RETURN v_id;
END
$$;


ALTER FUNCTION request_admin.create_global_identity(p_identity_kind text, p_evidence_ref text, p_authority_ref text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: create_service_classification(text, text, text, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.create_service_classification(p_classification_key text, p_canonical_name text, p_authority_ref text, p_reason text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_id uuid;
BEGIN
    IF btrim(COALESCE(p_authority_ref, '')) = '' OR btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'authority_ref and reason are required' USING ERRCODE = '22023';
    END IF;
    INSERT INTO request_engine.service_classifications (classification_key, canonical_name)
    VALUES (p_classification_key, p_canonical_name)
    RETURNING id INTO v_id;
    INSERT INTO request_engine.service_classification_authority_events (
        service_classification_id, action, authority_ref, reason
    ) VALUES (v_id, 'created', p_authority_ref, p_reason);
    RETURN v_id;
END
$$;


ALTER FUNCTION request_admin.create_service_classification(p_classification_key text, p_canonical_name text, p_authority_ref text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: create_shared_capacity_identity(uuid, text, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.create_shared_capacity_identity(p_global_identity_id uuid, p_authority_ref text, p_reason text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_id uuid;
BEGIN
    IF p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid SharedCapacityIdentity authority request'
            USING ERRCODE = '22023';
    END IF;

    PERFORM 1
      FROM request_engine.global_identities
     WHERE id = p_global_identity_id
       AND status = 'active'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'GlobalIdentity is not active'
            USING ERRCODE = '22023';
    END IF;

    INSERT INTO request_engine.shared_capacity_identities (
        global_identity_id, created_authority_ref, creation_reason
    ) VALUES (
        p_global_identity_id, btrim(p_authority_ref), btrim(p_reason)
    )
    RETURNING id INTO v_id;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, global_identity_id, shared_capacity_identity_id,
        authority_ref, reason
    ) VALUES (
        'shared_capacity.created', p_global_identity_id, v_id,
        btrim(p_authority_ref), btrim(p_reason)
    );

    RETURN v_id;
END
$$;


ALTER FUNCTION request_admin.create_shared_capacity_identity(p_global_identity_id uuid, p_authority_ref text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: replay_dead_outbox_message(uuid, uuid, integer, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.replay_dead_outbox_message(p_organization_id uuid, p_message_id uuid, p_additional_attempts integer, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_actor_principal_id uuid;
    v_updated bigint;
BEGIN
    v_actor_principal_id := request_engine.require_trusted_actor_context(p_organization_id);
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'replay reason is required' USING ERRCODE = '22023';
    END IF;
    IF p_additional_attempts <= 0 OR p_additional_attempts > 100 THEN
        RAISE EXCEPTION 'additional attempts must be between 1 and 100' USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages
       SET status = 'pending', claim_token = NULL, lease_until = NULL,
           max_attempts = max_attempts + p_additional_attempts,
           next_attempt_at = clock_timestamp(), last_error_class = NULL,
           replay_count = replay_count + 1, last_replayed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id AND id = p_message_id AND status = 'dead';
    GET DIAGNOSTICS v_updated = ROW_COUNT;

    IF v_updated = 1 THEN
        INSERT INTO request_engine.audit_records (
            organization_id, actor_principal_id, command_name,
            aggregate_kind, aggregate_id, correlation_data, details
        ) VALUES (
            p_organization_id, v_actor_principal_id,
            'admin.replay_outbox_message', 'OutboxMessage', p_message_id,
            jsonb_build_object(
                'correlation_id', current_setting('request_engine.correlation_id', true),
                'principal_kind', current_setting('request_engine.principal_kind', true),
                'authentication_method', current_setting('request_engine.authentication_method', true)
            ),
            jsonb_build_object('reason', p_reason, 'additional_attempts', p_additional_attempts)
        );
    END IF;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_admin.replay_dead_outbox_message(p_organization_id uuid, p_message_id uuid, p_additional_attempts integer, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: replay_dead_scheduled_action(uuid, uuid, integer, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.replay_dead_scheduled_action(p_organization_id uuid, p_action_id uuid, p_additional_attempts integer, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_actor_principal_id uuid;
    v_updated bigint;
BEGIN
    v_actor_principal_id := request_engine.require_trusted_actor_context(p_organization_id);
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'replay reason is required' USING ERRCODE = '22023';
    END IF;
    IF p_additional_attempts <= 0 OR p_additional_attempts > 100 THEN
        RAISE EXCEPTION 'additional attempts must be between 1 and 100' USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.scheduled_actions
       SET status = 'pending', claim_token = NULL, lease_until = NULL,
           max_attempts = max_attempts + p_additional_attempts,
           next_attempt_at = clock_timestamp(), last_error_class = NULL,
           replay_count = replay_count + 1, last_replayed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id AND id = p_action_id AND status = 'dead';
    GET DIAGNOSTICS v_updated = ROW_COUNT;

    IF v_updated = 1 THEN
        INSERT INTO request_engine.audit_records (
            organization_id, actor_principal_id, command_name,
            aggregate_kind, aggregate_id, correlation_data, details
        ) VALUES (
            p_organization_id, v_actor_principal_id,
            'admin.replay_scheduled_action', 'ScheduledAction', p_action_id,
            jsonb_build_object(
                'correlation_id', current_setting('request_engine.correlation_id', true),
                'principal_kind', current_setting('request_engine.principal_kind', true),
                'authentication_method', current_setting('request_engine.authentication_method', true)
            ),
            jsonb_build_object('reason', p_reason, 'additional_attempts', p_additional_attempts)
        );
    END IF;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_admin.replay_dead_scheduled_action(p_organization_id uuid, p_action_id uuid, p_additional_attempts integer, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: replay_provider_event(uuid, uuid, integer, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.replay_provider_event(p_organization_id uuid, p_provider_event_row_id uuid, p_additional_attempts integer, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_actor_principal_id uuid;
    v_updated bigint;
BEGIN
    v_actor_principal_id := request_engine.require_trusted_actor_context(p_organization_id);
    IF p_reason IS NULL OR btrim(p_reason) = '' THEN
        RAISE EXCEPTION 'replay reason is required' USING ERRCODE = '22023';
    END IF;
    IF p_additional_attempts <= 0 OR p_additional_attempts > 100 THEN
        RAISE EXCEPTION 'additional attempts must be between 1 and 100' USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.provider_events
       SET status = 'received', claim_token = NULL, lease_until = NULL,
           processed_at = NULL, max_attempts = max_attempts + p_additional_attempts,
           next_attempt_at = clock_timestamp(), last_error_class = NULL,
           replay_count = replay_count + 1, last_replayed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_provider_event_row_id
       AND status IN ('dead', 'rejected');
    GET DIAGNOSTICS v_updated = ROW_COUNT;

    IF v_updated = 1 THEN
        INSERT INTO request_engine.audit_records (
            organization_id, actor_principal_id, command_name,
            aggregate_kind, aggregate_id, correlation_data, details
        ) VALUES (
            p_organization_id, v_actor_principal_id,
            'admin.replay_provider_event', 'ProviderEvent', p_provider_event_row_id,
            jsonb_build_object(
                'correlation_id', current_setting('request_engine.correlation_id', true),
                'principal_kind', current_setting('request_engine.principal_kind', true),
                'authentication_method', current_setting('request_engine.authentication_method', true)
            ),
            jsonb_build_object('reason', p_reason, 'additional_attempts', p_additional_attempts)
        );
    END IF;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_admin.replay_provider_event(p_organization_id uuid, p_provider_event_row_id uuid, p_additional_attempts integer, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: retire_service_classification(uuid, bigint, text, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.retire_service_classification(p_service_classification_id uuid, p_expected_revision bigint, p_authority_ref text, p_reason text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_revision bigint;
    v_status text;
BEGIN
    IF btrim(COALESCE(p_authority_ref, '')) = '' OR btrim(COALESCE(p_reason, '')) = '' THEN
        RAISE EXCEPTION 'authority_ref and reason are required' USING ERRCODE = '22023';
    END IF;
    SELECT revision, status INTO v_revision, v_status
      FROM request_engine.service_classifications
     WHERE id = p_service_classification_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'ServiceClassification not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_status <> 'active' OR v_revision <> p_expected_revision THEN
        RAISE EXCEPTION 'ServiceClassification revision/status conflict' USING ERRCODE = '40001';
    END IF;
    IF request_engine.has_active_discovery_mapping(p_service_classification_id) THEN
        RAISE EXCEPTION 'active Offering mappings still reference ServiceClassification'
            USING ERRCODE = '55000';
    END IF;
    UPDATE request_engine.service_classifications
       SET status = 'retired', revision = revision + 1
     WHERE id = p_service_classification_id
     RETURNING revision INTO v_revision;
    INSERT INTO request_engine.service_classification_authority_events (
        service_classification_id, action, authority_ref, reason
    ) VALUES (p_service_classification_id, 'retired', p_authority_ref, p_reason);
    RETURN v_revision;
END
$$;


ALTER FUNCTION request_admin.retire_service_classification(p_service_classification_id uuid, p_expected_revision bigint, p_authority_ref text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_shared_capacity_binding(uuid, text, text); Type: FUNCTION; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_admin.revoke_shared_capacity_binding(p_binding_id uuid, p_authority_ref text, p_reason text) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_binding request_engine.shared_capacity_bindings%ROWTYPE;
BEGIN
    IF p_authority_ref IS NULL OR btrim(p_authority_ref) = ''
       OR p_reason IS NULL OR btrim(p_reason) = ''
    THEN
        RAISE EXCEPTION 'invalid SharedCapacityBinding revocation request'
            USING ERRCODE = '22023';
    END IF;

    SELECT *
      INTO v_binding
      FROM request_engine.shared_capacity_bindings
     WHERE id = p_binding_id;
    IF NOT FOUND OR v_binding.status <> 'active' THEN
        RAISE EXCEPTION 'SharedCapacityBinding is not active'
            USING ERRCODE = '22023';
    END IF;

    -- Same canonical order as booking/activation: Resource, then shared root.
    PERFORM 1
      FROM request_engine.resources
     WHERE organization_id = v_binding.organization_id
       AND id = v_binding.resource_id
     FOR UPDATE;
    PERFORM 1
      FROM request_engine.shared_capacity_identities
     WHERE id = v_binding.shared_capacity_identity_id
     FOR UPDATE;

    -- Re-read after acquiring serialization roots so a concurrent transition
    -- cannot be applied based on the stale snapshot above.
    SELECT *
      INTO v_binding
      FROM request_engine.shared_capacity_bindings
     WHERE id = p_binding_id
       AND status = 'active'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SharedCapacityBinding is not active'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.shared_capacity_bindings
       SET status = 'revoked',
           valid_until = clock_timestamp(),
           revoked_by = btrim(p_authority_ref),
           revocation_reason = btrim(p_reason),
           revision = revision + 1
     WHERE id = p_binding_id;

    INSERT INTO request_engine.shared_capacity_authority_events (
        event_kind, shared_capacity_identity_id, binding_id,
        resource_organization_id, resource_id, authority_ref, reason
    ) VALUES (
        'binding.revoked', v_binding.shared_capacity_identity_id, p_binding_id,
        v_binding.organization_id, v_binding.resource_id,
        btrim(p_authority_ref), btrim(p_reason)
    );
END
$$;


ALTER FUNCTION request_admin.revoke_shared_capacity_binding(p_binding_id uuid, p_authority_ref text, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: acquire_idempotency(uuid, uuid, text, text, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) RETURNS TABLE(idempotency_id uuid, status text, result_data jsonb, replay boolean)
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_record request_engine.idempotency_records%ROWTYPE;
    v_capability text;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    v_capability := CASE p_capability
        WHEN 'appointments.attendance.accepted'
            THEN 'booking.record_attendance_response'
        WHEN 'appointments.attendance.declined'
            THEN 'booking.record_attendance_response'
        ELSE p_capability
    END;

    INSERT INTO request_engine.idempotency_records (
        organization_id,
        principal_id,
        capability,
        idempotency_key,
        request_fingerprint
    )
    VALUES (
        p_organization_id,
        p_principal_id,
        v_capability,
        p_idempotency_key,
        p_request_fingerprint
    )
    ON CONFLICT (organization_id, principal_id, capability, idempotency_key)
    DO NOTHING;

    SELECT *
      INTO v_record
      FROM request_engine.idempotency_records i
     WHERE i.organization_id = p_organization_id
       AND i.principal_id = p_principal_id
       AND i.capability = v_capability
       AND i.idempotency_key = p_idempotency_key
     FOR UPDATE;

    IF v_record.request_fingerprint <> p_request_fingerprint THEN
        RAISE EXCEPTION 'idempotency key reused with different request fingerprint'
            USING ERRCODE = 'P1001';
    END IF;

    RETURN QUERY SELECT
        v_record.id,
        v_record.status,
        v_record.result_data,
        v_record.status = 'completed';
END
$$;


ALTER FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) OWNER TO request_engine_schema_owner;

--
-- Name: cancel_scheduled_action(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_status text;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    UPDATE request_engine.scheduled_actions
       SET status = 'cancelled',
           claim_token = NULL,
           lease_until = NULL,
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND id = p_action_id
       AND status IN ('pending', 'leased')
    RETURNING status INTO v_status;

    IF FOUND THEN
        RETURN v_status;
    END IF;

    SELECT status
      INTO v_status
      FROM request_engine.scheduled_actions
     WHERE organization_id = p_organization_id
       AND id = p_action_id;

    RETURN COALESCE(v_status, 'not_found');
END
$$;


ALTER FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: claim_outbox_messages(integer, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval DEFAULT '00:01:00'::interval) RETURNS TABLE(message_id uuid, organization_id uuid, claim_token uuid, event_type text, schema_version integer, aggregate_kind text, aggregate_id uuid, payload jsonb, attempt_count integer, lease_until timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.outbox_messages o
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE o.attempt_count >= o.max_attempts
       AND (
           (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
           (o.status = 'leased' AND o.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT o.id,
               o.organization_id,
               CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY o.organization_id
                   ORDER BY
                       CASE WHEN o.status = 'pending' THEN o.next_attempt_at ELSE o.lease_until END,
                       o.id
               ) AS tenant_rank
          FROM request_engine.outbox_messages o
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= statement_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= statement_timestamp())
           )
    ), candidates AS (
        SELECT o.id
          FROM ranked r
          JOIN request_engine.outbox_messages o ON o.id = r.id
         WHERE o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF o SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.outbox_messages o
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = o.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE o.id = c.id
           AND o.attempt_count < o.max_attempts
           AND (
               (o.status = 'pending' AND o.next_attempt_at <= clock_timestamp()) OR
               (o.status = 'leased' AND o.lease_until <= clock_timestamp())
           )
        RETURNING o.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.event_type,
           c.schema_version,
           c.aggregate_kind,
           c.aggregate_id,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$$;


ALTER FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval) OWNER TO request_engine_schema_owner;

--
-- Name: claim_provider_events(integer, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval DEFAULT '00:01:00'::interval) RETURNS TABLE(provider_event_row_id uuid, organization_id uuid, claim_token uuid, provider_key text, connection_key text, provider_event_id text, payload_hash text, payload jsonb, attempt_count integer, lease_until timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.provider_events e
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE e.attempt_count >= e.max_attempts
       AND (
           (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
           (e.status = 'leased' AND e.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT e.id,
               e.organization_id,
               CASE WHEN e.status = 'received' THEN e.next_attempt_at ELSE e.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY e.organization_id
                   ORDER BY
                       CASE WHEN e.status = 'received' THEN e.next_attempt_at ELSE e.lease_until END,
                       e.id
               ) AS tenant_rank
          FROM request_engine.provider_events e
         WHERE e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= statement_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= statement_timestamp())
           )
    ), candidates AS (
        SELECT e.id
          FROM ranked r
          JOIN request_engine.provider_events e ON e.id = r.id
         WHERE e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF e SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.provider_events e
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = e.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE e.id = c.id
           AND e.attempt_count < e.max_attempts
           AND (
               (e.status = 'received' AND e.next_attempt_at <= clock_timestamp()) OR
               (e.status = 'leased' AND e.lease_until <= clock_timestamp())
           )
        RETURNING e.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.provider_key,
           c.connection_key,
           c.provider_event_id,
           c.payload_hash,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$$;


ALTER FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval) OWNER TO request_engine_schema_owner;

--
-- Name: claim_scheduled_actions(integer, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval DEFAULT '00:01:00'::interval) RETURNS TABLE(action_id uuid, organization_id uuid, claim_token uuid, owner_module text, action_type text, action_version integer, subject_kind text, subject_id uuid, payload jsonb, attempt_count integer, lease_until timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF p_limit <= 0 OR p_limit > 500 THEN
        RAISE EXCEPTION 'claim limit must be between 1 and 500'
            USING ERRCODE = '22023';
    END IF;
    IF p_lease <= interval '0 seconds' OR p_lease > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;

    UPDATE request_engine.scheduled_actions s
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = COALESCE(last_error_class, 'max_attempts_exhausted'),
           updated_at = clock_timestamp()
     WHERE s.attempt_count >= s.max_attempts
       AND (
           (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
           (s.status = 'leased' AND s.lease_until <= clock_timestamp())
       );

    RETURN QUERY
    WITH ranked AS MATERIALIZED (
        SELECT s.id,
               s.organization_id,
               CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END AS due_at,
               row_number() OVER (
                   PARTITION BY s.organization_id
                   ORDER BY
                       CASE WHEN s.status = 'pending' THEN s.next_attempt_at ELSE s.lease_until END,
                       s.id
               ) AS tenant_rank
          FROM request_engine.scheduled_actions s
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= statement_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= statement_timestamp())
           )
    ), candidates AS (
        SELECT s.id
          FROM ranked r
          JOIN request_engine.scheduled_actions s ON s.id = r.id
         WHERE s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
         ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id
         FOR UPDATE OF s SKIP LOCKED
         LIMIT p_limit
    ), claimed AS (
        UPDATE request_engine.scheduled_actions s
           SET status = 'leased',
               claim_token = uuidv7(),
               lease_until = clock_timestamp() + p_lease,
               attempt_count = s.attempt_count + 1,
               updated_at = clock_timestamp()
          FROM candidates c
         WHERE s.id = c.id
           AND s.attempt_count < s.max_attempts
           AND (
               (s.status = 'pending' AND s.next_attempt_at <= clock_timestamp()) OR
               (s.status = 'leased' AND s.lease_until <= clock_timestamp())
           )
        RETURNING s.*
    )
    SELECT c.id,
           c.organization_id,
           c.claim_token,
           c.owner_module,
           c.action_type,
           c.action_version,
           c.subject_kind,
           c.subject_id,
           c.payload,
           c.attempt_count,
           c.lease_until
      FROM claimed c
      JOIN ranked r ON r.id = c.id
     ORDER BY r.tenant_rank, r.due_at, r.organization_id, r.id;
END
$$;


ALTER FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval) OWNER TO request_engine_schema_owner;

--
-- Name: complete_idempotency(uuid, jsonb); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.idempotency_records
       SET status = 'completed',
           result_data = p_result_data,
           completed_at = clock_timestamp()
     WHERE id = p_idempotency_id
       AND organization_id = request_engine.current_organization_id()
       AND status = 'in_progress';

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb) OWNER TO request_engine_schema_owner;

--
-- Name: complete_outbox_message(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.outbox_messages
       SET status = 'delivered',
           claim_token = NULL,
           lease_until = NULL,
           delivered_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: complete_provider_event(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.provider_events
       SET status = 'processed',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = clock_timestamp(),
           last_error_class = NULL,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: complete_scheduled_action(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.scheduled_actions
       SET status = 'completed',
           claim_token = NULL,
           lease_until = NULL,
           completed_at = clock_timestamp(),
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: dead_letter_outbox_message(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.outbox_messages
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: dead_letter_provider_event(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.provider_events
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: dead_letter_scheduled_action(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.scheduled_actions
       SET status = 'dead',
           claim_token = NULL,
           lease_until = NULL,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: find_recovery_sweep_scopes(integer); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) RETURNS TABLE(organization_id uuid, service_queue_id uuid)
    LANGUAGE sql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
    SELECT DISTINCT
        sa.organization_id AS organization_id,
        sa.subject_id AS service_queue_id
    FROM request_engine.scheduled_actions sa
    WHERE sa.owner_module = 'operational_recovery'
      AND sa.action_type = 'reassess_recovery_scope'
      AND sa.subject_id IS NOT NULL
    ORDER BY 1, 2
    LIMIT GREATEST(LEAST(COALESCE(p_limit, 0), 500), 0)
$$;


ALTER FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) OWNER TO request_engine_schema_owner;

--
-- Name: lock_outbox_message_claim(uuid, uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_found boolean;
BEGIN
    IF p_organization_id IS DISTINCT FROM request_engine.current_organization_id() THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT true
      INTO v_found
      FROM request_engine.outbox_messages
     WHERE organization_id = p_organization_id
       AND id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    RETURN COALESCE(v_found, false);
END
$$;


ALTER FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_recovery_source_revision(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_revision bigint;
BEGIN
    SELECT revision INTO v_revision
    FROM request_engine.recovery_source_revisions
    WHERE organization_id = p_organization_id
      AND service_queue_id = p_service_queue_id
    FOR UPDATE;
    IF v_revision IS NULL THEN
        RAISE EXCEPTION 'Recovery source revision is not configured for queue %',
            p_service_queue_id
          USING ERRCODE = '23514';
    END IF;
    RETURN v_revision;
END
$$;


ALTER FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_scheduled_action_claim(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_found boolean;
BEGIN
    SELECT true
      INTO v_found
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;

    RETURN COALESCE(v_found, false);
END
$$;


ALTER FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_shared_capacity_roots(uuid, uuid[]); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_context_organization_id uuid;
    v_requested bigint;
    v_local bigint := 0;
    v_resource_id uuid;
BEGIN
    v_context_organization_id := request_engine.current_organization_id();
    IF v_context_organization_id IS NULL
       OR p_organization_id IS NULL
       OR p_organization_id <> v_context_organization_id
    THEN
        RAISE EXCEPTION 'organization context mismatch'
            USING ERRCODE = '42501';
    END IF;

    SELECT count(DISTINCT value)
      INTO v_requested
      FROM unnest(COALESCE(p_resource_ids, ARRAY[]::uuid[])) AS input(value)
     WHERE value IS NOT NULL;

    IF v_requested = 0 THEN
        RETURN;
    END IF;

    -- Validate tenant ownership and take every local root in the same stable
    -- order used by Booking. Counting while locking prevents this protected
    -- function from ever acquiring a shared root first.
    FOR v_resource_id IN
        SELECT r.id
          FROM request_engine.resources r
         WHERE r.organization_id = p_organization_id
           AND r.id = ANY(p_resource_ids)
         ORDER BY r.id
         FOR UPDATE
    LOOP
        v_local := v_local + 1;
    END LOOP;

    IF v_local <> v_requested THEN
        RAISE EXCEPTION 'one or more Resources are not available in tenant context'
            USING ERRCODE = '42501';
    END IF;

    PERFORM 1
      FROM request_engine.shared_capacity_identities s
      JOIN request_engine.shared_capacity_bindings b
        ON b.shared_capacity_identity_id = s.id
       AND b.status = 'active'
     WHERE b.organization_id = p_organization_id
       AND b.resource_id = ANY(p_resource_ids)
       AND s.status = 'active'
     ORDER BY s.id
     FOR UPDATE OF s;
END
$$;


ALTER FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) OWNER TO request_engine_schema_owner;

--
-- Name: mark_queue_entry_service_completed(uuid, uuid, timestamp with time zone); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF request_engine.current_organization_id() IS DISTINCT FROM p_organization_id THEN
                RAISE EXCEPTION 'queue service-complete transition rejects foreign tenant authority'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.queue_entries
               SET status = 'completed',
                   completed_at = p_completed_at,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE organization_id = p_organization_id
               AND id = p_queue_entry_id
               AND status = 'serving';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'QueueEntry % is not serving', p_queue_entry_id
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: mark_queue_entry_service_started(uuid, uuid, timestamp with time zone); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF request_engine.current_organization_id() IS DISTINCT FROM p_organization_id THEN
                RAISE EXCEPTION 'queue service-start transition rejects foreign tenant authority'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.queue_entries
               SET status = 'serving',
                   service_started_at = p_started_at,
                   completed_at = NULL,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE organization_id = p_organization_id
               AND id = p_queue_entry_id
               AND status = 'called';

            IF NOT FOUND THEN
                RAISE EXCEPTION 'QueueEntry % is not callable', p_queue_entry_id
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_cmd.mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: reject_provider_event(uuid, uuid, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    UPDATE request_engine.provider_events
       SET status = 'rejected',
           claim_token = NULL,
           lease_until = NULL,
           processed_at = clock_timestamp(),
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: renew_outbox_message_lease(uuid, uuid, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval DEFAULT '00:01:00'::interval) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.outbox_messages
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval) OWNER TO request_engine_schema_owner;

--
-- Name: renew_provider_event_lease(uuid, uuid, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval DEFAULT '00:01:00'::interval) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.provider_events
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval) OWNER TO request_engine_schema_owner;

--
-- Name: renew_scheduled_action_lease(uuid, uuid, interval); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval DEFAULT '00:01:00'::interval) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_updated bigint;
BEGIN
    IF p_extension <= interval '0 seconds' OR p_extension > interval '15 minutes' THEN
        RAISE EXCEPTION 'lease extension must be > 0 and <= 15 minutes'
            USING ERRCODE = '22023';
    END IF;
    UPDATE request_engine.scheduled_actions
       SET lease_until = clock_timestamp() + p_extension,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated = 1;
END
$$;


ALTER FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval) OWNER TO request_engine_schema_owner;

--
-- Name: retry_outbox_message(uuid, uuid, timestamp with time zone, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.outbox_messages
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN p_next_attempt_at
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_outbox_message_after(uuid, uuid, interval, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.outbox_messages
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.outbox_messages
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_message_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_provider_event_after(uuid, uuid, interval, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.provider_events
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'received' END;
    UPDATE request_engine.provider_events
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'received' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_provider_event_row_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_scheduled_action(uuid, uuid, timestamp with time zone, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN p_next_attempt_at
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: retry_scheduled_action_after(uuid, uuid, interval, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) RETURNS text
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_attempt_count integer;
    v_max_attempts integer;
    v_status text;
    v_updated bigint;
BEGIN
    IF p_delay < interval '0 seconds' OR p_delay > interval '24 hours' THEN
        RAISE EXCEPTION 'retry delay must be between 0 and 24 hours'
            USING ERRCODE = '22023';
    END IF;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
      FROM request_engine.scheduled_actions
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp()
     FOR UPDATE;
    IF NOT FOUND THEN
        RETURN 'stale';
    END IF;

    v_status := CASE WHEN v_attempt_count >= v_max_attempts THEN 'dead' ELSE 'pending' END;
    UPDATE request_engine.scheduled_actions
       SET status = v_status,
           claim_token = NULL,
           lease_until = NULL,
           next_attempt_at = CASE
               WHEN v_status = 'pending' THEN clock_timestamp() + p_delay
               ELSE next_attempt_at
           END,
           last_error_class = p_error_class,
           updated_at = clock_timestamp()
     WHERE id = p_action_id
       AND status = 'leased'
       AND claim_token = p_claim_token
       AND lease_until > clock_timestamp();
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated <> 1 THEN
        RETURN 'stale';
    END IF;
    RETURN v_status;
END
$$;


ALTER FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: schedule_recovery_reassessment(uuid, uuid, bigint); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_dedupe_key text;
    v_inserted boolean := false;
    v_context text := COALESCE(
        current_setting('request_engine.organization_id', true),
        ''
    );
BEGIN
    IF p_service_queue_id IS NULL OR p_revision IS NULL OR p_revision <= 0 THEN
        RETURN false;
    END IF;
    IF v_context <> '' AND v_context <> p_organization_id::text THEN
        RAISE EXCEPTION
            'schedule_recovery_reassessment rejects foreign tenant authority'
            USING ERRCODE = '23514';
    END IF;

    v_dedupe_key := format('f5-reassessment:%s:%s', p_service_queue_id, p_revision);

    INSERT INTO request_engine.scheduled_actions (
        organization_id,
        owner_module,
        action_type,
        action_version,
        subject_kind,
        subject_id,
        payload,
        dedupe_key,
        execute_at,
        next_attempt_at,
        max_attempts
    ) VALUES (
        p_organization_id,
        'operational_recovery',
        'reassess_recovery_scope',
        1,
        'ServiceQueue',
        p_service_queue_id,
        jsonb_build_object(
            'service_queue_id', p_service_queue_id::text,
            'source_revision', p_revision
        ),
        v_dedupe_key,
        clock_timestamp(),
        clock_timestamp(),
        8
    )
    ON CONFLICT (organization_id, dedupe_key) DO NOTHING
    RETURNING true INTO v_inserted;

    UPDATE request_engine.scheduled_actions
       SET status = 'cancelled',
           updated_at = clock_timestamp()
     WHERE organization_id = p_organization_id
       AND owner_module = 'operational_recovery'
       AND action_type = 'reassess_recovery_scope'
       AND subject_id = p_service_queue_id
       AND status = 'pending'
       AND dedupe_key <> v_dedupe_key
       AND (payload->>'source_revision')::bigint < p_revision;

    RETURN v_inserted;
END
$$;


ALTER FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) OWNER TO request_engine_schema_owner;

--
-- Name: assert_arrival_estimate_reservation_confirmed(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_status text;
BEGIN
    SELECT status INTO v_status
      FROM request_engine.reservations
     WHERE organization_id = NEW.organization_id
       AND id = NEW.reservation_id;
    IF v_status IS NULL THEN
        RAISE EXCEPTION 'arrival estimate reservation must exist' USING ERRCODE = '23514';
    END IF;
    IF v_status <> 'confirmed' THEN
        RAISE EXCEPTION 'arrival estimate requires a confirmed reservation'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed() OWNER TO request_engine_schema_owner;

--
-- Name: assert_hold_claim_completeness(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_hold_claim_completeness(p_org uuid, p_hold uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.assert_hold_claim_completeness(p_org uuid, p_hold uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_offered_slot_offer_source_consistency(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_offered_slot_offer_source_consistency(p_organization_id uuid, p_slot_offer_id uuid) RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_offer_status text;
    v_offer_expires_at timestamptz;
    v_hold_status text;
    v_hold_expires_at timestamptz;
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
    SELECT so.status,
           so.expires_at,
           h.status,
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
      INTO v_offer_status,
           v_offer_expires_at,
           v_hold_status,
           v_hold_expires_at,
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
      FROM request_engine.slot_offers so
      JOIN request_engine.capacity_holds h
        ON h.organization_id = so.organization_id
       AND h.id = so.capacity_hold_id
      JOIN request_engine.slot_opportunities o
        ON o.organization_id = so.organization_id
       AND o.id = so.slot_opportunity_id
      JOIN request_engine.waitlist_entries w
        ON w.organization_id = so.organization_id
       AND w.id = so.waitlist_entry_id
      JOIN request_engine.offering_versions ov
        ON ov.organization_id = o.organization_id
       AND ov.id = o.offering_version_id
     WHERE so.organization_id = p_organization_id
       AND so.id = p_slot_offer_id;

    IF NOT FOUND OR v_offer_status <> 'offered' THEN
        RETURN;
    END IF;

    IF v_opportunity_status <> 'open'
       OR v_waitlist_status <> 'active'
       OR v_hold_status <> 'active'
       OR v_hold_expires_at <= clock_timestamp()
       OR v_offer_expires_at > v_hold_expires_at
       OR v_offer_expires_at > lower(v_opportunity_during)
       OR v_hold_subject_party_id <> v_waitlist_subject_party_id
       OR v_hold_offering_version_id <> v_opportunity_offering_version_id
       OR v_waitlist_offering_id <> v_version_offering_id
       OR v_hold_location_id IS DISTINCT FROM v_opportunity_location_id
       OR (
           v_waitlist_location_id IS NOT NULL
           AND v_waitlist_location_id IS DISTINCT FROM v_opportunity_location_id
       )
       OR v_hold_during <> v_opportunity_during
    THEN
        RAISE EXCEPTION 'offered SlotOffer source state is no longer valid'
            USING ERRCODE = '23514';
    END IF;
END
$$;


ALTER FUNCTION request_engine.assert_offered_slot_offer_source_consistency(p_organization_id uuid, p_slot_offer_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_reservation_claim_completeness(uuid, uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_reservation_claim_completeness(p_org uuid, p_reservation uuid) RETURNS void
    LANGUAGE plpgsql
    AS $$
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
$$;


ALTER FUNCTION request_engine.assert_reservation_claim_completeness(p_org uuid, p_reservation uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_service_queue_coherence(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_service_queue_coherence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_entry request_engine.queue_entries%ROWTYPE;
    v_session request_engine.service_sessions%ROWTYPE;
    v_entry_id uuid;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_entry_id := NEW.queue_entry_id;
    ELSE
        v_entry_id := NEW.id;
    END IF;
    SELECT * INTO v_entry FROM request_engine.queue_entries e
     WHERE e.organization_id = NEW.organization_id AND e.id = v_entry_id;
    SELECT * INTO v_session FROM request_engine.service_sessions s
     WHERE s.organization_id = NEW.organization_id AND s.queue_entry_id = v_entry_id;
    IF v_session.id IS NULL THEN
        IF v_entry.status IN ('serving', 'completed')
           AND v_entry.service_started_at IS NOT NULL THEN
            RAISE EXCEPTION 'QueueEntry % execution requires ServiceSession', v_entry_id
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF v_entry.called_at IS NULL OR v_session.started_at < v_entry.called_at THEN
        RAISE EXCEPTION 'ServiceSession % cannot start before QueueEntry is called', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_session.status IN ('active', 'paused') AND v_entry.status <> 'serving' THEN
        RAISE EXCEPTION 'live ServiceSession % requires SERVING QueueEntry', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_session.status = 'completed' AND v_entry.status <> 'completed' THEN
        RAISE EXCEPTION 'completed ServiceSession % requires COMPLETED QueueEntry', v_session.id
            USING ERRCODE = '23514';
    END IF;
    IF v_entry.service_started_at IS DISTINCT FROM v_session.started_at
       OR v_entry.completed_at IS DISTINCT FROM v_session.completed_at THEN
        RAISE EXCEPTION 'QueueEntry compatibility timestamps must equal ServiceSession timestamps'
            USING ERRCODE = '23514';
    END IF;
    IF v_entry.status = 'no_show' THEN
        RAISE EXCEPTION 'NO_SHOW QueueEntry cannot have a ServiceSession' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_service_queue_coherence() OWNER TO request_engine_schema_owner;

--
-- Name: assert_session_interruption_coherence(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_session_interruption_coherence() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
    v_session_id uuid;
    v_status text;
    v_started_at timestamptz;
    v_completed_at timestamptz;
    v_open bigint;
BEGIN
    IF TG_TABLE_NAME = 'service_sessions' THEN
        v_session_id := NEW.id;
    ELSE
        v_session_id := NEW.service_session_id;
    END IF;
    SELECT status, started_at, completed_at
      INTO v_status, v_started_at, v_completed_at
      FROM request_engine.service_sessions
     WHERE organization_id = NEW.organization_id AND id = v_session_id;
    IF NOT FOUND THEN RETURN NEW; END IF;

    IF EXISTS (
        SELECT 1 FROM request_engine.service_session_interruptions i
         WHERE i.organization_id = NEW.organization_id
           AND i.service_session_id = v_session_id
           AND i.started_at < v_started_at
    ) THEN
        RAISE EXCEPTION 'ServiceSession % interruption cannot predate execution', v_session_id
            USING ERRCODE = '23514';
    END IF;
    IF v_completed_at IS NOT NULL AND EXISTS (
        SELECT 1 FROM request_engine.service_session_interruptions i
         WHERE i.organization_id = NEW.organization_id
           AND i.service_session_id = v_session_id
           AND (i.ended_at IS NULL OR i.ended_at > v_completed_at)
    ) THEN
        RAISE EXCEPTION 'ServiceSession % interruption cannot outlive execution', v_session_id
            USING ERRCODE = '23514';
    END IF;

    SELECT count(*) INTO v_open FROM request_engine.service_session_interruptions
     WHERE organization_id = NEW.organization_id
       AND service_session_id = v_session_id AND ended_at IS NULL;
    IF (v_status = 'paused' AND v_open <> 1) OR (v_status <> 'paused' AND v_open <> 0) THEN
        RAISE EXCEPTION 'ServiceSession % interruption state is incoherent', v_session_id
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_session_interruption_coherence() OWNER TO request_engine_schema_owner;

--
-- Name: assert_slot_offer_consistency(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_slot_offer_consistency() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
DECLARE
    offer_row request_engine.slot_offers%ROWTYPE;
    hold_row request_engine.capacity_holds%ROWTYPE;
    opportunity_row request_engine.slot_opportunities%ROWTYPE;
    waitlist_row request_engine.waitlist_entries%ROWTYPE;
    opportunity_offering_id uuid;
    expected_hold_status text;
    v_claim_count bigint;
    v_promoted_claim_count bigint;
    v_reservation_count bigint;
    v_reservation_id uuid;
    v_reservation_status text;
BEGIN
    IF TG_TABLE_NAME = 'slot_offers' THEN
        offer_row := NEW;
    ELSE
        SELECT so.*
          INTO offer_row
          FROM request_engine.slot_offers so
         WHERE so.organization_id = NEW.organization_id
           AND so.capacity_hold_id = NEW.id;

        IF NOT FOUND THEN
            RETURN NEW;
        END IF;
    END IF;

    SELECT h.*
      INTO STRICT hold_row
      FROM request_engine.capacity_holds h
     WHERE h.organization_id = offer_row.organization_id
       AND h.id = offer_row.capacity_hold_id;

    SELECT o.*
      INTO STRICT opportunity_row
      FROM request_engine.slot_opportunities o
     WHERE o.organization_id = offer_row.organization_id
       AND o.id = offer_row.slot_opportunity_id;

    SELECT ov.offering_id
      INTO STRICT opportunity_offering_id
      FROM request_engine.offering_versions ov
     WHERE ov.organization_id = opportunity_row.organization_id
       AND ov.id = opportunity_row.offering_version_id;

    SELECT w.*
      INTO STRICT waitlist_row
      FROM request_engine.waitlist_entries w
     WHERE w.organization_id = offer_row.organization_id
       AND w.id = offer_row.waitlist_entry_id;

    IF waitlist_row.offering_id <> opportunity_offering_id THEN
        RAISE EXCEPTION 'SlotOffer % candidate does not match Opportunity Offering',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF hold_row.subject_party_id <> waitlist_row.subject_party_id THEN
        RAISE EXCEPTION 'SlotOffer provenance mismatch: Hold subject does not match WaitlistEntry subject'
            USING ERRCODE = '23514';
    END IF;

    IF hold_row.offering_version_id <> opportunity_row.offering_version_id
       OR hold_row.location_id IS DISTINCT FROM opportunity_row.location_id
       OR hold_row.during <> opportunity_row.during THEN
        RAISE EXCEPTION 'SlotOffer % Hold does not cover its SlotOpportunity',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    IF offer_row.expires_at > hold_row.expires_at
       OR offer_row.expires_at > lower(opportunity_row.during) THEN
        RAISE EXCEPTION 'SlotOffer % cannot outlive its CapacityHold or SlotOpportunity start',
            offer_row.id USING ERRCODE = '23514';
    END IF;

    expected_hold_status := CASE offer_row.status
        WHEN 'offered' THEN 'active'
        WHEN 'accepted' THEN 'consumed'
        WHEN 'declined' THEN 'released'
        WHEN 'cancelled' THEN 'released'
        WHEN 'expired' THEN 'expired'
        ELSE NULL
    END;

    IF expected_hold_status IS NULL OR hold_row.status <> expected_hold_status THEN
        RAISE EXCEPTION 'SlotOffer % status % requires Hold status %, found %',
            offer_row.id, offer_row.status, expected_hold_status, hold_row.status
            USING ERRCODE = '23514';
    END IF;

    IF offer_row.status = 'accepted' THEN
        IF opportunity_row.status <> 'filled' OR waitlist_row.status <> 'fulfilled' THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires filled Opportunity and fulfilled WaitlistEntry',
                offer_row.id USING ERRCODE = '23514';
        END IF;

        SELECT count(*),
               count(*) FILTER (
                   WHERE c.status = 'active' AND c.reservation_id IS NOT NULL
               ),
               count(DISTINCT c.reservation_id) FILTER (
                   WHERE c.status = 'active' AND c.reservation_id IS NOT NULL
               )
          INTO v_claim_count,
               v_promoted_claim_count,
               v_reservation_count
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = offer_row.organization_id
           AND c.hold_id = offer_row.capacity_hold_id;

        SELECT c.reservation_id
          INTO v_reservation_id
          FROM request_engine.capacity_claims c
         WHERE c.organization_id = offer_row.organization_id
           AND c.hold_id = offer_row.capacity_hold_id
           AND c.status = 'active'
           AND c.reservation_id IS NOT NULL
         LIMIT 1;

        IF v_claim_count = 0
           OR v_promoted_claim_count <> v_claim_count
           OR v_reservation_count <> 1
           OR v_reservation_id IS NULL THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires complete Hold-to-Reservation claim promotion',
                offer_row.id USING ERRCODE = '23514';
        END IF;

        SELECT r.status
          INTO v_reservation_status
          FROM request_engine.reservations r
         WHERE r.organization_id = offer_row.organization_id
           AND r.id = v_reservation_id;

        IF NOT FOUND OR v_reservation_status <> 'confirmed' THEN
            RAISE EXCEPTION 'accepted SlotOffer % requires a confirmed Reservation',
                offer_row.id USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.assert_slot_offer_consistency() OWNER TO request_engine_schema_owner;

--
-- Name: attach_shared_capacity_claim_link(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.attach_shared_capacity_claim_link() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
DECLARE
    v_shared_capacity_identity_id uuid;
BEGIN
    IF NEW.status <> 'active' THEN
        RETURN NEW;
    END IF;

    SELECT b.shared_capacity_identity_id
      INTO v_shared_capacity_identity_id
      FROM request_engine.shared_capacity_bindings b
     WHERE b.organization_id = NEW.organization_id
       AND b.resource_id = NEW.resource_id
       AND b.status = 'active';

    IF v_shared_capacity_identity_id IS NOT NULL THEN
        INSERT INTO request_engine.shared_capacity_claim_links (
            capacity_claim_id, shared_capacity_identity_id
        ) VALUES (
            NEW.id, v_shared_capacity_identity_id
        )
        ON CONFLICT (capacity_claim_id) DO NOTHING;
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.attach_shared_capacity_claim_link() OWNER TO request_engine_schema_owner;

--
-- Name: bind_consumed_identity_candidate_v1(uuid, uuid, text[], uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.bind_consumed_identity_candidate_v1(p_candidate_id uuid, p_party_id uuid, p_consent_fields text[], p_principal_id uuid) RETURNS uuid
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
