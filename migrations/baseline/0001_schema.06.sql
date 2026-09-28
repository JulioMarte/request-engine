               AND principal.id <> p_excluded_principal_id
               AND request_platform.principal_is_effective_platform_controller(
                       principal.id)
             ORDER BY principal.id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Platform must retain an effective controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_platform.assert_other_platform_controller(p_excluded_principal_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: assert_other_platform_owner(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.assert_other_platform_owner(p_excluded_principal_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.id
              INTO v_candidate
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
               AND principal.id <> p_excluded_principal_id
               AND request_platform.principal_is_effective_platform_owner(principal.id)
             ORDER BY principal.id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Platform must retain an effective Platform Owner'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_platform.assert_other_platform_owner(p_excluded_principal_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: assert_platform_configuration_actor(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.assert_platform_configuration_actor(p_capability text) RETURNS TABLE(actor_id uuid, actor_method text, correlation_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
        BEGIN
            IF p_capability NOT IN (
                'platform.configuration.read',
                'platform.configuration.stage',
                'platform.configuration.validate',
                'platform.configuration.activate',
                'platform.configuration.disable',
                'platform.secret.write',
                'platform.secret.rotate',
                'platform.secret.revoke',
                'platform.provider.test',
                'platform.readiness.read'
            ) THEN
                RAISE EXCEPTION 'Unknown platform configuration capability'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(
                    current_setting(
                        'request_engine.authenticated_principal_id',
                        true
                    ),
                    ''
                )::uuid;
                v_actor_revision := NULLIF(
                    current_setting(
                        'request_engine.authority_revision',
                        true
                    ),
                    ''
                )::bigint;
                v_actor_method := NULLIF(
                    current_setting(
                        'request_engine.authentication_method',
                        true
                    ),
                    ''
                );
                v_correlation_id := NULLIF(
                    current_setting(
                        'request_engine.correlation_id',
                        true
                    ),
                    ''
                )::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;

            IF v_actor_id IS NULL
               OR v_actor_revision IS NULL
               OR v_actor_method IS NULL
            THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT
                principal.principal_kind,
                principal.active,
                principal.authority_revision
              INTO
                v_actor_kind,
                v_actor_active,
                v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';

            IF NOT FOUND
               OR NOT v_actor_active
               OR v_actor_kind <> 'human'
            THEN
                RAISE EXCEPTION
                    'Platform configuration requires an active HUMAN principal'
                    USING ERRCODE = '42501';
            END IF;

            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.principal_plane = 'platform'
                   AND grant_row.authority_plane = 'platform'
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION
                    'Current Platform Principal lacks configuration authority'
                    USING ERRCODE = '42501';
            END IF;

            RETURN QUERY
            SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $$;


ALTER FUNCTION request_platform.assert_platform_configuration_actor(p_capability text) OWNER TO request_platform_control_definer;

--
-- Name: assert_platform_has_controller(); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.assert_platform_has_controller() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            SELECT principal.id
              INTO v_candidate
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
               AND request_platform.principal_is_effective_platform_controller(
                       principal.id)
             ORDER BY principal.id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Platform must retain an effective controller'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;


ALTER FUNCTION request_platform.assert_platform_has_controller() OWNER TO request_platform_control_definer;

--
-- Name: assert_platform_identity_actor(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.assert_platform_identity_actor(p_capability text) RETURNS TABLE(actor_id uuid, actor_method text, correlation_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
        BEGIN
            IF p_capability NOT IN (
                'platform.identity.recover', 'platform.identity.recovery_approve'
            ) THEN
                RAISE EXCEPTION 'Unknown platform identity recovery capability'
                    USING ERRCODE = '22023';
            END IF;
            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_actor_method := NULLIF(current_setting(
                    'request_engine.authentication_method', true
                ), '');
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot administer identity recovery'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS actor_grant
                 WHERE actor_grant.principal_id = v_actor_id
                   AND actor_grant.principal_plane = 'platform'
                   AND actor_grant.authority_plane = 'platform'
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks identity recovery authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN QUERY SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $$;


ALTER FUNCTION request_platform.assert_platform_identity_actor(p_capability text) OWNER TO request_platform_control_definer;

--
-- Name: assert_platform_owner_actor(text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.assert_platform_owner_actor(p_capability text) RETURNS TABLE(actor_id uuid, actor_method text, correlation_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_correlation_id uuid;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
        BEGIN
            IF p_capability NOT IN (
                'platform.owner.provision',
                'platform.owner.manage_lifecycle'
            ) THEN
                RAISE EXCEPTION 'Unknown Platform Owner capability'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_actor_method := NULLIF(current_setting(
                    'request_engine.authentication_method', true
                ), '');
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;

            IF v_actor_id IS NULL OR v_actor_revision IS NULL OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot administer owners'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS actor_grant
                 WHERE actor_grant.principal_id = v_actor_id
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = p_capability
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks Platform Owner authority'
                    USING ERRCODE = '42501';
            END IF;

            RETURN QUERY SELECT v_actor_id, v_actor_method, v_correlation_id;
        END
        $$;


ALTER FUNCTION request_platform.assert_platform_owner_actor(p_capability text) OWNER TO request_platform_control_definer;

--
-- Name: claim_identity_recovery_delivery_tickets(integer, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.claim_identity_recovery_delivery_tickets(p_limit integer, p_lease_seconds integer) RETURNS TABLE(ticket_id uuid, case_id uuid, generation integer, secret_reference text, secret_digest text, destination_reference text, expires_at timestamp with time zone, attempt_count integer, claim_token uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_terminal record;
            v_revision_before bigint;
            v_revision_after bigint;
        BEGIN
            IF p_limit IS NULL OR p_limit < 1 OR p_limit > 100 THEN
                RAISE EXCEPTION 'Delivery ticket claim limit must be between 1 and 100'
                    USING ERRCODE = '22023';
            END IF;
            IF p_lease_seconds IS NULL OR p_lease_seconds < 1 OR p_lease_seconds > 900 THEN
                RAISE EXCEPTION 'Delivery ticket lease must be between 1 and 900 seconds'
                    USING ERRCODE = '22023';
            END IF;

            -- Close abandoned work that can no longer be executed. An active
            -- final attempt is left alone until its lease expires; an expired
            -- proof is terminal immediately because a delivered proof would no
            -- longer be consumable.
            FOR v_terminal IN
                SELECT ticket.id,
                       ticket.case_id,
                       CASE
                           WHEN ticket.expires_at <= clock_timestamp()
                           THEN 'proof_expired'
                           ELSE 'attempts_exhausted'
                       END AS error_class
                  FROM request_engine.identity_recovery_delivery_tickets AS ticket
                  JOIN request_engine.identity_recovery_cases AS recovery_case
                    ON recovery_case.id = ticket.case_id
                 WHERE recovery_case.status = 'issued'
                   AND ticket.status IN ('pending', 'sending')
                   AND (
                       ticket.expires_at <= clock_timestamp()
                       OR (
                           ticket.attempt_count >= ticket.max_attempts
                           AND (
                               ticket.status = 'pending'
                               OR ticket.lease_until <= clock_timestamp()
                           )
                       )
                   )
                 ORDER BY ticket.id
                 FOR UPDATE OF ticket SKIP LOCKED
            LOOP
                UPDATE request_engine.identity_recovery_delivery_tickets AS ticket
                   SET status = 'failed',
                       claim_token = NULL,
                       lease_until = NULL,
                       last_error_class = v_terminal.error_class,
                       updated_at = clock_timestamp()
                 WHERE ticket.id = v_terminal.id;

                UPDATE request_engine.identity_recovery_cases AS recovery_case
                   SET delivery_status = 'failed',
                       revision = recovery_case.revision + 1,
                       updated_at = clock_timestamp()
                 WHERE recovery_case.id = v_terminal.case_id
                   AND recovery_case.status = 'issued'
                   AND recovery_case.delivery_status IN ('pending', 'sending')
                RETURNING recovery_case.revision - 1, recovery_case.revision
                     INTO v_revision_before, v_revision_after;

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
                        v_terminal.case_id,
                        'delivery_failed',
                        NULL,
                        NULL,
                        v_terminal.error_class,
                        NULL,
                        v_revision_before,
                        v_revision_after,
                        NULL,
                        'platform.identity.recovery_delivery',
                        NULL,
                        NULL
                    );
                END IF;
            END LOOP;

            RETURN QUERY
            WITH candidate AS (
                SELECT ticket.id,
                       CASE
                           WHEN ticket.status = 'pending' THEN ticket.next_attempt_at
                           ELSE ticket.lease_until
                       END AS due_at
                  FROM request_engine.identity_recovery_delivery_tickets AS ticket
                  JOIN request_engine.identity_recovery_cases AS recovery_case
                    ON recovery_case.id = ticket.case_id
                 WHERE (
                           (
                               ticket.status = 'pending'
                               AND ticket.next_attempt_at <= clock_timestamp()
                           )
                           OR (
                               ticket.status = 'sending'
                               AND ticket.lease_until <= clock_timestamp()
                           )
                       )
                   AND ticket.expires_at > clock_timestamp()
                   AND ticket.attempt_count < ticket.max_attempts
                   AND recovery_case.status = 'issued'
                 ORDER BY due_at, ticket.id
                 LIMIT p_limit
                 FOR UPDATE OF ticket SKIP LOCKED
            )
            UPDATE request_engine.identity_recovery_delivery_tickets AS ticket
               SET status = 'sending',
                   claim_token = uuidv7(),
                   lease_until = clock_timestamp() + make_interval(secs => p_lease_seconds),
                   attempt_count = ticket.attempt_count + 1,
                   last_error_class = CASE
                       WHEN ticket.status = 'sending' THEN 'lease_expired'
                       ELSE ticket.last_error_class
                   END,
                   updated_at = clock_timestamp()
              FROM candidate
             WHERE ticket.id = candidate.id
            RETURNING ticket.id,
                      ticket.case_id,
                      ticket.generation,
                      ticket.secret_reference,
                      ticket.secret_digest,
                      ticket.destination_reference,
                      ticket.expires_at,
                      ticket.attempt_count,
                      ticket.claim_token;

            UPDATE request_engine.identity_recovery_cases AS recovery_case
               SET delivery_status = 'sending',
                   revision = recovery_case.revision + 1,
                   updated_at = clock_timestamp()
             WHERE recovery_case.status = 'issued'
               AND recovery_case.delivery_status = 'pending'
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.identity_recovery_delivery_tickets AS ticket
                    WHERE ticket.case_id = recovery_case.id
                      AND ticket.status = 'sending'
                      AND ticket.lease_until > clock_timestamp()
               );
        END
        $$;


ALTER FUNCTION request_platform.claim_identity_recovery_delivery_tickets(p_limit integer, p_lease_seconds integer) OWNER TO request_platform_control_definer;

--
-- Name: commit_platform_secret_mutation(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.commit_platform_secret_mutation(p_operation_id uuid) RETURNS TABLE(operation_id uuid, operation_kind text, binding_id uuid, secret_id uuid, purpose text, backend text, expected_binding_revision bigint, expected_backend_version integer, applied_backend_version integer, operation_state text, result_binding_id uuid, result_binding_revision bigint, result_binding_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_operation request_engine.platform_secret_mutations%ROWTYPE;
            v_actor_id uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
            v_result record;
        BEGIN
            SELECT *
              INTO v_operation
              FROM request_engine.platform_secret_mutations
             WHERE id = p_operation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret mutation does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  v_operation.capability_key
              );
            IF v_actor_id <> v_operation.actor_principal_id THEN
                RAISE EXCEPTION 'Platform secret mutation belongs to another actor'
                    USING ERRCODE = '42501';
            END IF;

            IF v_operation.state IN ('committed', 'reconcile_required') THEN
                RETURN QUERY SELECT
                    v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                    v_operation.secret_id, v_operation.purpose, v_operation.backend,
                    v_operation.expected_binding_revision,
                    v_operation.expected_backend_version,
                    v_operation.applied_backend_version, v_operation.state,
                    v_operation.result_binding_id, v_operation.result_binding_revision,
                    v_operation.result_binding_status;
                RETURN;
            END IF;
            IF v_operation.state <> 'backend_applied' THEN
                RAISE EXCEPTION 'Backend mutation has not been recorded'
                    USING ERRCODE = '55000';
            END IF;

            BEGIN
                IF v_operation.operation_kind = 'create' THEN
                    SELECT * INTO v_result
                      FROM request_platform.record_platform_secret_binding(
                          v_operation.purpose,
                          v_operation.backend,
                          v_operation.secret_id,
                          v_operation.applied_backend_version,
                          v_operation.idempotency_key_digest,
                          v_operation.intent_digest
                      );
                ELSIF v_operation.operation_kind = 'rotate' THEN
                    SELECT * INTO v_result
                      FROM request_platform.commit_platform_secret_rotation(
                          v_operation.binding_id,
                          v_operation.expected_binding_revision,
                          v_operation.expected_backend_version,
                          v_operation.applied_backend_version,
                          v_operation.idempotency_key_digest,
                          v_operation.intent_digest
                      );
                ELSE
                    SELECT * INTO v_result
                      FROM request_platform.revoke_platform_secret_binding(
                          v_operation.binding_id,
                          v_operation.expected_binding_revision,
                          v_operation.expected_backend_version,
                          v_operation.idempotency_key_digest,
                          v_operation.intent_digest
                      );
                END IF;
            EXCEPTION
                WHEN SQLSTATE '40001' OR unique_violation THEN
                    UPDATE request_engine.platform_secret_mutations
                       SET state = 'reconcile_required',
                           reconcile_required_at = clock_timestamp()
                     WHERE id = p_operation_id
                    RETURNING * INTO v_operation;

                    RETURN QUERY SELECT
                        v_operation.id, v_operation.operation_kind,
                        v_operation.binding_id, v_operation.secret_id,
                        v_operation.purpose, v_operation.backend,
                        v_operation.expected_binding_revision,
                        v_operation.expected_backend_version,
                        v_operation.applied_backend_version, v_operation.state,
                        v_operation.result_binding_id,
                        v_operation.result_binding_revision,
                        v_operation.result_binding_status;
                    RETURN;
            END;

            UPDATE request_engine.platform_secret_mutations
               SET state = 'committed',
                   result_binding_id = v_result.binding_id,
                   result_binding_revision = v_result.revision,
                   result_binding_status = v_result.status,
                   committed_at = clock_timestamp()
             WHERE id = p_operation_id
            RETURNING * INTO v_operation;

            RETURN QUERY SELECT
                v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                v_operation.secret_id, v_operation.purpose, v_operation.backend,
                v_operation.expected_binding_revision,
                v_operation.expected_backend_version,
                v_operation.applied_backend_version, v_operation.state,
                v_operation.result_binding_id, v_operation.result_binding_revision,
                v_operation.result_binding_status;
        END
        $$;


ALTER FUNCTION request_platform.commit_platform_secret_mutation(p_operation_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: commit_platform_secret_rotation(uuid, bigint, integer, integer, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.commit_platform_secret_rotation(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_new_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(binding_id uuid, revision bigint, backend_version integer, status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_binding record;
            v_revision bigint;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.secret.rotate'
              );

            IF p_binding_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_expected_backend_version IS NULL
               OR p_expected_backend_version < 1
               OR p_new_backend_version IS NULL
               OR p_new_backend_version <= p_expected_backend_version
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform secret rotation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/idempotency/'
                    || v_actor_id::text
                    || '/platform.secret.rotate/'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.secret_binding_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.secret.rotate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another secret-rotation intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.secret_binding_id,
                    v_replay.revision,
                    (v_replay.detail ->> 'backend_version')::integer,
                    v_replay.detail ->> 'result_status';
                RETURN;
            END IF;

            SELECT
                binding.id,
                binding.purpose,
                binding.backend_version,
                binding.revision,
                binding.status
              INTO v_binding
              FROM request_engine.platform_secret_bindings AS binding
             WHERE binding.id = p_binding_id
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret binding does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            IF v_binding.status <> 'active'
               OR v_binding.revision <> p_expected_revision
               OR v_binding.backend_version <> p_expected_backend_version
            THEN
                RAISE EXCEPTION 'Platform secret binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_secret_bindings AS binding
               SET backend_version = p_new_backend_version,
                   revision = binding.revision + 1,
                   rotated_at = clock_timestamp()
             WHERE binding.id = p_binding_id
            RETURNING binding.revision INTO v_revision;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
                configuration_kind,
                revision,
                secret_binding_id,
                actor_principal_id,
                actor_authentication_method,
                correlation_id,
                detail,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                'secret_rotated',
                NULL,
                v_revision,
                p_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'purpose',
                    v_binding.purpose,
                    'previous_backend_version',
                    p_expected_backend_version,
                    'backend_version',
                    p_new_backend_version,
                    'result_status',
                    'active'
                ),
                'platform.secret.rotate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            RETURN QUERY
            SELECT
                p_binding_id,
                v_revision,
                p_new_backend_version,
                'active'::text;
        END
        $_$;


ALTER FUNCTION request_platform.commit_platform_secret_rotation(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_new_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: complete_identity_recovery_delivery_ticket(uuid, uuid, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.complete_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_case_id uuid;
            v_revision_before bigint;
            v_revision_after bigint;
        BEGIN
            IF p_ticket_id IS NULL OR p_claim_token IS NULL
               OR p_outcome IS NULL
               OR p_outcome NOT IN ('delivered', 'unknown', 'failed')
               OR (p_error_class IS NOT NULL
                   AND length(btrim(p_error_class)) NOT BETWEEN 1 AND 80) THEN
                RAISE EXCEPTION 'Delivery completion input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            UPDATE request_engine.identity_recovery_delivery_tickets
               SET status = p_outcome,
                   claim_token = NULL,
                   lease_until = NULL,
                   last_error_class = CASE
                       WHEN p_outcome = 'delivered' THEN NULL
                       ELSE btrim(p_error_class)
                   END,
                   delivered_at = CASE
                       WHEN p_outcome = 'delivered' THEN clock_timestamp()
                       ELSE delivered_at
                   END,
                   updated_at = clock_timestamp()
             WHERE id = p_ticket_id
               AND claim_token = p_claim_token
               AND status = 'sending'
            RETURNING case_id INTO v_case_id;
            IF NOT FOUND THEN
                RETURN false;
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET delivery_status = p_outcome,
                   revision = revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = v_case_id
               AND status = 'issued'
            RETURNING revision - 1, revision INTO v_revision_before, v_revision_after;
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
                    CASE p_outcome
                        WHEN 'delivered' THEN 'deliver'
                        WHEN 'unknown' THEN 'delivery_unknown'
                        ELSE 'delivery_failed'
                    END,
                    NULL,
                    NULL,
                    NULL,
                    NULL,
                    v_revision_before,
                    v_revision_after,
                    NULL,
                    'platform.identity.recovery_delivery',
                    NULL,
                    NULL
                );
            END IF;
            RETURN true;
        END
        $$;


ALTER FUNCTION request_platform.complete_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) OWNER TO request_platform_control_definer;

--
-- Name: create_identity_recovery_case(uuid, uuid, text, text, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.create_identity_recovery_case(p_case_id uuid, p_target_native_identity_id uuid, p_reason_code text, p_evidence_reference text, p_delivery_destination_reference text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_identity_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_target_native_identity_id IS NULL
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_evidence_reference IS NULL
               OR length(btrim(p_evidence_reference)) NOT BETWEEN 1 AND 400
               OR p_delivery_destination_reference IS NULL
               OR length(btrim(p_delivery_destination_reference)) NOT BETWEEN 1 AND 200
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity recovery case input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            -- Replay is evaluated only after revalidating current actor authority.
            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'request'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery request'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT

            recovery_case.id,
            recovery_case.target_native_identity_id,
            recovery_case.status,
            recovery_case.delivery_status,
            recovery_case.revision,
            recovery_case.issuance_generation,
            recovery_case.approval_expires_at,
            recovery_case.proof_expires_at,
            recovery_case.created_at,
            recovery_case.approved_at,
            recovery_case.issued_at,
            recovery_case.consumed_at,
            recovery_case.revoked_at
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            -- Authority/identity locks belong to the auth primitives; this
            -- command only validates current reachability before creating the case.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = p_target_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
               AND native_identity.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Recovery target is not an active Native identity'
                    USING ERRCODE = '22023';
            END IF;

            INSERT INTO request_engine.identity_recovery_cases (
                id,
                target_native_identity_id,
                requester_principal_id,
                status,
                reason_code,
                evidence_reference,
                delivery_destination_reference
            ) VALUES (
                p_case_id,
                p_target_native_identity_id,
                v_actor_id,
                'requested',
                btrim(p_reason_code),
                btrim(p_evidence_reference),
                btrim(p_delivery_destination_reference)
            );
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
                p_case_id,
                'request',
                v_actor_id,
                v_actor_method,
                btrim(p_reason_code),
                btrim(p_evidence_reference),
                1,
                1,
                v_correlation_id,
                'platform.identity.recover',
                p_idempotency_key_digest,
                p_intent_digest
            );
            RETURN QUERY SELECT

            recovery_case.id,
            recovery_case.target_native_identity_id,
            recovery_case.status,
            recovery_case.delivery_status,
            recovery_case.revision,
            recovery_case.issuance_generation,
            recovery_case.approval_expires_at,
            recovery_case.proof_expires_at,
            recovery_case.created_at,
            recovery_case.approved_at,
            recovery_case.issued_at,
            recovery_case.consumed_at,
            recovery_case.revoked_at
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $_$;


ALTER FUNCTION request_platform.create_identity_recovery_case(p_case_id uuid, p_target_native_identity_id uuid, p_reason_code text, p_evidence_reference text, p_delivery_destination_reference text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: create_platform_owner_invitation(uuid, bytea, text, timestamp with time zone, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.create_platform_owner_invitation(p_invitation_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(invitation_id uuid, created boolean, status text, expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_current_revision bigint;
            v_actor_active boolean;
            v_actor_kind text;
            v_correlation_id uuid;
            v_existing record;
        BEGIN
            IF p_invitation_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_expires_at IS NULL
               OR p_expires_at <= clock_timestamp()
               OR p_expires_at > clock_timestamp() + interval '7 days'
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform Owner invitation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            SELECT principal.active, principal.principal_kind, principal.authority_revision
              INTO v_actor_active, v_actor_kind, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform'
             FOR UPDATE;
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human'
               OR v_actor_current_revision <> v_actor_revision
            THEN
                RAISE EXCEPTION 'Current Platform Owner is unavailable or stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.principal_id = v_actor_id
                   AND grant_row.status = 'active'
                   AND grant_row.capability_key = 'platform.owner.provision'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal cannot invite owners'
                    USING ERRCODE = '42501';
            END IF;

            SELECT invitation.id, invitation.status, invitation.expires_at,
                   invitation.intent_digest
              INTO v_existing
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.invited_by_principal_id = v_actor_id
               AND invitation.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_existing.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts with another invitation'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT v_existing.id, false, v_existing.status,
                                    v_existing.expires_at;
                RETURN;
            END IF;

            INSERT INTO request_engine.platform_owner_invitations (
                id, token_digest, token_fingerprint, invited_by_principal_id,
                provenance_reference, idempotency_key_digest, intent_digest, expires_at
            ) VALUES (
                p_invitation_id, p_token_digest, p_token_fingerprint, v_actor_id,
                btrim(p_provenance_reference), p_idempotency_key_digest,
                p_intent_digest, p_expires_at
            );

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, revision_before,
                revision_after, correlation_id
            ) VALUES (
                p_invitation_id, 'create', v_actor_id, 0, 1, v_correlation_id
            );

            RETURN QUERY SELECT p_invitation_id, true, 'pending'::text, p_expires_at;
        END
        $_$;


ALTER FUNCTION request_platform.create_platform_owner_invitation(p_invitation_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: create_setup_session(uuid, bytea, text, text, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.create_setup_session(p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_mode text, p_ttl_seconds integer) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
DECLARE
    v_instance_id uuid;
    v_state text;
    v_active integer;
BEGIN
    -- Serializes concurrent creation (bounded active cap) and, together with the
    -- finalize command taking the same lock, setup creation against a claim.
    PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476358);

    SELECT instance.id, instance.state
      INTO v_instance_id, v_state
      FROM request_engine.platform_instance AS instance
     WHERE instance.singleton_key = 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Platform instance is not initialized' USING ERRCODE = '55000';
    END IF;
    IF v_state <> 'unclaimed' THEN
        RAISE EXCEPTION 'Setup is closed' USING ERRCODE = '55000';
    END IF;

    IF p_session_id IS NULL
       OR p_token_digest IS NULL
       OR octet_length(p_token_digest) <> 32
       OR p_token_fingerprint IS NULL
       OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
       OR p_mode IS NULL
       OR p_mode NOT IN ('interactive', 'protected', 'automated')
       OR p_ttl_seconds IS NULL
       OR p_ttl_seconds < 60
       OR p_ttl_seconds > 3600
    THEN
        RAISE EXCEPTION 'Setup session material is invalid' USING ERRCODE = '22023';
    END IF;

    SELECT count(*) INTO v_active
      FROM request_engine.setup_sessions
     WHERE status = 'pending'
       AND expires_at > clock_timestamp();
    IF v_active >= 5 THEN
        RAISE EXCEPTION 'Too many active setup sessions' USING ERRCODE = '54000';
    END IF;

    INSERT INTO request_engine.setup_sessions (
        id, instance_id, token_digest, token_fingerprint, mode, expires_at
    ) VALUES (
        p_session_id,
        v_instance_id,
        p_token_digest,
        p_token_fingerprint,
        p_mode,
        clock_timestamp() + pg_catalog.make_interval(secs => p_ttl_seconds)
    );
    RETURN p_session_id;
END
$_$;


ALTER FUNCTION request_platform.create_setup_session(p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_mode text, p_ttl_seconds integer) OWNER TO request_platform_control_definer;

--
-- Name: disable_native_identity(uuid, bigint, text, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.disable_native_identity(p_native_identity_id uuid, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(fact_id uuid, native_identity_id uuid, revision_after bigint, affected_tenant_count integer, affected_platform boolean)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_revision bigint;
            v_actor_method text;
            v_actor_kind text;
            v_actor_active boolean;
            v_actor_current_revision bigint;
            v_correlation_id uuid;
            v_identity record;
            v_binding record;
            v_authority_kind text;
            v_authority_status text;
            v_revision_before bigint;
            v_org_ids uuid[];
            v_org_id uuid;
            v_affected_platform boolean := false;
            v_affected_tenants integer := 0;
            v_replay record;
            v_fact_id uuid;
        BEGIN
            PERFORM set_config('lock_timeout', '10s', true);
            PERFORM request_engine.acquire_identity_topology_exclusive();

            IF p_native_identity_id IS NULL
               OR p_expected_revision IS NULL
               OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'Native identity and expected revision are required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR (p_external_case_reference IS NOT NULL
                   AND length(btrim(p_external_case_reference)) NOT BETWEEN 1 AND 200)
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Disable reason, case reference or digests are invalid'
                    USING ERRCODE = '22023';
            END IF;

            BEGIN
                v_actor_id := NULLIF(current_setting(
                    'request_engine.authenticated_principal_id', true
                ), '')::uuid;
                v_actor_revision := NULLIF(current_setting(
                    'request_engine.authority_revision', true
                ), '')::bigint;
                v_actor_method := NULLIF(current_setting(
                    'request_engine.authentication_method', true
                ), '');
                v_correlation_id := NULLIF(current_setting(
                    'request_engine.correlation_id', true
                ), '')::uuid;
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Platform actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_actor_revision IS NULL OR v_actor_method IS NULL THEN
                RAISE EXCEPTION 'Platform actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;

            -- Platform-plane serialization root: lock the platform Principal set in
            -- id order before bindings, grants or facts.
            PERFORM principal.id
              FROM request_engine.principals AS principal
             WHERE principal.principal_plane = 'platform'
             ORDER BY principal.id
             FOR UPDATE;

            SELECT principal.principal_kind, principal.active,
                   principal.authority_revision
              INTO v_actor_kind, v_actor_active, v_actor_current_revision
              FROM request_engine.principals AS principal
             WHERE principal.id = v_actor_id
               AND principal.principal_plane = 'platform';
            IF NOT FOUND OR NOT v_actor_active OR v_actor_kind <> 'human' THEN
                RAISE EXCEPTION 'Current Platform Principal cannot disable identities'
                    USING ERRCODE = '42501';
            END IF;
            IF v_actor_current_revision <> v_actor_revision THEN
                RAISE EXCEPTION 'Platform authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.principal_authority_grants AS actor_grant
                 WHERE actor_grant.principal_id = v_actor_id
                   AND actor_grant.principal_plane = 'platform'
                   AND actor_grant.authority_plane = 'platform'
                   AND actor_grant.status = 'active'
                   AND actor_grant.capability_key = 'platform.identity.disable'
            ) THEN
                RAISE EXCEPTION 'Current Platform Principal lacks identity disable authority'
                    USING ERRCODE = '42501';
            END IF;

            -- Replay is evaluated only after revalidating current actor authority.
            SELECT fact.id, fact.native_identity_id, fact.revision_after,
                   fact.affected_tenant_count, fact.affected_platform,
                   fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_disable_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.identity.disable'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key was used with a different intent'
                        USING ERRCODE = '40001';
                END IF;
                RETURN QUERY SELECT v_replay.id, v_replay.native_identity_id,
                                    v_replay.revision_after,
                                    v_replay.affected_tenant_count,
                                    v_replay.affected_platform;
                RETURN;
            END IF;

            SELECT identity.id, identity.identity_authority_id,
                   identity.status, identity.revision
              INTO v_identity
              FROM request_engine.native_identities AS identity
             WHERE identity.id = p_native_identity_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Native identity not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_identity.status <> 'active' THEN
                RAISE EXCEPTION 'Native identity is already disabled or terminal'
                    USING ERRCODE = '55000';
            END IF;
            IF v_identity.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Native identity revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            v_revision_before := v_identity.revision;

            SELECT authority.kind, authority.status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities AS authority
             WHERE authority.id = v_identity.identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native' OR v_authority_status <> 'active' THEN
                RAISE EXCEPTION 'Native identity authority is not active native'
                    USING ERRCODE = '23514';
            END IF;

            -- Only tenants whose continuity currently depends on this identity need a
            -- post-disable controller proof. The tenant predicate is owner-executed
            -- over FORCE RLS tables, so the trusted tenant GUC is set per candidate.
            FOR v_binding IN
                SELECT DISTINCT binding.organization_id, binding.principal_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.identity_authority_id = v_identity.identity_authority_id
                   AND binding.subject_id = p_native_identity_id::text
                   AND binding.principal_plane = 'tenant'
                   AND binding.organization_id IS NOT NULL
                   AND binding.status = 'active'
            LOOP
                PERFORM set_config(
                    'request_engine.organization_id', v_binding.organization_id::text, true
                );
                IF request_engine.principal_is_effective_tenant_controller(
                       v_binding.organization_id, v_binding.principal_id) THEN
                    v_org_ids := array_append(v_org_ids, v_binding.organization_id);
                END IF;
            END LOOP;
            PERFORM set_config('request_engine.organization_id', '', true);
            v_org_ids := (
                SELECT array_agg(DISTINCT org)
                  FROM unnest(v_org_ids) AS org
            );
            v_affected_tenants := COALESCE(array_length(v_org_ids, 1), 0);

            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.identity_authority_id = v_identity.identity_authority_id
                   AND binding.subject_id = p_native_identity_id::text
                   AND binding.principal_plane = 'platform'
                   AND binding.status = 'active'
                   AND request_platform.principal_is_effective_platform_controller(
                           binding.principal_id)
            ) INTO v_affected_platform;

            UPDATE request_engine.native_identities
               SET status = 'disabled',
                   session_epoch = session_epoch + 1,
                   revision = revision + 1,
                   updated_at = clock_timestamp(),
                   disabled_at = clock_timestamp()
             WHERE id = p_native_identity_id;
            UPDATE request_engine.native_credentials AS credential
               SET status = 'revoked',
                   revision = credential.revision + 1,
                   revoked_at = clock_timestamp()
             WHERE credential.native_identity_id = p_native_identity_id
               AND credential.status = 'active';
            UPDATE request_engine.native_sessions AS session
               SET status = 'revoked',
                   revoked_at = clock_timestamp(),
                   revocation_reason = 'identity_disabled'
             WHERE session.native_identity_id = p_native_identity_id
               AND session.status = 'active';
            UPDATE request_engine.native_recovery_intents AS intent
               SET status = 'revoked',
                   revoked_at = clock_timestamp()
             WHERE intent.native_identity_id = p_native_identity_id
               AND intent.status = 'pending';

            IF v_org_ids IS NOT NULL THEN
                FOREACH v_org_id IN ARRAY v_org_ids LOOP
                    PERFORM set_config(
                        'request_engine.organization_id', v_org_id::text, true
                    );
                    PERFORM request_engine.assert_organization_has_controller(v_org_id);
                END LOOP;
                PERFORM set_config('request_engine.organization_id', '', true);
            END IF;
            IF v_affected_platform THEN
                PERFORM request_platform.assert_platform_has_controller();
            END IF;

            INSERT INTO request_engine.platform_identity_disable_facts (
                actor_principal_id, capability_key, native_identity_id,
                native_authority_id, revision_before, revision_after, reason_code,
                external_case_reference, affected_tenant_count, affected_platform,
                idempotency_key_digest, intent_digest, correlation_id
            ) VALUES (
                v_actor_id, 'platform.identity.disable', p_native_identity_id,
                v_identity.identity_authority_id, v_revision_before,
                v_revision_before + 1, btrim(p_reason_code),
                NULLIF(btrim(p_external_case_reference), ''),
                v_affected_tenants, v_affected_platform,
                p_idempotency_key_digest, p_intent_digest, v_correlation_id
            ) RETURNING id INTO v_fact_id;

            RETURN QUERY SELECT v_fact_id, p_native_identity_id,
                                v_revision_before + 1, v_affected_tenants,
                                v_affected_platform;
        END
        $_$;


ALTER FUNCTION request_platform.disable_native_identity(p_native_identity_id uuid, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: disable_platform_configuration(text, bigint, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.disable_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(configuration_revision_id uuid, revision bigint, state text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_target record;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.disable'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration disable input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/idempotency/'
                    || v_actor_id::text
                    || '/platform.configuration.disable/'
                    || p_idempotency_key_digest,
                    0
                )
            );

            SELECT
                fact.configuration_revision_id,
                fact.revision,
                fact.intent_digest,
                fact.detail
              INTO v_replay
              FROM request_engine.platform_configuration_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.capability_key = 'platform.configuration.disable'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another disable intent'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY
                SELECT
                    v_replay.configuration_revision_id,
                    v_replay.revision,
                    v_replay.detail ->> 'result_state';
                RETURN;
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/configuration-kind/' || p_configuration_kind,
                    0
                )
            );

            SELECT
                revision_row.id,
                revision_row.state,
                revision_row.secret_binding_id
              INTO v_target
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE revision_row.configuration_kind = p_configuration_kind
               AND revision_row.revision = p_revision
             FOR UPDATE;

            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform configuration revision does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            IF v_target.state NOT IN ('draft', 'validated', 'active') THEN
                RAISE EXCEPTION
                    'Platform configuration revision cannot be disabled'
                    USING ERRCODE = '40001';
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'disabled',
                   disabled_at = clock_timestamp()
             WHERE id = v_target.id;

            INSERT INTO request_engine.platform_configuration_facts (
                event_kind,
                configuration_revision_id,
                configuration_kind,
                revision,
                secret_binding_id,
                actor_principal_id,
                actor_authentication_method,
                correlation_id,
                detail,
                capability_key,
                idempotency_key_digest,
                intent_digest
            ) VALUES (
                'disabled',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'previous_state',
                    v_target.state,
                    'result_state',
                    'disabled'
                ),
                'platform.configuration.disable',
                p_idempotency_key_digest,
                p_intent_digest
            );

            IF v_target.state = 'active' THEN
                PERFORM pg_catalog.pg_notify(
                    'request_engine_platform_configuration',
                    jsonb_build_object(
                        'configuration_kind',
                        p_configuration_kind,
                        'revision',
                        p_revision,
                        'state',
                        'disabled'
                    )::text
                );
            END IF;

            RETURN QUERY
            SELECT v_target.id, p_revision, 'disabled'::text;
        END
        $_$;


ALTER FUNCTION request_platform.disable_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: enroll_platform_owner_invitation(bytea, uuid, uuid, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.enroll_platform_owner_invitation(p_token_digest bytea, p_native_identity_id uuid, p_credential_id uuid, p_login_handle text, p_password_verifier text) RETURNS TABLE(invitation_id uuid, native_identity_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_invitation record;
            v_instance record;
        BEGIN
            IF p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_native_identity_id IS NULL OR p_credential_id IS NULL
               OR p_login_handle IS NULL
               OR length(btrim(p_login_handle)) NOT BETWEEN 1 AND 320
               OR p_password_verifier IS NULL
               OR NOT (p_password_verifier LIKE '$argon2id$%'
                       OR p_password_verifier LIKE 'scrypt$%')
            THEN
                RETURN;
            END IF;

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.expires_at
              INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.token_digest = p_token_digest
             FOR UPDATE;
            IF NOT FOUND
               OR v_invitation.status <> 'pending'
               OR v_invitation.expires_at <= clock_timestamp()
            THEN
                RETURN;
            END IF;

            SELECT instance.id, instance.built_in_native_authority_id, instance.state
              INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1
             FOR SHARE;
            IF NOT FOUND OR v_instance.state <> 'claimed' THEN
                RETURN;
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, v_instance.built_in_native_authority_id,
                btrim(p_login_handle)
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_password_verifier
            );

            UPDATE request_engine.platform_owner_invitations
               SET status = 'enrolled',
                   revision = revision + 1,
                   native_identity_id = p_native_identity_id,
                   enrolled_at = clock_timestamp()
             WHERE id = v_invitation.id;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, native_identity_id, revision_before, revision_after
            ) VALUES (
                v_invitation.id, 'enroll', p_native_identity_id,
                v_invitation.revision, v_invitation.revision + 1
            );

            RETURN QUERY SELECT v_invitation.id, p_native_identity_id;
        EXCEPTION WHEN unique_violation THEN
            RETURN;
        END
        $_$;


ALTER FUNCTION request_platform.enroll_platform_owner_invitation(p_token_digest bytea, p_native_identity_id uuid, p_credential_id uuid, p_login_handle text, p_password_verifier text) OWNER TO request_platform_control_definer;

--
-- Name: establish_root(uuid, bytea, uuid, uuid, text, uuid, text, uuid, uuid); Type: FUNCTION; Schema: request_platform; Owner: request_bootstrap_definer
--

CREATE FUNCTION request_platform.establish_root(p_intent_id uuid, p_token_digest bytea, p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_password_verifier text, p_principal_id uuid, p_binding_id uuid) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_provenance text;
            v_authority_kind text;
            v_authority_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476356);

            SELECT provenance_reference
              INTO v_provenance
              FROM request_engine.platform_bootstrap_intents
             WHERE id = p_intent_id
               AND token_digest = p_token_digest
               AND permitted_action = 'platform.root.establish'
               AND status = 'pending'
               AND expires_at > clock_timestamp()
             FOR UPDATE;
            IF NOT FOUND THEN
                RETURN NULL;
            END IF;

            PERFORM 1
              FROM request_engine.principals
             WHERE principal_plane = 'platform'
             LIMIT 1;
            IF FOUND THEN
                RAISE EXCEPTION 'Platform root already exists'
                    USING ERRCODE = '55000';
            END IF;

            SELECT kind, status
              INTO v_authority_kind, v_authority_status
              FROM request_engine.identity_authorities
             WHERE id = p_identity_authority_id;
            IF NOT FOUND OR v_authority_kind <> 'native'
               OR v_authority_status <> 'active'
            THEN
                RAISE EXCEPTION 'Platform root requires an active Native identity authority'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                p_native_identity_id, p_identity_authority_id, p_login_handle
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                p_credential_id, p_native_identity_id, p_password_verifier
            );
            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                p_principal_id,
                'platform',
                'human',
                'native-bootstrap:' || p_native_identity_id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id,
                subject_id, status
            ) VALUES (
                p_binding_id,
                p_principal_id,
                'platform',
                p_identity_authority_id,
                p_native_identity_id::text,
                'active'
            );

            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT p_principal_id,
                   'platform',
                   'platform',
                   capability_key,
                   delegable,
                   'trust_bootstrap',
                   'platform-bootstrap:' || p_intent_id::text || ':' || v_provenance
              FROM (VALUES
                  ('platform.principal.provision', true),
                  ('platform.tenant_provisioner.provision', true),
                  ('organization.provision', true),
                  ('platform.identity.recover', false),
                  ('platform.identity.read', false),
                  ('platform.identity.recovery_approve', false),
                  ('platform.recovery_operator.provision', false),
                  ('platform.provisioner.read', false),
                  ('platform.provisioner.manage_lifecycle', false),
                  ('platform.owner.read', false),
                  ('platform.owner.provision', false),
                  ('platform.owner.manage_lifecycle', false),
                  ('platform.identity.provision', false)
              ) AS initial_grant(capability_key, delegable);

            UPDATE request_engine.platform_bootstrap_intents
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_intent_id;
            RETURN p_principal_id;
        END
        $$;


ALTER FUNCTION request_platform.establish_root(p_intent_id uuid, p_token_digest bytea, p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_password_verifier text, p_principal_id uuid, p_binding_id uuid) OWNER TO request_bootstrap_definer;

--
-- Name: finalize_instance_claim(uuid, text, text, text, text, uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.finalize_instance_claim(p_setup_session_id uuid, p_idempotency_key_digest text, p_intent_digest text, p_claim_provenance text, p_actor_authentication_method text, p_correlation_id uuid) RETURNS TABLE(instance_id uuid, owner_principal_id uuid, native_identity_id uuid, setup_session_id uuid, policy_key text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_instance request_engine.platform_instance%ROWTYPE;
            v_session request_engine.setup_sessions%ROWTYPE;
            v_identity request_engine.setup_pending_identity%ROWTYPE;
            v_verified_count integer;
            v_policy request_engine.platform_owner_policies%ROWTYPE;
            v_principal_id uuid;
            v_binding_id uuid;
            v_replay request_engine.platform_installation_claim_facts%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_exclusive();

            IF p_setup_session_id IS NULL
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
               OR p_claim_provenance IS NULL
               OR length(btrim(p_claim_provenance)) NOT BETWEEN 1 AND 500
            THEN
                RAISE EXCEPTION 'Instance claim request is invalid' USING ERRCODE = '22023';
            END IF;

            -- Serialization root: the singleton instance row.
            SELECT instance.* INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform instance is not initialized' USING ERRCODE = '55000';
            END IF;

            IF v_instance.state = 'claimed' THEN
                SELECT fact.* INTO v_replay
                  FROM request_engine.platform_installation_claim_facts AS fact
                 WHERE fact.idempotency_key_digest = p_idempotency_key_digest;
                IF FOUND AND v_replay.intent_digest = p_intent_digest THEN
                    RETURN QUERY SELECT v_replay.instance_id, v_replay.owner_principal_id,
                                        v_replay.native_identity_id,
                                        v_replay.setup_session_id, v_replay.policy_key;
                    RETURN;
                END IF;
                RAISE EXCEPTION 'Instance is already claimed' USING ERRCODE = '55000';
            END IF;

            SELECT session.* INTO v_session
              FROM request_engine.setup_sessions AS session
             WHERE session.id = p_setup_session_id;
            IF NOT FOUND
               OR v_session.status <> 'pending'
               OR v_session.expires_at <= clock_timestamp()
               OR v_session.instance_id <> v_instance.id
            THEN
                RAISE EXCEPTION 'Setup session is not usable' USING ERRCODE = '55000';
            END IF;

            SELECT identity.* INTO v_identity
              FROM request_engine.setup_pending_identity AS identity
             WHERE identity.setup_session_id = p_setup_session_id;
            IF NOT FOUND OR v_identity.status <> 'pending' THEN
                RAISE EXCEPTION 'Setup has no pending identity' USING ERRCODE = '55000';
            END IF;

            SELECT count(*)::integer INTO v_verified_count
              FROM request_engine.setup_pending_webauthn_credential AS credential
             WHERE credential.setup_session_id = p_setup_session_id
               AND credential.status = 'pending'
               AND credential.user_verified;
            IF v_verified_count < 1 THEN
                RAISE EXCEPTION 'Setup requires a verified WebAuthn authenticator'
                    USING ERRCODE = '55000';
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM request_engine.recovery_code_sets AS code_set
                 WHERE code_set.setup_session_id = p_setup_session_id
                   AND code_set.status = 'active'
            ) THEN
                RAISE EXCEPTION 'Setup requires recovery codes' USING ERRCODE = '55000';
            END IF;

            SELECT policy.* INTO v_policy
              FROM request_engine.platform_owner_policies AS policy
             WHERE policy.policy_key = 'platform-owner-v1';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform owner policy is missing' USING ERRCODE = '55000';
            END IF;

            v_principal_id := gen_random_uuid();
            v_binding_id := gen_random_uuid();

            INSERT INTO request_engine.native_identities (
                id, identity_authority_id, login_handle
            ) VALUES (
                v_identity.id, v_instance.built_in_native_authority_id,
                v_identity.login_handle
            );
            INSERT INTO request_engine.native_credentials (
                id, native_identity_id, verifier
            ) VALUES (
                gen_random_uuid(), v_identity.id, v_identity.verifier
            );
            INSERT INTO request_engine.webauthn_credentials (
                id, native_identity_id, credential_id, public_key, sign_count,
                aaguid, backup_eligible, backup_state, user_verified
            )
            SELECT gen_random_uuid(), v_identity.id, credential.credential_id,
                   credential.public_key, credential.sign_count, credential.aaguid,
                   credential.backup_eligible, credential.backup_state,
                   credential.user_verified
              FROM request_engine.setup_pending_webauthn_credential AS credential
             WHERE credential.setup_session_id = p_setup_session_id
               AND credential.status = 'pending';

            INSERT INTO request_engine.principals (
                id, principal_plane, principal_kind, external_subject
            ) VALUES (
                v_principal_id, 'platform', 'human', 'instance-claim:' || v_identity.id::text
            );
            INSERT INTO request_engine.identity_bindings (
                id, principal_id, principal_plane, identity_authority_id, subject_id, status
            ) VALUES (
                v_binding_id, v_principal_id, 'platform',
                v_instance.built_in_native_authority_id, v_identity.id::text, 'active'
            );
            INSERT INTO request_engine.principal_authority_grants (
                principal_id, principal_plane, authority_plane, capability_key,
                delegable, provenance_kind, provenance_reference
            )
            SELECT v_principal_id, 'platform', 'platform',
                   grant_item ->> 'capability_key',
                   coalesce((grant_item ->> 'delegable')::boolean, false),
                   'trust_bootstrap',
                   'instance-claim:' || v_instance.id::text || ':' || btrim(p_claim_provenance)
              FROM jsonb_array_elements(v_policy.grants) AS grant_item;

            UPDATE request_engine.recovery_code_sets AS code_set
               SET setup_session_id = NULL,
                   native_identity_id = v_identity.id
             WHERE code_set.setup_session_id = p_setup_session_id
               AND code_set.status = 'active';

            UPDATE request_engine.setup_pending_identity
               SET status = 'promoted', promoted_at = clock_timestamp()
             WHERE id = v_identity.id;
            UPDATE request_engine.setup_pending_webauthn_credential AS credential
               SET status = 'promoted', promoted_at = clock_timestamp()
             WHERE credential.setup_session_id = p_setup_session_id
               AND credential.status = 'pending';

            UPDATE request_engine.setup_sessions
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = p_setup_session_id;

            UPDATE request_engine.platform_instance
               SET state = 'claimed',
                   revision = revision + 1,
                   claimed_at = clock_timestamp(),
                   initial_owner_principal_id = v_principal_id,
                   claim_provenance = btrim(p_claim_provenance)
             WHERE singleton_key = 1;

            INSERT INTO request_engine.platform_installation_claim_facts (
                instance_id, setup_session_id, owner_principal_id, native_identity_id,
                policy_key, claim_provenance, idempotency_key_digest, intent_digest,
                correlation_id
            ) VALUES (
                v_instance.id, p_setup_session_id, v_principal_id, v_identity.id,
                v_policy.policy_key, btrim(p_claim_provenance), p_idempotency_key_digest,
                p_intent_digest, p_correlation_id
            );

            RETURN QUERY SELECT v_instance.id, v_principal_id, v_identity.id,
                                p_setup_session_id, v_policy.policy_key;
        END
        $_$;


ALTER FUNCTION request_platform.finalize_instance_claim(p_setup_session_id uuid, p_idempotency_key_digest text, p_intent_digest text, p_claim_provenance text, p_actor_authentication_method text, p_correlation_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: grant_platform_owner_v2_capabilities_on_claim(); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF OLD.state = 'unclaimed'
               AND NEW.state = 'claimed'
               AND NEW.initial_owner_principal_id IS NOT NULL
               AND EXISTS (
                   SELECT 1
                     FROM request_engine.principals AS principal
                    WHERE principal.id = NEW.initial_owner_principal_id
                      AND principal.principal_plane = 'platform'
                      AND principal.principal_kind = 'human'
                      AND principal.active
               )
            THEN
                INSERT INTO request_engine.principal_authority_grants (
                    principal_id, principal_plane, authority_plane, capability_key,
                    delegable, provenance_kind, provenance_reference
                )
                SELECT NEW.initial_owner_principal_id,
                       'platform',
                       'platform',
                       capability.capability_key,
                       false,
                       'trust_bootstrap',
                       'platform-owner-v2-claim:' || NEW.id::text
                  FROM (
                      VALUES ('platform.owner.read'),
                             ('platform.owner.provision'),
                             ('platform.owner.manage_lifecycle'),
                             ('platform.identity.provision')
                  ) AS capability(capability_key)
                 WHERE NOT EXISTS (
                     SELECT 1
                       FROM request_engine.principal_authority_grants AS existing
                      WHERE existing.principal_id = NEW.initial_owner_principal_id
                        AND existing.capability_key = capability.capability_key
                        AND existing.status = 'active'
                 );
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim() OWNER TO request_platform_control_definer;

--
-- Name: issue_identity_recovery_case(uuid, bigint, integer, uuid, bytea, text, timestamp with time zone, uuid, text, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.issue_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_ticket_id uuid, p_secret_reference text, p_secret_digest text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
            v_superseded record;
            v_created boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_generation IS NULL OR p_generation < 1
               OR p_recovery_id IS NULL
               OR p_token_digest IS NULL OR octet_length(p_token_digest) <> 32
               OR p_token_fingerprint IS NULL
               OR p_token_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_proof_expires_at IS NULL
               OR p_proof_expires_at <= clock_timestamp()
               OR p_proof_expires_at > clock_timestamp() + interval '30 minutes'
               OR p_ticket_id IS NULL
               OR p_secret_reference IS NULL
               OR length(btrim(p_secret_reference)) NOT BETWEEN 1 AND 400
               OR p_secret_digest IS NULL
               OR p_secret_digest !~ '^[0-9a-f]{64}$'
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity recovery issuance input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'issue'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery issuance'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    recovery_case.id,
                    recovery_case.target_native_identity_id,
                    recovery_case.status,
                    recovery_case.delivery_status,
                    recovery_case.revision,
                    recovery_case.issuance_generation,
                    recovery_case.approval_expires_at,
                    recovery_case.proof_expires_at,
                    recovery_case.created_at,
                    recovery_case.approved_at,
                    recovery_case.issued_at,
                    recovery_case.consumed_at,
                    recovery_case.revoked_at
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id
                   AND reservation.generation = p_generation
                   AND reservation.idempotency_key_digest = p_idempotency_key_digest
            ) THEN
                RAISE EXCEPTION 'Identity recovery issuance generation is not reserved'
                    USING ERRCODE = '40001';
            END IF;

            -- The auth primitive owns the authoritative authority/identity locks
            -- and revokes every prior pending intent for the target. Calling it
            -- before the case lock serializes concurrent issuances of the same
            -- identity on the identity row instead of on the case set.
            SELECT request_auth.create_native_recovery_intent(
                v_case.target_native_identity_id,
                p_recovery_id,
                p_token_digest,
                p_token_fingerprint,
                p_proof_expires_at
            ) INTO v_created;
            IF v_created IS NOT TRUE THEN
                RAISE EXCEPTION 'Recovery target is no longer eligible for issuance'
                    USING ERRCODE = '23514';
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id
                   AND reservation.generation = p_generation
                   AND reservation.idempotency_key_digest = p_idempotency_key_digest
            ) THEN
                RAISE EXCEPTION 'Identity recovery issuance generation is not reserved'
                    USING ERRCODE = '40001';
            END IF;

            -- A new issuance supersedes every other live proof of this identity.
            FOR v_superseded IN
                SELECT candidate.id, candidate.revision
                  FROM request_engine.identity_recovery_cases AS candidate
                 WHERE candidate.target_native_identity_id = v_case.target_native_identity_id
                   AND candidate.status = 'issued'
                   AND candidate.id <> p_case_id
                 ORDER BY candidate.id
                 FOR UPDATE
            LOOP
                UPDATE request_engine.identity_recovery_cases
                   SET status = 'revoked',
                       revoked_at = clock_timestamp(),
                       revoke_reason_code = 'superseded_by_new_issuance',
                       revision = identity_recovery_cases.revision + 1,
                       updated_at = clock_timestamp()
                 WHERE id = v_superseded.id;
                UPDATE request_engine.identity_recovery_delivery_tickets
                   SET status = 'cancelled',
                       claim_token = NULL,
                       lease_until = NULL,
                       updated_at = clock_timestamp()
                 WHERE identity_recovery_delivery_tickets.case_id = v_superseded.id
                   AND identity_recovery_delivery_tickets.status IN ('pending', 'sending');
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
                    v_superseded.id,
                    'revoke',
                    v_actor_id,
                    v_actor_method,
                    'superseded_by_new_issuance',
                    NULL,
                    v_superseded.revision,
                    v_superseded.revision + 1,
                    v_correlation_id,
                    'platform.identity.recover',
                    NULL,
                    NULL
                );
            END LOOP;

            UPDATE request_engine.identity_recovery_cases
               SET status = 'issued',
                   recovery_intent_id = p_recovery_id,
                   issuance_generation = p_generation,
                   issued_at = clock_timestamp(),
                   proof_expires_at = p_proof_expires_at,
                   delivery_status = 'pending',
                   revision = identity_recovery_cases.revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_case_id;
            DELETE FROM request_engine.identity_recovery_issuance_reservations AS reservation
             WHERE reservation.case_id = p_case_id
               AND reservation.generation = p_generation;
            INSERT INTO request_engine.identity_recovery_delivery_tickets (
                id,
                case_id,
                generation,
                status,
                secret_reference,
                secret_digest,
                destination_reference,
                expires_at
            ) VALUES (
                p_ticket_id,
                p_case_id,
                p_generation,
                'pending',
                btrim(p_secret_reference),
                p_secret_digest,
                v_case.delivery_destination_reference,
                p_proof_expires_at
            );
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
                p_case_id,
                'issue',
                v_actor_id,
                v_actor_method,
                'recovery_issued',
                v_case.evidence_reference,
                v_case.revision,
                v_case.revision + 1,
                v_correlation_id,
                'platform.identity.recover',
                p_idempotency_key_digest,
                p_intent_digest
            );
            RETURN QUERY SELECT
                recovery_case.id,
                recovery_case.target_native_identity_id,
                recovery_case.status,
                recovery_case.delivery_status,
                recovery_case.revision,
                recovery_case.issuance_generation,
                recovery_case.approval_expires_at,
                recovery_case.proof_expires_at,
                recovery_case.created_at,
                recovery_case.approved_at,
                recovery_case.issued_at,
                recovery_case.consumed_at,
                recovery_case.revoked_at
              FROM request_engine.identity_recovery_cases AS recovery_case
             WHERE recovery_case.id = p_case_id;
        END
        $_$;


ALTER FUNCTION request_platform.issue_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_ticket_id uuid, p_secret_reference text, p_secret_digest text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: managed_oidc_projection_matches(text, text, text, bigint); Type: FUNCTION; Schema: request_platform; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_platform.managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_authorities AS authority
                 WHERE authority.kind = 'oidc'
                   AND authority.issuer_or_environment = p_issuer
                   AND authority.status = 'active'
                   AND authority.configuration_ref = jsonb_build_object(
                       'jwks_uri', p_jwks_uri,
                       'audience', p_audience,
                       'managed_configuration_revision', p_revision
                   )::text
            )
        $$;


ALTER FUNCTION request_platform.managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint) OWNER TO request_engine_schema_owner;

--
-- Name: mark_platform_secret_backend_applied(uuid, integer); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer) RETURNS TABLE(operation_id uuid, operation_kind text, binding_id uuid, secret_id uuid, purpose text, backend text, expected_binding_revision bigint, expected_backend_version integer, applied_backend_version integer, operation_state text, result_binding_id uuid, result_binding_revision bigint, result_binding_status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_operation request_engine.platform_secret_mutations%ROWTYPE;
            v_actor_id uuid;
            v_ignore_method text;
            v_ignore_correlation uuid;
        BEGIN
            SELECT *
              INTO v_operation
              FROM request_engine.platform_secret_mutations
             WHERE id = p_operation_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform secret mutation does not exist'
                    USING ERRCODE = 'P0002';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_ignore_method, v_ignore_correlation
              FROM request_platform.assert_platform_configuration_actor(
                  v_operation.capability_key
              );
            IF v_actor_id <> v_operation.actor_principal_id THEN
                RAISE EXCEPTION 'Platform secret mutation belongs to another actor'
                    USING ERRCODE = '42501';
            END IF;

            IF v_operation.state IN ('committed', 'reconcile_required') THEN
                RETURN QUERY SELECT
                    v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                    v_operation.secret_id, v_operation.purpose, v_operation.backend,
                    v_operation.expected_binding_revision,
                    v_operation.expected_backend_version,
                    v_operation.applied_backend_version, v_operation.state,
                    v_operation.result_binding_id, v_operation.result_binding_revision,
                    v_operation.result_binding_status;
                RETURN;
            END IF;

            IF p_applied_backend_version IS NULL OR p_applied_backend_version < 1
               OR (v_operation.operation_kind = 'rotate'
                   AND p_applied_backend_version <= v_operation.expected_backend_version)
               OR (v_operation.operation_kind = 'revoke'
                   AND p_applied_backend_version <> v_operation.expected_backend_version)
            THEN
                RAISE EXCEPTION 'Applied backend version is invalid'
                    USING ERRCODE = '22023';
            END IF;

            IF v_operation.state = 'backend_applied' THEN
                IF v_operation.applied_backend_version <> p_applied_backend_version THEN
                    RAISE EXCEPTION 'Backend-applied version changed'
                        USING ERRCODE = '40001';
                END IF;
            ELSE
                UPDATE request_engine.platform_secret_mutations
                   SET state = 'backend_applied',
                       applied_backend_version = p_applied_backend_version,
                       backend_applied_at = clock_timestamp()
                 WHERE id = p_operation_id
                RETURNING * INTO v_operation;
            END IF;

            RETURN QUERY SELECT
                v_operation.id, v_operation.operation_kind, v_operation.binding_id,
                v_operation.secret_id, v_operation.purpose, v_operation.backend,
                v_operation.expected_binding_revision,
                v_operation.expected_backend_version,
                v_operation.applied_backend_version, v_operation.state,
                v_operation.result_binding_id, v_operation.result_binding_revision,
                v_operation.result_binding_status;
        END
        $$;


ALTER FUNCTION request_platform.mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer) OWNER TO request_platform_control_definer;

--
-- Name: native_identity_ready_for_platform_owner(uuid, uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.native_identity_ready_for_platform_owner(p_identity_authority_id uuid, p_native_identity_id uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            SELECT EXISTS (
                SELECT 1
                  FROM request_engine.identity_authorities AS authority
                  JOIN request_engine.native_identities AS identity
                    ON identity.identity_authority_id = authority.id
                 WHERE authority.id = p_identity_authority_id
                   AND authority.kind = 'native'
                   AND authority.status = 'active'
                   AND identity.id = p_native_identity_id
                   AND identity.status = 'active'
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.native_credentials AS password
                        WHERE password.native_identity_id = identity.id
                          AND password.kind = 'password'
                          AND password.status = 'active'
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.webauthn_credentials AS credential
                        WHERE credential.native_identity_id = identity.id
                          AND credential.status = 'active'
                          AND credential.user_verified
                   )
                   AND EXISTS (
                       SELECT 1
                         FROM request_engine.recovery_code_sets AS code_set
                        WHERE code_set.native_identity_id = identity.id
                          AND code_set.status = 'active'
                          AND EXISTS (
                              SELECT 1
                                FROM request_engine.recovery_codes AS code
                               WHERE code.set_id = code_set.id
                                 AND code.used_at IS NULL
                          )
                   )
            )
        $$;


ALTER FUNCTION request_platform.native_identity_ready_for_platform_owner(p_identity_authority_id uuid, p_native_identity_id uuid) OWNER TO request_platform_control_definer;

--
-- Name: prepare_identity_recovery_issue(uuid, bigint, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.prepare_identity_recovery_issue(p_case_id uuid, p_expected_revision bigint, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(replayed boolean, case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
            v_reserved integer;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity recovery issuance input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor('platform.identity.recover');

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'issue'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery issuance'
                        USING ERRCODE = '23505';
                END IF;
                RETURN QUERY SELECT
                    true,
                    recovery_case.id,
                    recovery_case.target_native_identity_id,
                    recovery_case.status,
                    recovery_case.delivery_status,
                    recovery_case.revision,
                    recovery_case.issuance_generation,
                    recovery_case.approval_expires_at,
                    recovery_case.proof_expires_at,
                    recovery_case.created_at,
                    recovery_case.approved_at,
                    recovery_case.issued_at,
                    recovery_case.consumed_at,
                    recovery_case.revoked_at
                  FROM request_engine.identity_recovery_cases AS recovery_case
                 WHERE recovery_case.id = v_replay.case_id;
                RETURN;
            END IF;

            SELECT * INTO v_case
              FROM request_engine.identity_recovery_cases
             WHERE id = p_case_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'approved' THEN
                RAISE EXCEPTION 'Only an approved recovery case can be issued'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.approval_expires_at IS NULL
               OR v_case.approval_expires_at <= clock_timestamp() THEN
                RAISE EXCEPTION 'Recovery approval has expired'
                    USING ERRCODE = '55000';
            END IF;

            -- Reuse the reservation for this idempotency key; otherwise reserve
            -- the next generation above every live reservation and the last
            -- committed issuance. The FOR UPDATE case lock serializes allocation.
            SELECT reservation.generation INTO v_reserved
              FROM request_engine.identity_recovery_issuance_reservations AS reservation
             WHERE reservation.case_id = p_case_id
               AND reservation.idempotency_key_digest = p_idempotency_key_digest;
            IF NOT FOUND THEN
                SELECT COALESCE(max(reservation.generation), v_case.issuance_generation) + 1
                  INTO v_reserved
                  FROM request_engine.identity_recovery_issuance_reservations AS reservation
                 WHERE reservation.case_id = p_case_id;
                INSERT INTO request_engine.identity_recovery_issuance_reservations
