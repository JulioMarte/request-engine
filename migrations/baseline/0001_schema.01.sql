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
-- Name: request_auth; Type: SCHEMA; Schema: -; Owner: request_engine_schema_owner
--

CREATE SCHEMA request_auth;


ALTER SCHEMA request_auth OWNER TO request_engine_schema_owner;

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
-- Name: request_platform; Type: SCHEMA; Schema: -; Owner: request_engine_schema_owner
--

CREATE SCHEMA request_platform;


ALTER SCHEMA request_platform OWNER TO request_engine_schema_owner;

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
-- Name: activate_native_recovery_delivery_request(uuid, uuid, integer, uuid, bytea, text, timestamp with time zone, text, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.activate_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_secret_reference text, p_secret_digest text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_identity_id uuid;
            v_address_id uuid;
            v_destination text;
            v_identity_status text;
        BEGIN
            IF p_request_id IS NULL
               OR p_claim_token IS NULL
               OR p_generation IS NULL OR p_generation < 1
               OR p_recovery_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_proof_expires_at IS NULL
               OR p_proof_expires_at <= clock_timestamp()
               OR p_proof_expires_at > clock_timestamp() + interval '30 minutes'
               OR p_secret_reference IS NULL
               OR length(btrim(p_secret_reference)) NOT BETWEEN 1 AND 400
               OR p_secret_digest !~ '^[0-9a-f]{64}$'
            THEN
                RETURN false;
            END IF;

            SELECT request.native_identity_id
              INTO v_identity_id
              FROM request_engine.native_recovery_delivery_requests AS request
             WHERE request.id = p_request_id;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT request.recovery_address_id,
                   request.destination_reference
              INTO v_address_id, v_destination
              FROM request_engine.native_recovery_delivery_requests AS request
             WHERE request.id = p_request_id
               AND request.native_identity_id = v_identity_id
               AND request.status = 'sending'
               AND request.claim_token = p_claim_token
               AND request.generation = p_generation
               AND request.secret_reference IS NULL
               AND request.request_expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.id = v_address_id
               AND address.native_identity_id = v_identity_id
               AND address.status = 'verified'
               AND address.normalized_address = v_destination
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF NOT request_auth.create_native_recovery_intent(
                v_identity_id,
                p_recovery_id,
                p_token_digest,
                p_token_fingerprint,
                p_proof_expires_at
            ) THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET recovery_intent_id = p_recovery_id,
                   secret_reference = btrim(p_secret_reference),
                   secret_digest = p_secret_digest,
                   proof_expires_at = p_proof_expires_at,
                   updated_at = clock_timestamp()
             WHERE request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending';

            INSERT INTO request_engine.native_recovery_delivery_facts (
                request_id,
                native_identity_id,
                recovery_address_id,
                generation,
                event_kind
            ) VALUES (
                p_request_id,
                v_identity_id,
                v_address_id,
                p_generation,
                'staged'
            );
            RETURN true;
        END
        $_$;


ALTER FUNCTION request_auth.activate_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_secret_reference text, p_secret_digest text) OWNER TO request_engine_schema_owner;

--
-- Name: claim_native_recovery_delivery_requests(integer, integer); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.claim_native_recovery_delivery_requests(p_limit integer, p_lease_seconds integer) RETURNS TABLE(request_id uuid, native_identity_id uuid, recovery_address_id uuid, generation integer, recovery_intent_id uuid, secret_reference text, secret_digest text, destination_reference text, proof_expires_at timestamp with time zone, attempt_count integer, claim_token uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_expired record;
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Native recovery delivery claim limit is invalid'
                    USING ERRCODE = '22023';
            END IF;
            IF p_lease_seconds IS NULL OR p_lease_seconds < 1 OR p_lease_seconds > 900 THEN
                RAISE EXCEPTION 'Native recovery delivery lease is invalid'
                    USING ERRCODE = '22023';
            END IF;

            -- A process may disappear after claiming but before it can retry or
            -- finalize. Expired leases are therefore made claimable again under a
            -- new fencing token; staged proof metadata, when present, is retained so
            -- the next worker reconciles/publishes the same proof rather than minting
            -- another one.
            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'pending',
                   claim_token = NULL,
                   lease_until = NULL,
                   next_attempt_at = clock_timestamp(),
                   last_error_class = 'lease_expired',
                   updated_at = clock_timestamp()
             WHERE request.status = 'sending'
               AND request.lease_until <= clock_timestamp();

            FOR v_expired IN
                SELECT request.id,
                       request.native_identity_id,
                       request.recovery_address_id,
                       request.generation,
                       request.recovery_intent_id,
                       CASE
                           WHEN request.request_expires_at <= clock_timestamp()
                           THEN 'request_expired'
                           ELSE 'attempts_exhausted'
                       END AS error_class
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.status = 'pending'
                   AND (
                       request.request_expires_at <= clock_timestamp()
                       OR request.attempt_count >= request.max_attempts
                   )
                 ORDER BY request.id
                 FOR UPDATE SKIP LOCKED
            LOOP
                IF v_expired.recovery_intent_id IS NOT NULL THEN
                    UPDATE request_engine.native_recovery_intents AS intent
                       SET status = 'revoked',
                           revoked_at = clock_timestamp()
                     WHERE intent.id = v_expired.recovery_intent_id
                       AND intent.status = 'pending';
                END IF;
                UPDATE request_engine.native_recovery_delivery_requests AS request
                   SET status = 'failed',
                       last_error_class = v_expired.error_class,
                       updated_at = clock_timestamp()
                 WHERE request.id = v_expired.id;
                INSERT INTO request_engine.native_recovery_delivery_facts (
                    request_id,
                    native_identity_id,
                    recovery_address_id,
                    generation,
                    event_kind,
                    error_class
                ) VALUES (
                    v_expired.id,
                    v_expired.native_identity_id,
                    v_expired.recovery_address_id,
                    v_expired.generation,
                    'delivery_failed',
                    v_expired.error_class
                );
            END LOOP;

            RETURN QUERY
            WITH candidate AS (
                SELECT request.id
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.status = 'pending'
                   AND request.next_attempt_at <= clock_timestamp()
                   AND request.request_expires_at > clock_timestamp()
                   AND request.attempt_count < request.max_attempts
                 ORDER BY request.next_attempt_at, request.id
                 LIMIT p_limit
                 FOR UPDATE SKIP LOCKED
            )
            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'sending',
                   generation = CASE
                       WHEN request.secret_reference IS NULL
                       THEN request.generation + 1
                       ELSE request.generation
                   END,
                   claim_token = uuidv7(),
                   lease_until = clock_timestamp()
                       + make_interval(secs => p_lease_seconds),
                   attempt_count = request.attempt_count + 1,
                   updated_at = clock_timestamp()
              FROM candidate
             WHERE request.id = candidate.id
            RETURNING request.id,
                      request.native_identity_id,
                      request.recovery_address_id,
                      request.generation,
                      request.recovery_intent_id,
                      request.secret_reference,
                      request.secret_digest,
                      request.destination_reference,
                      request.proof_expires_at,
                      request.attempt_count,
                      request.claim_token;
        END
        $$;


ALTER FUNCTION request_auth.claim_native_recovery_delivery_requests(p_limit integer, p_lease_seconds integer) OWNER TO request_engine_schema_owner;

--
-- Name: complete_native_recovery(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.complete_native_recovery(p_native_identity_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_state text;
            v_epoch bigint;
            v_method text;
        BEGIN
            IF p_native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.native_identities AS identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE identity.id = p_native_identity_id
               AND identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT state, recovery_epoch, last_recovery_method
              INTO v_state, v_epoch, v_method
              FROM request_engine.native_identity_recovery_state
             WHERE native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_state = 'normal' THEN
                RETURN true;
            END IF;

            PERFORM 1
              FROM request_engine.webauthn_credentials AS credential
             WHERE credential.native_identity_id = p_native_identity_id
               AND credential.status = 'active';
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_identity_recovery_state
               SET state = 'normal',
                   revision = revision + 1,
                   completed_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id;

            INSERT INTO request_engine.native_identity_recovery_facts (
                native_identity_id,
                event_kind,
                recovery_epoch,
                recovery_method,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                'recovery_completed',
                v_epoch,
                v_method,
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.complete_native_recovery(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: complete_native_recovery_delivery_request(uuid, uuid, text, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.complete_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_row record;
        BEGIN
            IF p_request_id IS NULL
               OR p_claim_token IS NULL
               OR p_outcome NOT IN ('delivered', 'unknown', 'failed')
               OR (
                   p_error_class IS NOT NULL
                   AND length(btrim(p_error_class)) NOT BETWEEN 1 AND 80
               )
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = p_outcome,
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = CASE
                       WHEN p_outcome = 'delivered' THEN NULL
                       ELSE btrim(p_error_class)
                   END,
                   delivered_at = CASE
                       WHEN p_outcome = 'delivered' THEN clock_timestamp()
                       ELSE request.delivered_at
                   END,
                   updated_at = clock_timestamp()
             WHERE request.id = p_request_id
               AND request.claim_token = p_claim_token
               AND request.status = 'sending'
            RETURNING request.native_identity_id,
                      request.recovery_address_id,
                      request.generation,
                      request.recovery_intent_id
                 INTO v_row;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            IF p_outcome = 'failed' AND v_row.recovery_intent_id IS NOT NULL THEN
                UPDATE request_engine.native_recovery_intents AS intent
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE intent.id = v_row.recovery_intent_id
                   AND intent.status = 'pending';
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_facts (
                request_id,
                native_identity_id,
                recovery_address_id,
                generation,
                event_kind,
                error_class
            ) VALUES (
                p_request_id,
                v_row.native_identity_id,
                v_row.recovery_address_id,
                v_row.generation,
                CASE p_outcome
                    WHEN 'delivered' THEN 'delivered'
                    WHEN 'unknown' THEN 'delivery_unknown'
                    ELSE 'delivery_failed'
                END,
                CASE WHEN p_outcome = 'delivered' THEN NULL ELSE btrim(p_error_class) END
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.complete_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) OWNER TO request_engine_schema_owner;

--
-- Name: consume_native_recovery_intent(uuid, bytea, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.consume_native_recovery_intent(p_recovery_id uuid, p_token_digest bytea, p_new_credential_id uuid, p_new_verifier text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_native_identity_id uuid;
            v_identity_status text;
            v_case_id uuid;
            v_case_revision_before bigint;
            v_case_revision_after bigint;
            v_recovery_epoch bigint;
        BEGIN
            -- Preserve the canonical authority -> identity -> intent lock order.
            -- The initial intent lookup is advisory and is revalidated after
            -- acquiring the authority and identity locks.
            SELECT intent.native_identity_id
              INTO v_native_identity_id
              FROM request_engine.native_recovery_intents AS intent
             WHERE intent.id = p_recovery_id
               AND intent.token_digest = p_token_digest
               AND intent.status = 'pending'
               AND intent.expires_at > clock_timestamp();
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_native_identity_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.native_recovery_intents AS intent
             WHERE intent.id = p_recovery_id
               AND intent.native_identity_id = v_native_identity_id
               AND intent.token_digest = p_token_digest
               AND intent.status = 'pending'
               AND intent.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   rotated_at = clock_timestamp(),
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password'
               AND status = 'active';

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_new_credential_id, v_native_identity_id, p_new_verifier
            );

            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;

            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'credential_recovery'
             WHERE native_identity_id = v_native_identity_id
               AND status = 'active';

            UPDATE request_engine.native_recovery_intents
               SET status = 'consumed',
                   consumed_at = clock_timestamp()
             WHERE id = p_recovery_id;

            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND id <> p_recovery_id
               AND status = 'pending';

            -- Preserve governed recovery linkage from migration 0045. A proof
            -- issued from a recovery case must consume that case atomically.
            UPDATE request_engine.identity_recovery_cases
               SET status = 'consumed',
                   consumed_at = clock_timestamp(),
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE recovery_intent_id = p_recovery_id
               AND status = 'issued'
            RETURNING id, revision - 1, revision
                 INTO v_case_id, v_case_revision_before, v_case_revision_after;
            IF FOUND THEN
                INSERT INTO request_engine.platform_identity_recovery_facts (
                    id,
                    case_id,
                    action,
                    actor_principal_id,
                    actor_authentication_method,
                    reason_code,
                    external_case_reference,
                    revision_before,
                    revision_after,
                    correlation_id,
                    capability_key,
                    idempotency_key_digest,
                    intent_digest
                ) VALUES (
                    uuidv7(),
                    v_case_id,
                    'consume',
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    v_case_revision_before,
                    v_case_revision_after,
                    NULL,
                    'platform.identity.recovery_consume',
                    NULL,
                    NULL
                );
            END IF;

            -- New P6 posture is additive to the established consumption
            -- semantics: every successful recovery enters a restricted state
            -- until a strong authenticator explicitly completes recovery.
            INSERT INTO request_engine.native_identity_recovery_state (
                native_identity_id,
                state,
                recovery_epoch,
                revision,
                last_recovered_at,
                last_recovery_method,
                completed_at
            ) VALUES (
                v_native_identity_id,
                'recovery_restricted',
                1,
                1,
                clock_timestamp(),
                'delivered_recovery_proof',
                NULL
            )
            ON CONFLICT (native_identity_id) DO UPDATE
               SET state = 'recovery_restricted',
                   recovery_epoch =
                       request_engine.native_identity_recovery_state.recovery_epoch + 1,
                   revision =
                       request_engine.native_identity_recovery_state.revision + 1,
                   last_recovered_at = clock_timestamp(),
                   last_recovery_method = 'delivered_recovery_proof',
                   completed_at = NULL
            RETURNING recovery_epoch INTO v_recovery_epoch;

            INSERT INTO request_engine.native_identity_recovery_facts (
                native_identity_id,
                event_kind,
                recovery_epoch,
                recovery_method,
                correlation_id
            ) VALUES (
                v_native_identity_id,
                'recovery_started',
                v_recovery_epoch,
                'delivered_recovery_proof',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN v_native_identity_id;
        END
        $$;


ALTER FUNCTION request_auth.consume_native_recovery_intent(p_recovery_id uuid, p_token_digest bytea, p_new_credential_id uuid, p_new_verifier text) OWNER TO request_engine_schema_owner;

--
-- Name: consume_recovery_code(bytea); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.consume_recovery_code(p_code_digest bytea) RETURNS TABLE(native_identity_id uuid, set_id uuid, code_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_code_id uuid;
            v_set_id uuid;
            v_identity_id uuid;
            v_identity_status text;
        BEGIN
            IF p_code_digest IS NULL OR octet_length(p_code_digest) <> 32 THEN
                RETURN;
            END IF;

            SELECT code.id, code.set_id, code_set.native_identity_id
              INTO v_code_id, v_set_id, v_identity_id
              FROM request_engine.recovery_codes AS code
              JOIN request_engine.recovery_code_sets AS code_set
                ON code_set.id = code.set_id
             WHERE code.code_digest = p_code_digest
               AND code.used_at IS NULL
               AND code_set.status = 'active'
               AND code_set.native_identity_id IS NOT NULL
             FOR UPDATE OF code, code_set;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_identity_id;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN;
            END IF;

            UPDATE request_engine.recovery_codes
               SET used_at = clock_timestamp()
             WHERE id = v_code_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, code_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'code_consumed', v_set_id, v_identity_id, v_code_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.consume',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_identity_id, v_set_id, v_code_id;
        END
        $$;


ALTER FUNCTION request_auth.consume_recovery_code(p_code_digest bytea) OWNER TO request_engine_schema_owner;

--
-- Name: consume_recovery_code_and_rotate_password(bytea, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.consume_recovery_code_and_rotate_password(p_code_digest bytea, p_new_credential_id uuid, p_new_verifier text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_code_id uuid;
            v_set_id uuid;
            v_native_identity_id uuid;
            v_authority_id uuid;
            v_identity_status text;
            v_authority_status text;
            v_recovery_epoch bigint;
        BEGIN
            IF p_code_digest IS NULL
               OR octet_length(p_code_digest) <> 32
               OR p_new_credential_id IS NULL
               OR p_new_verifier IS NULL
               OR length(p_new_verifier) <= 32
               OR NOT (
                    p_new_verifier LIKE 'scrypt$%'
                    OR p_new_verifier LIKE '$argon2id$%'
               )
            THEN
                RETURN NULL;
            END IF;

            SELECT code.id, code_set.id, code_set.native_identity_id
              INTO v_code_id, v_set_id, v_native_identity_id
              FROM request_engine.recovery_codes AS code
              JOIN request_engine.recovery_code_sets AS code_set
                ON code_set.id = code.set_id
             WHERE code.code_digest = p_code_digest
               AND code.used_at IS NULL
               AND code_set.status = 'active'
               AND code_set.native_identity_id IS NOT NULL
             FOR UPDATE OF code, code_set;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT identity.identity_authority_id
              INTO v_authority_id
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            SELECT authority.status
              INTO v_authority_status
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = v_authority_id
               AND authority.kind = 'native'
             FOR UPDATE;
            IF NOT FOUND OR v_authority_status <> 'active' THEN
                RETURN NULL;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_native_identity_id
               AND identity.identity_authority_id = v_authority_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.native_credentials AS credential
             WHERE credential.native_identity_id = v_native_identity_id
               AND credential.kind = 'password'
               AND credential.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            UPDATE request_engine.recovery_codes
               SET used_at = clock_timestamp()
             WHERE id = v_code_id;

            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   rotated_at = clock_timestamp(),
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND kind = 'password'
               AND status = 'active';

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_new_credential_id, v_native_identity_id, p_new_verifier
            );

            UPDATE request_engine.native_identities
               SET session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_native_identity_id;

            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'recovery_code_password_reset'
             WHERE native_identity_id = v_native_identity_id
               AND status = 'active';

            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = v_native_identity_id
               AND status = 'pending';

            INSERT INTO request_engine.native_identity_recovery_state (
                native_identity_id,
                state,
                recovery_epoch,
                revision,
                last_recovered_at,
                last_recovery_method,
                completed_at
            ) VALUES (
                v_native_identity_id,
                'recovery_restricted',
                1,
                1,
                clock_timestamp(),
                'offline_recovery_code',
                NULL
            )
            ON CONFLICT (native_identity_id) DO UPDATE
               SET state = 'recovery_restricted',
                   recovery_epoch =
                       request_engine.native_identity_recovery_state.recovery_epoch + 1,
                   revision =
                       request_engine.native_identity_recovery_state.revision + 1,
                   last_recovered_at = clock_timestamp(),
                   last_recovery_method = 'offline_recovery_code',
                   completed_at = NULL
            RETURNING recovery_epoch INTO v_recovery_epoch;

            INSERT INTO request_engine.native_identity_recovery_facts (
                native_identity_id,
                event_kind,
                recovery_epoch,
                recovery_method,
                correlation_id
            ) VALUES (
                v_native_identity_id,
                'recovery_started',
                v_recovery_epoch,
                'offline_recovery_code',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, code_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'code_consumed', v_set_id, v_native_identity_id, v_code_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.password_reset',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN v_native_identity_id;
        END
        $_$;


ALTER FUNCTION request_auth.consume_recovery_code_and_rotate_password(p_code_digest bytea, p_new_credential_id uuid, p_new_verifier text) OWNER TO request_engine_schema_owner;

--
-- Name: create_native_identity(uuid, uuid, text, uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.create_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_verifier text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_identity_id uuid;
        BEGIN
            PERFORM 1
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
               AND status = 'active' AND kind = 'native'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, p_identity_authority_id, p_login_handle
            )
            ON CONFLICT (identity_authority_id, login_handle) DO NOTHING
            RETURNING id INTO v_identity_id;
            IF v_identity_id IS NULL THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_verifier
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.create_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_verifier text) OWNER TO request_engine_schema_owner;

--
-- Name: create_native_recovery_intent(uuid, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.create_native_recovery_intent(p_native_identity_id uuid, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_status text;
        BEGIN
            -- Authority is locked before identity; SHARE conflicts with status UPDATE.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT status INTO v_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_status <> 'active' OR p_expires_at <= clock_timestamp() THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id
               AND status = 'pending';
            INSERT INTO request_engine.native_recovery_intents (
                id,
                native_identity_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_recovery_id,
                p_native_identity_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.create_native_recovery_intent(p_native_identity_id uuid, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: create_native_recovery_intent_for_verified_address(uuid, text, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.create_native_recovery_intent_for_verified_address(p_identity_authority_id uuid, p_login_handle text, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) RETURNS TABLE(native_identity_id uuid, recovery_address_id uuid, destination_address text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_identity_id uuid;
            v_address record;
        BEGIN
            IF p_identity_authority_id IS NULL
               OR p_login_handle IS NULL
               OR p_recovery_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '30 minutes'
            THEN
                RETURN;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = p_identity_authority_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT identity.id
              INTO v_identity_id
              FROM request_engine.native_identities AS identity
             WHERE identity.identity_authority_id = p_identity_authority_id
               AND identity.login_handle = p_login_handle
               AND identity.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT address.id, address.normalized_address
              INTO v_address
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = v_identity_id
               AND address.kind = 'email'
               AND address.status = 'verified'
             ORDER BY address.verified_at DESC, address.id
             LIMIT 1
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN;
            END IF;

            -- Durable per-account throttling. Returning no row is deliberate:
            -- callers receive the same public response as an unknown account.
            PERFORM 1
              FROM request_engine.native_recovery_address_facts AS fact
             WHERE fact.native_identity_id = v_identity_id
               AND fact.recovery_address_id = v_address.id
               AND fact.event_kind = 'recovery_requested'
               AND fact.created_at > clock_timestamp() - interval '1 minute'
             LIMIT 1;
            IF FOUND THEN
                RETURN;
            END IF;

            UPDATE request_engine.native_recovery_intents AS intent
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE intent.native_identity_id = v_identity_id
               AND intent.status = 'pending';

            INSERT INTO request_engine.native_recovery_intents (
                id,
                native_identity_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_recovery_id,
                v_identity_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address.id,
                'recovery_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT
                v_identity_id,
                v_address.id,
                v_address.normalized_address;
        END
        $_$;


ALTER FUNCTION request_auth.create_native_recovery_intent_for_verified_address(p_identity_authority_id uuid, p_login_handle text, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: create_native_session(uuid, uuid, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.create_native_session(p_native_identity_id uuid, p_credential_id uuid, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_epoch bigint;
            v_identity_status text;
            v_credential_status text;
        BEGIN
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT session_epoch, status
              INTO v_epoch, v_identity_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT status
              INTO v_credential_status
              FROM request_engine.native_credentials
             WHERE id = p_credential_id
               AND native_identity_id = p_native_identity_id
               AND kind = 'password'
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active' THEN
                RETURN false;
            END IF;
            IF p_expires_at <= clock_timestamp() THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_sessions (
                id, native_identity_id, password_credential_id, token_digest,
                token_fingerprint, session_epoch, expires_at
            ) VALUES (
                p_session_id, p_native_identity_id, p_credential_id, p_token_digest,
                p_token_fingerprint, v_epoch, p_expires_at
            );
            UPDATE request_engine.native_credentials
               SET last_used_at = clock_timestamp()
             WHERE id = p_credential_id;
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.create_native_session(p_native_identity_id uuid, p_credential_id uuid, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: create_recovery_code_set(uuid, uuid, uuid, bytea[]); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.create_recovery_code_set(p_set_id uuid, p_native_identity_id uuid, p_setup_session_id uuid, p_code_digests bytea[]) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_scope_count integer;
            v_identity_status text;
            v_setup_status text;
            v_version integer;
        BEGIN
            v_scope_count := (p_native_identity_id IS NOT NULL)::int
                + (p_setup_session_id IS NOT NULL)::int;
            IF p_set_id IS NULL
               OR v_scope_count <> 1
               OR p_code_digests IS NULL
               OR cardinality(p_code_digests) NOT BETWEEN 1 AND 50
               OR EXISTS (
                   SELECT 1 FROM unnest(p_code_digests) AS digest
                    WHERE digest IS NULL OR octet_length(digest) <> 32
               )
            THEN
                RETURN false;
            END IF;

            IF p_native_identity_id IS NOT NULL THEN
                PERFORM 1
                  FROM request_engine.identity_authorities AS authority
                  JOIN request_engine.native_identities AS native_identity
                    ON native_identity.identity_authority_id = authority.id
                 WHERE native_identity.id = p_native_identity_id
                   AND authority.kind = 'native' AND authority.status = 'active'
                 FOR SHARE OF authority;
                IF NOT FOUND THEN RETURN false; END IF;

                SELECT identity.status INTO v_identity_status
                  FROM request_engine.native_identities AS identity
                 WHERE identity.id = p_native_identity_id
                 FOR UPDATE;
                IF NOT FOUND OR v_identity_status <> 'active' THEN
                    RETURN false;
                END IF;

                SELECT coalesce(max(code_set.version), 0) + 1 INTO v_version
                  FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.native_identity_id = p_native_identity_id;

                UPDATE request_engine.recovery_code_sets
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE native_identity_id = p_native_identity_id
                   AND status = 'active';
            ELSE
                SELECT session.status INTO v_setup_status
                  FROM request_engine.setup_sessions AS session
                 WHERE session.id = p_setup_session_id
                 FOR UPDATE;
                IF NOT FOUND OR v_setup_status <> 'pending' THEN
                    RETURN false;
                END IF;

                SELECT coalesce(max(code_set.version), 0) + 1 INTO v_version
                  FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.setup_session_id = p_setup_session_id;

                UPDATE request_engine.recovery_code_sets
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE setup_session_id = p_setup_session_id
                   AND status = 'active';
            END IF;

            INSERT INTO request_engine.recovery_code_sets (
                id, native_identity_id, setup_session_id, version
            ) VALUES (
                p_set_id, p_native_identity_id, p_setup_session_id, v_version
            );

            INSERT INTO request_engine.recovery_codes (set_id, code_digest)
            SELECT p_set_id, digest FROM unnest(p_code_digests) AS digest;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_created', p_set_id, p_native_identity_id, p_setup_session_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.manage',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.create_recovery_code_set(p_set_id uuid, p_native_identity_id uuid, p_setup_session_id uuid, p_code_digests bytea[]) OWNER TO request_engine_schema_owner;

--
-- Name: create_webauthn_challenge(uuid, text, uuid, uuid, uuid, bytea, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_scope_count integer;
        BEGIN
            v_scope_count := (p_native_identity_id IS NOT NULL)::int
                + (p_session_id IS NOT NULL)::int
                + (p_setup_session_id IS NOT NULL)::int;
            IF p_challenge_id IS NULL
               OR p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_purpose NOT IN ('registration', 'authentication', 'step_up')
               OR v_scope_count <> 1
               OR p_expires_at <= clock_timestamp()
            THEN
                RETURN false;
            END IF;

            -- Serialize challenge creation per scope so two concurrent begins
            -- cannot both leave a live challenge.
            PERFORM pg_advisory_xact_lock(
                hashtextextended(
                    coalesce(p_purpose, '') || '|'
                    || coalesce(p_native_identity_id::text, '') || '|'
                    || coalesce(p_session_id::text, '') || '|'
                    || coalesce(p_setup_session_id::text, ''),
                    0
                )
            );

            UPDATE request_engine.webauthn_challenges
               SET status = 'expired'
             WHERE status = 'pending'
               AND purpose = p_purpose
               AND native_identity_id IS NOT DISTINCT FROM p_native_identity_id
               AND session_id IS NOT DISTINCT FROM p_session_id
               AND setup_session_id IS NOT DISTINCT FROM p_setup_session_id;

            INSERT INTO request_engine.webauthn_challenges (
                id, purpose, native_identity_id, session_id, setup_session_id,
                challenge_digest, expires_at
            ) VALUES (
                p_challenge_id, p_purpose, p_native_identity_id, p_session_id,
                p_setup_session_id, p_challenge_digest, p_expires_at
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: disable_native_identity(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.disable_native_identity(p_native_identity_id uuid, p_reason text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            UPDATE request_engine.native_identities
               SET status = 'disabled',
                   session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp(),
                   disabled_at = clock_timestamp()
             WHERE id = p_native_identity_id
               AND status = 'active';
            IF NOT FOUND THEN
                RETURN false;
            END IF;
            UPDATE request_engine.native_credentials
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id
               AND status = 'active';
            UPDATE request_engine.native_sessions
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = p_reason
             WHERE native_identity_id = p_native_identity_id
               AND status = 'active';
            UPDATE request_engine.native_recovery_intents
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE native_identity_id = p_native_identity_id
               AND status = 'pending';
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.disable_native_identity(p_native_identity_id uuid, p_reason text) OWNER TO request_engine_schema_owner;

--
-- Name: finalize_setup_webauthn_registration(bytea, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.finalize_setup_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_setup_session_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_setup_status text;
            v_instance_state text;
            v_expires_at timestamptz;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_credential_id_bytes IS NULL
               OR octet_length(p_credential_id_bytes) NOT BETWEEN 16 AND 1023
               OR p_public_key IS NULL
               OR octet_length(p_public_key) = 0
               OR p_sign_count < 0
               OR p_aaguid IS NULL
               OR p_aaguid !~ '^[0-9a-f]{32}$'
               OR p_setup_session_id IS NULL
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'registration'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            -- The presented SetupSession must own the challenge. A valid bearer
            -- for a different concurrent ceremony is never sufficient.
            IF NOT FOUND
               OR v_challenge.setup_session_id IS NULL
               OR v_challenge.setup_session_id <> p_setup_session_id
            THEN
                RETURN false;
            END IF;

            SELECT session.status, session.expires_at, instance.state
              INTO v_setup_status, v_expires_at, v_instance_state
              FROM request_engine.setup_sessions AS session
              JOIN request_engine.platform_instance AS instance
                ON instance.id = session.instance_id
             WHERE session.id = v_challenge.setup_session_id
             FOR UPDATE OF session;
            IF NOT FOUND
               OR v_setup_status <> 'pending'
               OR v_expires_at <= clock_timestamp()
               OR v_instance_state <> 'unclaimed'
            THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.setup_pending_webauthn_credential (
                id, setup_session_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            ) VALUES (
                p_credential_row_id, v_challenge.setup_session_id, p_credential_id_bytes,
                p_public_key, p_sign_count, p_aaguid, p_backup_eligible,
                p_backup_state, p_user_verified
            )
            ON CONFLICT (credential_id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $_$;


ALTER FUNCTION request_auth.finalize_setup_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_setup_session_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: finalize_webauthn_authentication(bytea, uuid, uuid, bigint, boolean, boolean, boolean, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.finalize_webauthn_authentication(p_challenge_digest bytea, p_credential_row_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_epoch bigint;
            v_identity_status text;
            v_credential_status text;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_sign_count < 0
               OR p_session_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'authentication'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND
               OR v_challenge.native_identity_id IS DISTINCT FROM p_native_identity_id
            THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT session_epoch, status
              INTO v_epoch, v_identity_status
              FROM request_engine.native_identities
             WHERE id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT status INTO v_credential_status
              FROM request_engine.webauthn_credentials
             WHERE id = p_credential_row_id
               AND native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active' THEN
                RETURN false;
            END IF;
            IF p_expires_at <= clock_timestamp() THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_credentials
               SET sign_count = GREATEST(sign_count, p_sign_count),
                   last_used_at = clock_timestamp(),
                   backup_state = p_backup_state,
                   user_verified = user_verified OR p_user_verified,
                   last_regression_at = CASE
                       WHEN NOT p_backup_eligible
                            AND p_sign_count > 0
                            AND sign_count > 0
                            AND p_sign_count < sign_count
                       THEN clock_timestamp()
                       ELSE last_regression_at
                   END
             WHERE id = p_credential_row_id;

            INSERT INTO request_engine.native_sessions (
                id, native_identity_id, password_credential_id,
                webauthn_credential_id, token_digest, token_fingerprint,
                session_epoch, expires_at, authentication_methods,
                authentication_assurance, user_verified, recovery_derived
            ) VALUES (
                p_session_id, p_native_identity_id, NULL, p_credential_row_id,
                p_token_digest, p_token_fingerprint, v_epoch, p_expires_at,
                ARRAY['webauthn']::text[],
                request_engine.derive_authentication_assurance(
                    ARRAY['webauthn']::text[], p_user_verified, false
                ),
                p_user_verified, false
            );

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $_$;


ALTER FUNCTION request_auth.finalize_webauthn_authentication(p_challenge_digest bytea, p_credential_row_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: finalize_webauthn_registration(bytea, uuid, bytea, bytea, bigint, text, boolean, boolean, boolean); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_identity_status text;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_credential_id_bytes IS NULL
               OR octet_length(p_credential_id_bytes) NOT BETWEEN 16 AND 1023
               OR p_public_key IS NULL
               OR octet_length(p_public_key) = 0
               OR p_sign_count < 0
               OR p_aaguid IS NULL
               OR p_aaguid !~ '^[0-9a-f]{32}$'
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'registration'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND OR v_challenge.native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            -- A suspended native authority must not accept new credentials.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_challenge.native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = v_challenge.native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.webauthn_credentials (
                id, native_identity_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            ) VALUES (
                p_credential_row_id, v_challenge.native_identity_id,
                p_credential_id_bytes, p_public_key, p_sign_count, p_aaguid,
                p_backup_eligible, p_backup_state, p_user_verified
            )
            ON CONFLICT (credential_id) DO NOTHING;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $_$;


ALTER FUNCTION request_auth.finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean) OWNER TO request_engine_schema_owner;

--
-- Name: finalize_webauthn_step_up(bytea, uuid, uuid, uuid, bigint, boolean, boolean); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_challenge request_engine.webauthn_challenges%ROWTYPE;
            v_session request_engine.native_sessions%ROWTYPE;
            v_credential_status text;
            v_identity_status text;
            v_identity_epoch bigint;
            v_methods text[];
            v_user_verified boolean;
        BEGIN
            IF p_challenge_digest IS NULL
               OR octet_length(p_challenge_digest) <> 32
               OR p_credential_row_id IS NULL
               OR p_session_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_sign_count < 0
            THEN
                RETURN false;
            END IF;

            SELECT challenge.* INTO v_challenge
              FROM request_engine.webauthn_challenges AS challenge
             WHERE challenge.challenge_digest = p_challenge_digest
               AND challenge.purpose = 'step_up'
               AND challenge.status = 'pending'
               AND challenge.expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND OR v_challenge.session_id IS DISTINCT FROM p_session_id THEN
                RETURN false;
            END IF;

            -- Canonical lock order: authority -> identity -> credential -> session.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
             FOR SHARE OF authority;
            IF NOT FOUND THEN RETURN false; END IF;

            SELECT identity.status, identity.session_epoch
              INTO v_identity_status, v_identity_epoch
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR SHARE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT status INTO v_credential_status
              FROM request_engine.webauthn_credentials
             WHERE id = p_credential_row_id
               AND native_identity_id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_credential_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT session.* INTO v_session
              FROM request_engine.native_sessions AS session
             WHERE session.id = p_session_id
             FOR UPDATE;
            IF NOT FOUND
               OR v_session.native_identity_id <> p_native_identity_id
               OR v_session.status <> 'active'
               OR v_session.expires_at <= clock_timestamp()
               OR v_session.session_epoch <> v_identity_epoch
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.webauthn_credentials
               SET sign_count = GREATEST(sign_count, p_sign_count),
                   last_used_at = clock_timestamp(),
                   user_verified = user_verified OR p_user_verified,
                   last_regression_at = CASE
                       WHEN NOT p_backup_eligible
                            AND p_sign_count > 0
                            AND sign_count > 0
                            AND p_sign_count < sign_count
                       THEN clock_timestamp()
                       ELSE last_regression_at
                   END
             WHERE id = p_credential_row_id;

            v_methods := CASE
                WHEN 'webauthn' = ANY(v_session.authentication_methods)
                    THEN v_session.authentication_methods
                ELSE v_session.authentication_methods || ARRAY['webauthn']::text[]
            END;
            v_user_verified := v_session.user_verified OR p_user_verified;

            UPDATE request_engine.native_sessions
               SET authentication_methods = v_methods,
                   authentication_assurance = request_engine.derive_authentication_assurance(
                       v_methods, v_user_verified, v_session.recovery_derived
                   ),
                   user_verified = v_user_verified,
                   last_authenticated_at = clock_timestamp(),
                   last_seen_at = clock_timestamp()
             WHERE id = p_session_id;

            UPDATE request_engine.webauthn_challenges
               SET status = 'consumed', consumed_at = clock_timestamp()
             WHERE id = v_challenge.id;
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean) OWNER TO request_engine_schema_owner;

--
-- Name: is_native_authority_ready(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT EXISTS (
                SELECT 1 FROM request_engine.identity_authorities
                 WHERE id = p_authority_id AND kind = 'native' AND status = 'active'
            )
        $$;


ALTER FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_credentialed_native_identity(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        BEGIN
            PERFORM 1 FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id
               AND kind = 'native' AND status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN RETURN false; END IF;

            PERFORM 1
              FROM request_engine.native_identities AS native_identity
             WHERE native_identity.id = p_native_identity_id
               AND native_identity.identity_authority_id = p_identity_authority_id
               AND native_identity.status = 'active'
             FOR SHARE OF native_identity;
            IF NOT FOUND THEN RETURN false; END IF;

            PERFORM 1 FROM request_engine.native_credentials AS credential
             WHERE credential.native_identity_id = p_native_identity_id
               AND credential.kind = 'password' AND credential.status = 'active'
             FOR SHARE OF credential;
            RETURN FOUND;
        END
        $$;


ALTER FUNCTION request_auth.lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: prepare_native_recovery_address(uuid, uuid, text, text, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) RETURNS TABLE(recovery_address_id uuid, address_status text, verification_created boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $_$
        DECLARE
            v_identity_status text;
            v_existing record;
            v_address_id uuid;
        BEGIN
            IF p_address_id IS NULL
               OR p_native_identity_id IS NULL
               OR p_kind <> 'email'
               OR p_normalized_address IS NULL
               OR length(p_normalized_address) NOT BETWEEN 3 AND 320
               OR p_normalized_address !~ '^[^[:space:]@]+@[^[:space:]@]+$'
               OR p_verification_id IS NULL
               OR p_token_digest IS NULL
               OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '30 minutes'
            THEN
                RETURN;
            END IF;

            SELECT identity.status
              INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN;
            END IF;

            SELECT address.id, address.status
              INTO v_existing
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = p_native_identity_id
               AND address.kind = p_kind
               AND address.normalized_address = p_normalized_address
               AND address.status <> 'revoked'
             FOR UPDATE;

            IF FOUND AND v_existing.status = 'verified' THEN
                RETURN QUERY SELECT v_existing.id, 'verified'::text, false;
                RETURN;
            END IF;

            IF FOUND THEN
                v_address_id := v_existing.id;
                UPDATE request_engine.native_recovery_address_verifications
                   SET status = 'revoked',
                       revoked_at = clock_timestamp()
                 WHERE recovery_address_id = v_address_id
                   AND status = 'pending';
            ELSE
                v_address_id := p_address_id;
                INSERT INTO request_engine.native_recovery_addresses (
                    id, native_identity_id, kind, normalized_address
                ) VALUES (
                    v_address_id,
                    p_native_identity_id,
                    p_kind,
                    p_normalized_address
                );
            END IF;

            INSERT INTO request_engine.native_recovery_address_verifications (
                id,
                recovery_address_id,
                token_digest,
                token_fingerprint,
                expires_at
            ) VALUES (
                p_verification_id,
                v_address_id,
                p_token_digest,
                p_token_fingerprint,
                p_expires_at
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                p_native_identity_id,
                v_address_id,
                'verification_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_address_id, 'pending'::text, true;
        END
        $_$;


ALTER FUNCTION request_auth.prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: promote_recovery_code_set(uuid, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_set request_engine.recovery_code_sets%ROWTYPE;
            v_identity_status text;
        BEGIN
            IF p_set_id IS NULL OR p_native_identity_id IS NULL THEN
                RETURN false;
            END IF;

            SELECT identity.status INTO v_identity_status
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND OR v_identity_status <> 'active' THEN
                RETURN false;
            END IF;

            SELECT code_set.* INTO v_set
              FROM request_engine.recovery_code_sets AS code_set
             WHERE code_set.id = p_set_id
             FOR UPDATE;
            IF NOT FOUND
               OR v_set.status <> 'active'
               OR v_set.setup_session_id IS NULL
            THEN
                RETURN false;
            END IF;

            UPDATE request_engine.recovery_code_sets
               SET setup_session_id = NULL,
                   native_identity_id = p_native_identity_id
             WHERE id = p_set_id;

            INSERT INTO request_engine.platform_recovery_code_facts (
                event_kind, set_id, native_identity_id, setup_session_id,
                actor_principal_id, actor_authentication_method, capability_key,
                correlation_id
            ) VALUES (
                'set_promoted', p_set_id, p_native_identity_id, v_set.setup_session_id,
                NULLIF(
                    current_setting('request_engine.authenticated_principal_id', true), ''
                )::uuid,
                NULLIF(current_setting('request_engine.authentication_method', true), ''),
                'platform.recovery_codes.manage',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: queue_native_verified_recovery(uuid, text, uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
        DECLARE
            v_identity_id uuid;
            v_address record;
        BEGIN
            IF p_identity_authority_id IS NULL
               OR p_login_handle IS NULL
               OR length(p_login_handle) NOT BETWEEN 1 AND 320
               OR p_request_id IS NULL
            THEN
                RETURN false;
            END IF;

            PERFORM 1
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = p_identity_authority_id
               AND authority.kind = 'native'
               AND authority.status = 'active'
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT identity.id
              INTO v_identity_id
              FROM request_engine.native_identities AS identity
             WHERE identity.identity_authority_id = p_identity_authority_id
               AND identity.login_handle = p_login_handle
               AND identity.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            SELECT address.id, address.normalized_address
              INTO v_address
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = v_identity_id
               AND address.kind = 'email'
               AND address.status = 'verified'
             ORDER BY address.verified_at DESC, address.id
             LIMIT 1
             FOR SHARE;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.native_recovery_delivery_requests AS request
               SET status = 'cancelled',
                   updated_at = clock_timestamp(),
                   last_error_class = 'request_expired'
             WHERE request.native_identity_id = v_identity_id
               AND request.status = 'pending'
               AND request.request_expires_at <= clock_timestamp();

            IF EXISTS (
                SELECT 1
                  FROM request_engine.native_recovery_delivery_requests AS request
                 WHERE request.native_identity_id = v_identity_id
                   AND request.status IN ('pending', 'sending')
            ) THEN
                RETURN false;
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM request_engine.native_recovery_address_facts AS fact
                 WHERE fact.native_identity_id = v_identity_id
                   AND fact.recovery_address_id = v_address.id
                   AND fact.event_kind = 'recovery_requested'
                   AND fact.created_at > clock_timestamp() - interval '1 minute'
            ) THEN
                RETURN false;
            END IF;

            INSERT INTO request_engine.native_recovery_delivery_requests (
                id,
                native_identity_id,
                recovery_address_id,
                destination_reference,
                request_expires_at
            ) VALUES (
                p_request_id,
                v_identity_id,
                v_address.id,
                v_address.normalized_address,
                clock_timestamp() + interval '30 minutes'
            );

            INSERT INTO request_engine.native_recovery_address_facts (
                native_identity_id,
                recovery_address_id,
                event_kind,
                correlation_id
            ) VALUES (
                v_identity_id,
                v_address.id,
                'recovery_requested',
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );
            RETURN true;
        END
        $$;


ALTER FUNCTION request_auth.queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_active_webauthn_identity(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text) RETURNS uuid
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT native_identity.id
              FROM request_engine.native_identities AS native_identity
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = native_identity.identity_authority_id
             WHERE native_identity.identity_authority_id = p_identity_authority_id
               AND native_identity.login_handle = p_login_handle
               AND native_identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.webauthn_credentials AS credential
                    WHERE credential.native_identity_id = native_identity.id
                      AND credential.status = 'active'
               )
        $$;


ALTER FUNCTION request_auth.read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_credential_verifier(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_credential_verifier(p_credential_id uuid) RETURNS text
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT credential.verifier
              FROM request_engine.native_credentials AS credential
              JOIN request_engine.native_identities AS identity
                ON identity.id = credential.native_identity_id
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = identity.identity_authority_id
             WHERE credential.id = p_credential_id
               AND credential.kind = 'password'
               AND credential.status = 'active'
               AND identity.status = 'active'
               AND authority.kind = 'native'
               AND authority.status = 'active'
        $$;


ALTER FUNCTION request_auth.read_native_credential_verifier(p_credential_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_password_credential(uuid, text); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_password_credential(p_identity_authority_id uuid, p_login_handle text) RETURNS TABLE(native_identity_id uuid, credential_id uuid, verifier text, identity_status text, credential_status text, session_epoch bigint, identity_revision bigint, credential_revision bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT i.id,
                   c.id,
                   c.verifier,
                   i.status,
                   c.status,
                   i.session_epoch,
                   i.revision,
                   c.revision
              FROM request_engine.native_identities AS i
              JOIN request_engine.native_credentials AS c
                ON c.native_identity_id = i.id
               AND c.kind = 'password'
               AND c.status = 'active'
              JOIN request_engine.identity_authorities AS authority
                ON authority.id = i.identity_authority_id
               AND authority.kind = 'native' AND authority.status = 'active'
             WHERE i.identity_authority_id = p_identity_authority_id
               AND i.login_handle = p_login_handle
        $$;


ALTER FUNCTION request_auth.read_native_password_credential(p_identity_authority_id uuid, p_login_handle text) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_recovery_addresses(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_recovery_addresses(p_native_identity_id uuid) RETURNS TABLE(recovery_address_id uuid, kind text, normalized_address text, status text, revision bigint, verified_at timestamp with time zone, created_at timestamp with time zone)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT address.id,
                   address.kind,
                   address.normalized_address,
                   address.status,
                   address.revision,
                   address.verified_at,
                   address.created_at
              FROM request_engine.native_recovery_addresses AS address
             WHERE address.native_identity_id = p_native_identity_id
               AND address.status <> 'revoked'
             ORDER BY address.created_at, address.id
        $$;


ALTER FUNCTION request_auth.read_native_recovery_addresses(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_recovery_readiness(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_recovery_readiness(p_native_identity_id uuid) RETURNS TABLE(recovery_state text, recovery_epoch bigint, last_recovered_at timestamp with time zone, last_recovery_method text, completed_at timestamp with time zone, active_code_set boolean, remaining_codes bigint, active_webauthn_credentials bigint)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine'
    AS $$
            SELECT coalesce(rs.state, 'normal'),
                   coalesce(rs.recovery_epoch, 0),
                   rs.last_recovered_at,
                   rs.last_recovery_method,
                   rs.completed_at,
                   EXISTS (
                       SELECT 1
                         FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.native_identity_id = p_native_identity_id
                          AND code_set.status = 'active'
                   ),
                   (
                       SELECT count(*)
                         FROM request_engine.recovery_codes AS code
                         JOIN request_engine.recovery_code_sets AS code_set
                           ON code_set.id = code.set_id
                        WHERE code_set.native_identity_id = p_native_identity_id
                          AND code_set.status = 'active'
                          AND code.used_at IS NULL
                   ),
                   (
                       SELECT count(*)
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = p_native_identity_id
                          AND credential.status = 'active'
                   )
              FROM request_engine.native_identities AS identity
              LEFT JOIN request_engine.native_identity_recovery_state AS rs
                ON rs.native_identity_id = identity.id
             WHERE identity.id = p_native_identity_id
               AND identity.status = 'active'
        $$;


ALTER FUNCTION request_auth.read_native_recovery_readiness(p_native_identity_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_native_session(uuid); Type: FUNCTION; Schema: request_auth; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_auth.read_native_session(p_session_id uuid) RETURNS TABLE(session_id uuid, native_identity_id uuid, identity_authority_id uuid, password_credential_id uuid, password_credential_status text, webauthn_credential_id uuid, webauthn_credential_status text, token_digest bytea, session_epoch bigint, current_session_epoch bigint, session_status text, identity_status text, authority_status text, authentication_methods text[], authentication_assurance text, user_verified boolean, recovery_derived boolean, recovery_restricted boolean, expires_at timestamp with time zone, created_at timestamp with time zone, last_seen_at timestamp with time zone, last_authenticated_at timestamp with time zone)
