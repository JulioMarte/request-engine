BEGIN;
SET ROLE request_engine_schema_owner;
SET search_path = request_engine, request_admin, pg_catalog;

CREATE FUNCTION request_engine.current_authenticated_principal_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('request_engine.authenticated_principal_id', true), '')::uuid
$function$;

CREATE FUNCTION request_engine.current_correlation_id()
RETURNS uuid
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
$function$;

CREATE FUNCTION request_engine.require_trusted_actor_context(p_organization_id uuid)
RETURNS uuid
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
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
$function$;

DROP FUNCTION request_admin.replay_dead_scheduled_action(uuid, uuid, uuid, integer, text);
DROP FUNCTION request_admin.replay_dead_outbox_message(uuid, uuid, uuid, integer, text);
DROP FUNCTION request_admin.replay_provider_event(uuid, uuid, uuid, integer, text);

CREATE FUNCTION request_admin.replay_dead_scheduled_action(
    p_organization_id uuid,
    p_action_id uuid,
    p_additional_attempts integer,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
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
$function$;

CREATE FUNCTION request_admin.replay_dead_outbox_message(
    p_organization_id uuid,
    p_message_id uuid,
    p_additional_attempts integer,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
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
$function$;

CREATE FUNCTION request_admin.replay_provider_event(
    p_organization_id uuid,
    p_provider_event_row_id uuid,
    p_additional_attempts integer,
    p_reason text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, request_engine
AS $function$
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
$function$;

RESET ROLE;

REVOKE ALL ON FUNCTION request_engine.current_authenticated_principal_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.current_correlation_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION request_engine.require_trusted_actor_context(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.replay_dead_scheduled_action(uuid, uuid, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.replay_dead_outbox_message(uuid, uuid, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION request_admin.replay_provider_event(uuid, uuid, integer, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION request_engine.current_authenticated_principal_id()
    TO request_engine_app, request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_engine.current_correlation_id()
    TO request_engine_app, request_engine_worker, request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.replay_dead_scheduled_action(uuid, uuid, integer, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.replay_dead_outbox_message(uuid, uuid, integer, text)
    TO request_engine_admin;
GRANT EXECUTE ON FUNCTION request_admin.replay_provider_event(uuid, uuid, integer, text)
    TO request_engine_admin;

COMMIT;
