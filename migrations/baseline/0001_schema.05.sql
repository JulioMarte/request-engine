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
            v_recorded_policy_key text;
            v_policy_revision integer;
            v_policy_grants jsonb;
            v_policy_ready boolean := false;
            v_staff_available boolean := false;
            v_authority_revision bigint;
        BEGIN
            IF p_organization_id IS NULL
               OR p_organization_id IS DISTINCT FROM v_org_id
            THEN
                RAISE EXCEPTION 'Onboarding identity facts are tenant-scoped'
                    USING ERRCODE = '42501';
            END IF;

            SELECT membership.principal_id
              INTO v_active_controller_id
              FROM request_engine.staff_memberships AS membership
              JOIN request_engine.principals AS principal
                ON principal.id = membership.principal_id
               AND principal.principal_plane = 'tenant'
               AND principal.active
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND (
                   SELECT count(DISTINCT grant_row.capability_key)
                     FROM request_engine.principal_authority_grants AS grant_row
                    WHERE grant_row.organization_id = p_organization_id
                      AND grant_row.principal_id = membership.principal_id
                      AND grant_row.status = 'active'
                      AND grant_row.capability_key IN (
                          'staff.manage_membership',
                          'staff.manage_authority',
                          'identity.bind'
                      )
               ) = 3
             ORDER BY membership.principal_id
             LIMIT 1;

            SELECT membership.principal_id
              INTO v_effective_controller_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       p_organization_id, membership.principal_id
                   )
             ORDER BY membership.principal_id
             LIMIT 1;

            SELECT root_fact.initial_controller_policy_key
              INTO v_recorded_policy_key
              FROM request_engine.organization_root_provisioning_facts AS root_fact
             WHERE root_fact.organization_id = p_organization_id;

            IF v_recorded_policy_key IS NOT NULL THEN
                SELECT policy.revision, policy.grants
                  INTO v_policy_revision, v_policy_grants
                  FROM request_engine.initial_controller_policies AS policy
                 WHERE policy.policy_key = v_recorded_policy_key;
                IF FOUND
                   AND COALESCE(v_active_controller_id, v_effective_controller_id)
                       IS NOT NULL
                THEN
                    v_policy_ready := NOT EXISTS (
                        SELECT 1
                          FROM jsonb_to_recordset(v_policy_grants)
                            AS g(capability_key text, authority_plane text, delegable boolean)
                         WHERE NOT EXISTS (
                                   SELECT 1
                                     FROM request_engine.principal_authority_grants AS active
                                    WHERE active.organization_id = p_organization_id
                                      AND active.principal_id = COALESCE(
                                              v_active_controller_id,
                                              v_effective_controller_id
                                          )
                                      AND active.capability_key = g.capability_key
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
                   AND principal.principal_plane = 'tenant'
                   AND principal.active
                 WHERE membership_grant.organization_id = p_organization_id
                   AND membership_grant.capability_key = 'staff.manage_membership'
                   AND membership_grant.status = 'active'
            ) INTO v_staff_available;

            IF v_effective_controller_id IS NOT NULL THEN
                SELECT principal.authority_revision
                  INTO v_authority_revision
                  FROM request_engine.principals AS principal
                 WHERE principal.id = v_effective_controller_id;
            ELSIF v_active_controller_id IS NOT NULL THEN
                SELECT principal.authority_revision
                  INTO v_authority_revision
                  FROM request_engine.principals AS principal
                 WHERE principal.id = v_active_controller_id;
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
                'staff_administration', jsonb_build_object(
                    'available', v_staff_available
                ),
                'observed_at', to_char(
                    clock_timestamp() AT TIME ZONE 'UTC',
                    'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                ),
                'controller_authority_revision', v_authority_revision,
                'policy_revision', v_policy_revision
            );
        END
        $$;


ALTER FUNCTION request_engine.read_onboarding_identity_facts(p_organization_id uuid) OWNER TO request_engine_schema_owner;

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
-- Name: replace_agent_authority(uuid, bigint, text[], text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.replace_agent_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_profile_status text;
            v_workload_identity_id uuid;
            v_current_revision bigint;
            v_capability text;
            v_plane text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager(
                'agent.manage_authority'
            );
            SELECT status, workload_identity_id
              INTO v_profile_status, v_workload_identity_id
              FROM request_engine.agent_profiles
             WHERE principal_id = p_principal_id
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent profile not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_profile_status NOT IN ('pending', 'active') THEN
                RAISE EXCEPTION 'Suspended or revoked agents cannot receive authority'
                    USING ERRCODE = '55000';
            END IF;
            IF p_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Agent authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id
             FOR UPDATE;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Agent authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(COALESCE(p_desired_capabilities, ARRAY[]::text[])) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(COALESCE(p_desired_capabilities, ARRAY[]::text[])) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(
                                COALESCE(p_desired_capabilities, ARRAY[]::text[])
                            ) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Desired agent authority is invalid'
                    USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
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
                        'Desired authority exceeds the agent operational ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE organization_id = v_org_id
               AND principal_id = p_principal_id
               AND status = 'active'
               AND NOT (
                   capability_key = ANY(
                       COALESCE(p_desired_capabilities, ARRAY[]::text[])
                   )
               );

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = p_principal_id
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    INSERT INTO request_engine.principal_authority_grants (
                        organization_id,
                        principal_id,
                        principal_plane,
                        authority_plane,
                        capability_key,
                        delegable,
                        granted_by_principal_id,
                        provenance_kind,
                        provenance_reference
                    ) VALUES (
                        v_org_id,
                        p_principal_id,
                        'tenant',
                        'operational',
                        v_capability,
                        false,
                        v_actor_id,
                        'agent_authority_management',
                        btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;

            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_current_revision;
        END
        $$;


ALTER FUNCTION request_engine.replace_agent_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: replace_integration_authority(uuid, bigint, text[], text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.replace_integration_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := 'integration.manage_authority';
            BEGIN
                PERFORM request_engine.acquire_identity_topology_share();
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                
                IF p_expected_authority_revision IS NULL OR p_expected_authority_revision < 1
                   OR p_desired_capabilities IS NULL
                   OR array_position(p_desired_capabilities, NULL) IS NOT NULL
                   OR cardinality(p_desired_capabilities) > 128 THEN
                    RAISE EXCEPTION 'Invalid integration authority input'
                        USING ERRCODE = '22023';
                END IF;
            
                IF 'authority_replace' <> 'provision' THEN
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
                v_revision := request_engine.replace_integration_authority_state(p_principal_id, p_expected_authority_revision, p_desired_capabilities, p_provenance_reference);
                IF 'authority_replace' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, 'authority_replace', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $$;


ALTER FUNCTION request_engine.replace_integration_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: replace_integration_authority_state(uuid, bigint, text[], text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.replace_integration_authority_state(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_principal record;
            v_active boolean;
            v_current_revision bigint;
            v_capability text;
            v_plane text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            v_actor_id := request_engine.assert_staff_manager(
                'integration.manage_authority'
            );
            SELECT principal_kind, principal_plane
              INTO v_principal
              FROM request_engine.principals
             WHERE id = p_principal_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration Principal not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_principal.principal_kind <> 'integration'
               OR v_principal.principal_plane <> 'tenant'
            THEN
                RAISE EXCEPTION
                    'Integration authority requires a tenant INTEGRATION Principal'
                    USING ERRCODE = '23514';
            END IF;
            IF p_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Integration authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT active, authority_revision
              INTO v_active, v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id
             FOR UPDATE;
            IF NOT v_active THEN
                RAISE EXCEPTION
                    'Suspended or revoked integrations cannot receive authority'
                    USING ERRCODE = '55000';
            END IF;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Integration authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(COALESCE(p_desired_capabilities, ARRAY[]::text[])) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(COALESCE(p_desired_capabilities, ARRAY[]::text[])) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(
                                COALESCE(p_desired_capabilities, ARRAY[]::text[])
                            ) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Desired integration authority is invalid'
                    USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
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
                        'Desired authority exceeds the integration operational ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE organization_id = v_org_id
               AND principal_id = p_principal_id
               AND status = 'active'
               AND NOT (
                   capability_key = ANY(
                       COALESCE(p_desired_capabilities, ARRAY[]::text[])
                   )
               );

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = p_principal_id
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    INSERT INTO request_engine.principal_authority_grants (
                        organization_id,
                        principal_id,
                        principal_plane,
                        authority_plane,
                        capability_key,
                        delegable,
                        granted_by_principal_id,
                        provenance_kind,
                        provenance_reference
                    ) VALUES (
                        v_org_id,
                        p_principal_id,
                        'tenant',
                        'operational',
                        v_capability,
                        false,
                        v_actor_id,
                        'integration_authority_management',
                        btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;

            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_current_revision;
        END
        $$;


ALTER FUNCTION request_engine.replace_integration_authority_state(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: replace_staff_authority(uuid, bigint, text[], text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_target_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_current_revision bigint;
            v_capability text;
            v_plane text;
            v_target_is_controller boolean;
            v_desired_is_controller boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_authority'
            );
            SELECT membership.principal_id
              INTO v_target_id
              FROM request_engine.staff_memberships AS membership
             WHERE membership.id = p_membership_id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Active Staff membership not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_target_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff authority self-replacement is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = v_target_id
             FOR UPDATE;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Staff authority revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0
               OR EXISTS (
                   SELECT 1
                     FROM unnest(COALESCE(p_desired_capabilities, ARRAY[]::text[])) AS cap
                    WHERE length(btrim(cap)) = 0
               )
               OR cardinality(COALESCE(p_desired_capabilities, ARRAY[]::text[])) <>
                  cardinality(
                      ARRAY(
                          SELECT DISTINCT cap
                            FROM unnest(
                                COALESCE(p_desired_capabilities, ARRAY[]::text[])
                            ) AS cap
                      )
                  )
            THEN
                RAISE EXCEPTION 'Desired Staff authority is invalid'
                    USING ERRCODE = '22023';
            END IF;

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                SELECT authority_plane INTO v_plane
                  FROM request_engine.principal_authority_grants
                 WHERE organization_id = v_org_id
                   AND principal_id = v_actor_id
                   AND capability_key = v_capability
                   AND status = 'active'
                   AND delegable
                 FOR SHARE;
                IF NOT FOUND OR v_plane = 'platform' THEN
                    RAISE EXCEPTION 'Desired authority exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            SELECT (
                SELECT count(DISTINCT capability_key) = 3
                  FROM request_engine.principal_authority_grants
                 WHERE principal_id = v_target_id
                   AND status = 'active'
                   AND capability_key IN (
                       'staff.manage_membership',
                       'staff.manage_authority',
                       'identity.bind'
                   )
            ) INTO v_target_is_controller;
            SELECT (
                SELECT count(DISTINCT cap) = 3
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
                 WHERE cap IN (
                     'staff.manage_membership',
                     'staff.manage_authority',
                     'identity.bind'
                 )
            ) INTO v_desired_is_controller;
            IF v_target_is_controller AND NOT v_desired_is_controller THEN
                PERFORM request_engine.assert_other_tenant_controller(v_target_id);
            END IF;

            UPDATE request_engine.principal_authority_grants
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE organization_id = v_org_id
               AND principal_id = v_target_id
               AND status = 'active'
               AND NOT (
                   capability_key = ANY(
                       COALESCE(p_desired_capabilities, ARRAY[]::text[])
                   )
               );

            FOR v_capability IN
                SELECT cap
                  FROM unnest(
                      COALESCE(p_desired_capabilities, ARRAY[]::text[])
                  ) AS cap
            LOOP
                IF NOT EXISTS (
                    SELECT 1
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = v_target_id
                       AND capability_key = v_capability
                       AND status = 'active'
                ) THEN
                    SELECT authority_plane INTO v_plane
                      FROM request_engine.principal_authority_grants
                     WHERE principal_id = v_actor_id
                       AND organization_id = v_org_id
                       AND capability_key = v_capability
                       AND status = 'active'
                       AND delegable;
                    INSERT INTO request_engine.principal_authority_grants (
                        organization_id,
                        principal_id,
                        principal_plane,
                        authority_plane,
                        capability_key,
                        delegable,
                        granted_by_principal_id,
                        provenance_kind,
                        provenance_reference
                    ) VALUES (
                        v_org_id,
                        v_target_id,
                        'tenant',
                        v_plane,
                        v_capability,
                        false,
                        v_actor_id,
                        'authority_management',
                        btrim(p_provenance_reference)
                    );
                END IF;
            END LOOP;
            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = v_target_id;
            RETURN v_current_revision;
        END
        $$;


ALTER FUNCTION request_engine.replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) OWNER TO request_engine_schema_owner;

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
-- Name: revoke_delegation(uuid, bigint, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.revoke_delegation(p_id uuid, p_expected_revision bigint, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_delegator uuid;
            v_status text;
            v_delegate uuid;
            v_revision bigint;
        BEGIN
            v_actor_id := current_setting(
                'request_engine.authenticated_principal_id', true
            )::uuid;
            SELECT delegator_principal_id, status, delegate_principal_id, revision
              INTO v_delegator, v_status, v_delegate, v_revision
              FROM request_engine.delegations
             WHERE id = p_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Delegation not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_actor_id IS NULL
               OR v_actor_id NOT IN (v_delegator, v_delegate)
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Only the delegator or delegate may revoke'
                    USING ERRCODE = '42501';
            END IF;
            IF v_status <> 'active' THEN
                RAISE EXCEPTION 'Delegation is already revoked'
                    USING ERRCODE = '55000';
            END IF;
            IF v_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Delegation revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            UPDATE request_engine.delegations
               SET status = 'revoked',
                   revision = revision + 1,
                   revoked_at = clock_timestamp(),
                   revoked_by_principal_id = v_actor_id
             WHERE id = p_id;
            RETURN p_expected_revision + 1;
        END
        $$;


ALTER FUNCTION request_engine.revoke_delegation(p_id uuid, p_expected_revision bigint, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: revoke_webauthn_credentials_on_disable(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.revoke_webauthn_credentials_on_disable() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF NEW.status = 'disabled' AND OLD.status <> 'disabled' THEN
                UPDATE request_engine.webauthn_credentials
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE native_identity_id = NEW.id
                   AND status = 'active';
            END IF;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.revoke_webauthn_credentials_on_disable() OWNER TO request_engine_schema_owner;

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
-- Name: seed_initial_controller_policy(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.seed_initial_controller_policy() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_grants jsonb;
        BEGIN
            IF NEW.initial_controller_policy_key IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT grants INTO STRICT v_grants
              FROM request_engine.initial_controller_policies
             WHERE policy_key = NEW.initial_controller_policy_key;
            IF EXISTS (
                SELECT 1 FROM jsonb_to_recordset(v_grants)
                    AS g(capability_key text, authority_plane text, delegable boolean)
                 WHERE g.capability_key IS NULL OR btrim(g.capability_key) = ''
                    OR g.capability_key LIKE '%*%' OR g.authority_plane IS NULL
                    OR g.authority_plane NOT IN ('tenant_control', 'operational')
                    OR g.delegable IS NULL
            ) THEN
                RAISE EXCEPTION 'Invalid initial controller policy' USING ERRCODE = '23514';
            END IF;
            PERFORM set_config('request_engine.organization_id', NEW.organization_id::text, true);
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            )
            SELECT NEW.organization_id, NEW.controller_principal_id, 'tenant', g.authority_plane,
                   g.capability_key, g.delegable, NEW.provisioned_by_principal_id, 'provisioning',
                   'policy:' || NEW.initial_controller_policy_key
                       || ';root:' || NEW.provenance_reference
              FROM jsonb_to_recordset(v_grants)
                AS g(capability_key text, authority_plane text, delegable boolean);
            RETURN NEW;
        END $$;


ALTER FUNCTION request_engine.seed_initial_controller_policy() OWNER TO request_engine_schema_owner;

--
-- Name: seed_root_staff_membership(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.seed_root_staff_membership() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_grant record;
        BEGIN
            PERFORM set_config(
                'request_engine.organization_id',
                NEW.organization_id::text,
                true
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
                provenance_reference,
                activated_at
            ) VALUES (
                gen_random_uuid(),
                NEW.organization_id,
                NEW.controller_principal_id,
                NEW.controller_binding_id,
                NEW.organization_party_id,
                'active',
                NEW.provisioned_by_principal_id,
                'root_provisioning',
                NEW.provenance_reference,
                clock_timestamp()
            );

            FOR v_grant IN
                SELECT *
                  FROM request_engine.principal_authority_grants
                 WHERE principal_id = NEW.controller_principal_id
                   AND organization_id = NEW.organization_id
                   AND authority_plane = 'tenant_control'
                   AND status = 'active'
                   AND NOT delegable
                 FOR UPDATE
            LOOP
                UPDATE request_engine.principal_authority_grants
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp(),
                       revoked_by_principal_id = NEW.provisioned_by_principal_id
                 WHERE id = v_grant.id;
                INSERT INTO request_engine.principal_authority_grants (
                    organization_id,
                    principal_id,
                    principal_plane,
                    authority_plane,
                    capability_key,
                    delegable,
                    granted_by_principal_id,
                    provenance_kind,
                    provenance_reference
                ) VALUES (
                    NEW.organization_id,
                    NEW.controller_principal_id,
                    'tenant',
                    v_grant.authority_plane,
                    v_grant.capability_key,
                    true,
                    v_grant.granted_by_principal_id,
                    'provisioning',
                    concat(NEW.provenance_reference, '-root-delegable')
                );
            END LOOP;
            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.seed_root_staff_membership() OWNER TO request_engine_schema_owner;

--
-- Name: seed_root_staff_read_authority(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.seed_root_staff_read_authority() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM set_config('request_engine.organization_id', NEW.organization_id::text, true);
            INSERT INTO request_engine.principal_authority_grants (
                organization_id, principal_id, principal_plane, authority_plane,
                capability_key, delegable, granted_by_principal_id,
                provenance_kind, provenance_reference
            ) VALUES (
                NEW.organization_id, NEW.controller_principal_id, 'tenant', 'tenant_control',
                'staff.read', true, NEW.provisioned_by_principal_id,
                'provisioning', concat(NEW.provenance_reference, '-staff-inspection-v1')
            );
            RETURN NEW;
        END $$;


ALTER FUNCTION request_engine.seed_root_staff_read_authority() OWNER TO request_engine_schema_owner;

--
-- Name: set_integration_status(uuid, bigint, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.set_integration_status(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            DECLARE
                v_actor uuid;
                v_revision bigint;
                v_before bigint;
                v_capability text := CASE WHEN p_target_status = 'active' THEN 'integration.provision' ELSE 'integration.suspend' END;
            BEGIN
                PERFORM request_engine.acquire_identity_topology_share();
                v_actor := request_engine.assert_staff_manager(v_capability);
                IF p_provenance_reference IS NULL
                   OR length(btrim(p_provenance_reference)) NOT BETWEEN 1 AND 500 THEN
                    RAISE EXCEPTION 'Integration provenance is required'
                        USING ERRCODE = '22023';
                END IF;
                
                IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                    RAISE EXCEPTION 'Invalid integration revision' USING ERRCODE = '22023';
                END IF;
            
                IF 'status_transition' <> 'provision' THEN
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
                v_revision := request_engine.set_integration_status_state(p_principal_id, p_expected_revision, p_target_status, p_provenance_reference);
                IF 'status_transition' = 'authority_replace' AND v_revision = v_before THEN
                    UPDATE request_engine.principals
                       SET authority_revision = authority_revision + 1
                     WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
                END IF;
                PERFORM request_engine.append_integration_fact(
                    p_principal_id, v_actor, 'status_transition', p_provenance_reference, v_capability
                );
                RETURN v_revision;
            END $$;


ALTER FUNCTION request_engine.set_integration_status(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: set_integration_status_state(uuid, bigint, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.set_integration_status_state(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_principal record;
            v_active boolean;
            v_binding_status text;
            v_workload_identity_id uuid;
            v_current_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_target_status = 'active' THEN
                v_actor_id := request_engine.assert_staff_manager(
                    'integration.provision'
                );
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                v_actor_id := request_engine.assert_staff_manager(
                    'integration.suspend'
                );
            ELSE
                RAISE EXCEPTION 'Unsupported integration target status'
                    USING ERRCODE = '22023';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            SELECT pr.active, pr.authority_revision,
                   b.status, wi.id
              INTO v_active, v_current_revision,
                   v_binding_status, v_workload_identity_id
              FROM request_engine.principals pr
              LEFT JOIN request_engine.identity_bindings b
                ON b.principal_id = pr.id
               AND b.status <> 'revoked'
              LEFT JOIN request_engine.workload_identities wi
                ON wi.id::text = b.subject_id
             WHERE pr.id = p_principal_id
               AND pr.principal_kind = 'integration'
               AND pr.principal_plane = 'tenant'
               AND pr.organization_id = v_org_id
             FOR UPDATE OF pr;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration Principal not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF p_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Integration self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF v_current_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Integration revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            v_binding_status := COALESCE(v_binding_status, 'revoked');
            IF NOT (
                (v_binding_status = 'pending'
                    AND p_target_status IN ('active', 'revoked'))
                OR (v_binding_status = 'active'
                    AND p_target_status IN ('suspended', 'revoked'))
                OR (v_binding_status = 'suspended'
                    AND p_target_status IN ('active', 'revoked'))
            ) THEN
                RAISE EXCEPTION 'Invalid integration state transition'
                    USING ERRCODE = '55000';
            END IF;
            IF p_target_status = 'active' THEN                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = p_principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
            ELSIF p_target_status = 'suspended' THEN
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = p_principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended',
                       revision = revision + 1
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
            ELSE
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = p_principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE principal_id = p_principal_id
                   AND status <> 'revoked';
                UPDATE request_engine.workload_credentials
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE workload_identity_id = v_workload_identity_id
                   AND status = 'active';
                UPDATE request_engine.workload_identities
                   SET status = 'disabled',
                       revision = revision + 1,
                       disabled_at = clock_timestamp()
                 WHERE id = v_workload_identity_id
                   AND status = 'active';
            END IF;

            SELECT authority_revision
              INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_principal_id;
            RETURN v_current_revision;
        END
        $$;


ALTER FUNCTION request_engine.set_integration_status_state(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) OWNER TO request_engine_schema_owner;

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
-- Name: transition_agent_profile(uuid, bigint, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.transition_agent_profile(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_profile request_engine.agent_profiles%ROWTYPE;
            v_new_revision bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_target_status = 'active' THEN
                v_actor_id := request_engine.assert_staff_manager('agent.provision');
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                v_actor_id := request_engine.assert_staff_manager('agent.suspend');
            ELSE
                RAISE EXCEPTION 'Unsupported agent profile target status'
                    USING ERRCODE = '22023';
            END IF;
            SELECT * INTO v_profile
              FROM request_engine.agent_profiles
             WHERE principal_id = p_principal_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent profile not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_profile.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Agent self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF v_profile.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Agent profile revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            IF NOT (
                (v_profile.status = 'pending'
                    AND p_target_status IN ('active', 'revoked'))
                OR (v_profile.status = 'active'
                    AND p_target_status IN ('suspended', 'revoked'))
                OR (v_profile.status = 'suspended'
                    AND p_target_status IN ('active', 'revoked'))
            ) THEN
                RAISE EXCEPTION 'Invalid agent profile state transition'
                    USING ERRCODE = '55000';
            END IF;
            v_new_revision := v_profile.revision + 1;

            IF p_target_status = 'active' THEN
                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = v_profile.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE principal_id = v_profile.principal_id
                   AND subject_id = v_profile.workload_identity_id::text
                   AND status <> 'revoked';
            ELSIF p_target_status = 'suspended' THEN
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_profile.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'suspended',
                       revision = revision + 1
                 WHERE principal_id = v_profile.principal_id
                   AND subject_id = v_profile.workload_identity_id::text
                   AND status <> 'revoked';
            ELSE
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_profile.principal_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE principal_id = v_profile.principal_id
                   AND subject_id = v_profile.workload_identity_id::text
                   AND status <> 'revoked';
                UPDATE request_engine.workload_credentials
                   SET status = 'revoked',
                       revision = revision + 1,
                       revoked_at = clock_timestamp()
                 WHERE workload_identity_id = v_profile.workload_identity_id
                   AND status = 'active';
                UPDATE request_engine.workload_identities
                   SET status = 'disabled',
                       revision = revision + 1,
                       disabled_at = clock_timestamp()
                 WHERE id = v_profile.workload_identity_id
                   AND status = 'active';
            END IF;

            UPDATE request_engine.agent_profiles
               SET status = p_target_status,
                   revision = v_new_revision,
                   suspended_at = CASE
                       WHEN p_target_status = 'suspended'
                       THEN clock_timestamp()
                       ELSE suspended_at
                   END,
                   revoked_at = CASE
                       WHEN p_target_status = 'revoked'
                       THEN clock_timestamp()
                       ELSE NULL
                   END
             WHERE principal_id = p_principal_id;
            RETURN v_new_revision;
        END
        $$;


ALTER FUNCTION request_engine.transition_agent_profile(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: transition_identity_binding(uuid, bigint, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.transition_identity_binding(p_binding_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_binding request_engine.identity_bindings%ROWTYPE;
            v_was_controller boolean;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager('identity.bind');
            SELECT * INTO v_binding
              FROM request_engine.identity_bindings
             WHERE id = p_binding_id
               AND organization_id = v_org_id
               AND principal_plane = 'tenant'
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity binding not found'
                    USING ERRCODE = 'P0002';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'A positive Identity binding revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF v_binding.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity binding revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;
            IF p_target_status = 'suspended' THEN
                IF v_binding.status <> 'active' THEN
                    RAISE EXCEPTION 'Identity binding cannot be suspended'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF p_target_status = 'active' THEN
                IF v_binding.status <> 'suspended' THEN
                    RAISE EXCEPTION 'Identity binding cannot be reactivated'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF p_target_status = 'revoked' THEN
                IF v_binding.status NOT IN ('pending', 'active', 'suspended') THEN
                    RAISE EXCEPTION 'Identity binding cannot be revoked'
                        USING ERRCODE = '55000';
                END IF;
            ELSE
                RAISE EXCEPTION 'Unsupported Identity binding target status'
                    USING ERRCODE = '22023';
            END IF;

            v_was_controller := request_engine.principal_is_effective_tenant_controller(
                v_org_id, v_binding.principal_id
            );

            UPDATE request_engine.identity_bindings
               SET status = p_target_status,
                   revision = revision + 1,
                   revoked_at = CASE
                       WHEN p_target_status = 'revoked'
                       THEN clock_timestamp()
                       ELSE NULL
                   END
             WHERE id = p_binding_id
               AND organization_id = v_org_id;

            IF v_was_controller AND p_target_status IN ('suspended', 'revoked') THEN
                PERFORM request_engine.assert_tenant_has_controller();
            END IF;
            RETURN p_expected_revision + 1;
        END
        $$;


ALTER FUNCTION request_engine.transition_identity_binding(p_binding_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: transition_staff_membership(uuid, bigint, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_membership request_engine.staff_memberships%ROWTYPE;
            v_native_identity_id uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager(
                'staff.manage_membership'
            );
            SELECT * INTO v_membership
              FROM request_engine.staff_memberships
             WHERE id = p_membership_id
               AND organization_id = v_org_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Staff membership not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_membership.principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Staff membership self-transition is forbidden'
                    USING ERRCODE = '42501';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1 THEN
                RAISE EXCEPTION 'A positive Staff membership revision is required'
                    USING ERRCODE = '22023';
            END IF;
            IF v_membership.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Staff membership revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_provenance_reference IS NULL OR length(btrim(p_provenance_reference)) = 0 THEN
                RAISE EXCEPTION 'Transition provenance is required'
                    USING ERRCODE = '22023';
            END IF;

            IF p_target_status = 'active' THEN
                IF v_membership.status NOT IN ('invited', 'suspended') THEN
                    RAISE EXCEPTION 'Staff membership cannot be activated'
                        USING ERRCODE = '55000';
                END IF;
                UPDATE request_engine.principals
                   SET active = true
                 WHERE id = v_membership.principal_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.identity_bindings
                   SET status = 'active',
                       revision = revision + 1
                 WHERE id = v_membership.identity_binding_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.staff_memberships
                   SET status = 'active',
                       revision = revision + 1,
                       activated_at = COALESCE(activated_at, clock_timestamp()),
                       suspended_at = NULL
                 WHERE id = p_membership_id
                   AND organization_id = v_org_id;
            ELSIF p_target_status IN ('suspended', 'revoked') THEN
                IF (p_target_status = 'suspended' AND v_membership.status <> 'active')
                   OR (p_target_status = 'revoked'
                       AND v_membership.status NOT IN ('invited', 'active', 'suspended')) THEN
                    RAISE EXCEPTION 'Staff membership cannot make this terminal transition'
                        USING ERRCODE = '55000';
                END IF;
                IF (
                    SELECT count(DISTINCT capability_key)
                      FROM request_engine.principal_authority_grants
                     WHERE organization_id = v_org_id
                       AND principal_id = v_membership.principal_id
                       AND status = 'active'
                       AND capability_key IN (
                           'staff.manage_membership',
                           'staff.manage_authority',
                           'identity.bind'
                       )
                ) = 3 THEN
                    PERFORM request_engine.assert_other_tenant_controller(
                        v_membership.principal_id
                    );
                END IF;
                UPDATE request_engine.principals
                   SET active = false
                 WHERE id = v_membership.principal_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.identity_bindings
                   SET status = p_target_status,
                       revision = revision + 1,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = v_membership.identity_binding_id
                   AND organization_id = v_org_id;
                UPDATE request_engine.staff_memberships
                   SET status = p_target_status,
                       revision = revision + 1,
                       suspended_at = CASE
                           WHEN p_target_status = 'suspended'
                           THEN clock_timestamp()
                           ELSE suspended_at
                       END,
                       revoked_at = CASE
                           WHEN p_target_status = 'revoked'
                           THEN clock_timestamp()
                           ELSE NULL
                       END
                 WHERE id = p_membership_id
                   AND organization_id = v_org_id;

                SELECT binding.subject_id::uuid INTO v_native_identity_id
                  FROM request_engine.identity_bindings AS binding
                  JOIN request_engine.identity_authorities AS authority
                    ON authority.id = binding.identity_authority_id
                 WHERE binding.id = v_membership.identity_binding_id
                   AND binding.organization_id = v_org_id
                   AND authority.kind = 'native';
                IF v_native_identity_id IS NOT NULL THEN
                    PERFORM request_auth.revoke_native_sessions(
                        v_native_identity_id,
                        'staff_' || p_target_status
                    );
                END IF;
            ELSE
                RAISE EXCEPTION 'Unsupported Staff membership target status'
                    USING ERRCODE = '22023';
            END IF;
            RETURN p_expected_revision + 1;
        END
        $$;


ALTER FUNCTION request_engine.transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: upgrade_controller_policy(uuid, text, text, bigint, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.upgrade_controller_policy(p_target_principal_id uuid, p_source_policy_key text, p_target_policy_key text, p_expected_authority_revision bigint, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_target_grants jsonb;
            v_current_revision bigint;
            v_root_controller_id uuid;
            v_root_policy_key text;
            v_grant record;
            v_actor_plane text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor_id := request_engine.assert_staff_manager(
                'controller_policy_upgrade'
            );

            IF p_target_principal_id IS NULL
               OR p_target_policy_key IS NULL
               OR length(btrim(p_target_policy_key)) = 0
               OR p_expected_authority_revision IS NULL
               OR p_expected_authority_revision < 1
               OR p_provenance_reference IS NULL
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Controller policy upgrade input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT grants INTO v_target_grants
              FROM request_engine.initial_controller_policies
             WHERE policy_key = p_target_policy_key;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Unknown controller policy'
                    USING ERRCODE = '22023';
            END IF;

            IF p_source_policy_key IS NOT NULL
               AND length(btrim(p_source_policy_key)) > 0
            THEN
                SELECT root_fact.controller_principal_id,
                       root_fact.initial_controller_policy_key
                  INTO v_root_controller_id, v_root_policy_key
                  FROM request_engine.organization_root_provisioning_facts AS root_fact
                 WHERE root_fact.organization_id = v_org_id;
                IF v_root_controller_id = p_target_principal_id
                   AND v_root_policy_key IS NOT NULL
                   AND v_root_policy_key IS DISTINCT FROM btrim(p_source_policy_key)
                THEN
                    RAISE EXCEPTION 'Controller policy source assertion is stale'
                        USING ERRCODE = '40001';
                END IF;
            END IF;

            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_target_principal_id
               AND organization_id = v_org_id
               AND principal_plane = 'tenant'
               AND active
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Target Principal is not visible in this tenant'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_current_revision <> p_expected_authority_revision THEN
                RAISE EXCEPTION 'Controller policy revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF p_target_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'Controller policy self-upgrade is forbidden'
                    USING ERRCODE = '42501';
            END IF;

            IF EXISTS (
                SELECT 1
                  FROM jsonb_to_recordset(v_target_grants)
                    AS g(capability_key text, authority_plane text, delegable boolean)
                 WHERE EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS revoked
                            WHERE revoked.organization_id = v_org_id
                              AND revoked.principal_id = p_target_principal_id
                              AND revoked.capability_key = g.capability_key
                              AND revoked.status = 'revoked'
                       )
                   AND NOT EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS active
                            WHERE active.organization_id = v_org_id
                              AND active.principal_id = p_target_principal_id
                              AND active.capability_key = g.capability_key
                              AND active.status = 'active'
                       )
            ) THEN
                RAISE EXCEPTION 'Controller policy upgrade cannot restore revoked authority'
                    USING ERRCODE = '23514';
            END IF;

            FOR v_grant IN
                SELECT g.capability_key
                  FROM jsonb_to_recordset(v_target_grants)
                    AS g(capability_key text, authority_plane text, delegable boolean)
                 WHERE NOT EXISTS (
                           SELECT 1
                             FROM request_engine.principal_authority_grants AS active
                            WHERE active.organization_id = v_org_id
                              AND active.principal_id = p_target_principal_id
                              AND active.capability_key = g.capability_key
                              AND active.status = 'active'
                       )
            LOOP
                SELECT grant_row.authority_plane INTO v_actor_plane
                  FROM request_engine.principal_authority_grants AS grant_row
                 WHERE grant_row.organization_id = v_org_id
                   AND grant_row.principal_id = v_actor_id
                   AND grant_row.capability_key = v_grant.capability_key
                   AND grant_row.status = 'active'
                   AND grant_row.delegable
                 FOR SHARE;
                IF NOT FOUND OR v_actor_plane = 'platform' THEN
                    RAISE EXCEPTION 'Controller policy upgrade exceeds delegable ceiling'
                        USING ERRCODE = '42501';
                END IF;
            END LOOP;

            INSERT INTO request_engine.principal_authority_grants (
                organization_id,
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            )
            SELECT v_org_id,
                   p_target_principal_id,
                   'tenant',
                   g.authority_plane,
                   g.capability_key,
                   false,
                   v_actor_id,
                   'controller_policy_upgrade',
                   btrim(p_provenance_reference)
              FROM jsonb_to_recordset(v_target_grants)
                AS g(capability_key text, authority_plane text, delegable boolean)
             WHERE NOT EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS active
                        WHERE active.organization_id = v_org_id
                          AND active.principal_id = p_target_principal_id
                          AND active.capability_key = g.capability_key
                          AND active.status = 'active'
                   );

            SELECT authority_revision INTO v_current_revision
              FROM request_engine.principals
             WHERE id = p_target_principal_id;
            RETURN v_current_revision;
        END
        $$;


ALTER FUNCTION request_engine.upgrade_controller_policy(p_target_principal_id uuid, p_source_policy_key text, p_target_policy_key text, p_expected_authority_revision bigint, p_provenance_reference text) OWNER TO request_engine_schema_owner;

--
-- Name: upsert_agent_policy(uuid, text[], text[], text, integer, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.upsert_agent_policy(p_agent_principal_id uuid, p_allowed_capabilities text[], p_denied_capabilities text[], p_risk_ceiling text, p_max_mutations_per_minute integer, p_provenance_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid := request_engine.current_organization_id();
            v_profile_status text;
            v_revision bigint;
            v_capability text;
        BEGIN
            v_actor_id := request_engine.assert_staff_manager(
                'agent.manage_policy'
            );
            FOREACH v_capability IN ARRAY p_allowed_capabilities
            LOOP
                IF v_capability IS NULL
                   OR length(btrim(v_capability)) = 0
                   OR length(v_capability) > 200
                THEN
                    RAISE EXCEPTION 'Invalid agent policy capability key'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;
            FOREACH v_capability IN ARRAY p_denied_capabilities
            LOOP
                IF v_capability IS NULL
                   OR length(btrim(v_capability)) = 0
                   OR length(v_capability) > 200
                THEN
                    RAISE EXCEPTION 'Invalid agent policy capability key'
                        USING ERRCODE = '22023';
                END IF;
            END LOOP;
            IF p_agent_principal_id = v_actor_id
               OR p_risk_ceiling NOT IN (
                    'read',
                    'low_impact_write',
                    'reversible_write',
                    'external_commitment',
                    'sensitive_data',
                    'financial',
                    'destructive'
               )
               OR p_max_mutations_per_minute IS NULL
               OR p_max_mutations_per_minute <= 0
               OR p_allowed_capabilities && p_denied_capabilities
               OR length(btrim(p_provenance_reference)) = 0
            THEN
                RAISE EXCEPTION 'Invalid agent policy input'
                    USING ERRCODE = '22023';
            END IF;

            SELECT status
              INTO v_profile_status
              FROM request_engine.agent_profiles
             WHERE principal_id = p_agent_principal_id
             FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Agent profile not found' USING ERRCODE = 'P0002';
            END IF;
            IF v_profile_status NOT IN ('pending', 'active') THEN
                RAISE EXCEPTION 'Suspended or revoked agents cannot receive policy'
                    USING ERRCODE = '55000';
            END IF;

            INSERT INTO request_engine.agent_policies (
                organization_id,
                agent_principal_id,
                allowed_capabilities,
                denied_capabilities,
                risk_ceiling,
                max_mutations_per_minute,
                provenance_reference
            ) VALUES (
                v_org_id,
                p_agent_principal_id,
                p_allowed_capabilities,
                p_denied_capabilities,
                p_risk_ceiling,
                p_max_mutations_per_minute,
                p_provenance_reference
            )
            ON CONFLICT (organization_id, agent_principal_id)
            DO UPDATE SET
                allowed_capabilities = EXCLUDED.allowed_capabilities,
                denied_capabilities = EXCLUDED.denied_capabilities,
                risk_ceiling = EXCLUDED.risk_ceiling,
                max_mutations_per_minute = EXCLUDED.max_mutations_per_minute,
                provenance_reference = EXCLUDED.provenance_reference,
                policy_revision = request_engine.agent_policies.policy_revision + 1,
                updated_at = clock_timestamp()
            RETURNING policy_revision INTO v_revision;
            RETURN v_revision;
        END
        $$;


ALTER FUNCTION request_engine.upsert_agent_policy(p_agent_principal_id uuid, p_allowed_capabilities text[], p_denied_capabilities text[], p_risk_ceiling text, p_max_mutations_per_minute integer, p_provenance_reference text) OWNER TO request_engine_schema_owner;

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
-- Name: activate_platform_configuration(text, bigint, bigint, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.activate_platform_configuration(p_configuration_kind text, p_revision bigint, p_expected_active_revision bigint, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(configuration_revision_id uuid, revision bigint, state text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_target record;
            v_previous record;
        BEGIN
            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_configuration_actor(
                  'platform.configuration.activate'
              );

            IF p_configuration_kind !~ '^[a-z][a-z0-9_.-]{1,79}$'
               OR p_revision IS NULL
               OR p_revision < 1
               OR (
                   p_expected_active_revision IS NOT NULL
                   AND p_expected_active_revision < 1
               )
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$'
            THEN
                RAISE EXCEPTION 'Platform configuration activation input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            PERFORM pg_catalog.pg_advisory_xact_lock(
                pg_catalog.hashtextextended(
                    'p7/idempotency/'
                    || v_actor_id::text
                    || '/platform.configuration.activate/'
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
               AND fact.capability_key = 'platform.configuration.activate'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;

            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key conflicts with another activation intent'
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
                revision_row.revision,
                revision_row.secret_binding_id
              INTO v_previous
              FROM request_engine.platform_configuration_revisions AS revision_row
             WHERE revision_row.configuration_kind = p_configuration_kind
               AND revision_row.state = 'active'
             FOR UPDATE;

            IF p_expected_active_revision IS NULL THEN
                IF FOUND THEN
                    RAISE EXCEPTION
                        'Platform configuration active revision changed'
                        USING ERRCODE = '40001';
                END IF;
            ELSIF NOT FOUND
               OR v_previous.revision <> p_expected_active_revision
            THEN
                RAISE EXCEPTION
                    'Platform configuration active revision changed'
                    USING ERRCODE = '40001';
            END IF;

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

            IF v_target.state <> 'validated' THEN
                RAISE EXCEPTION
                    'Platform configuration revision requires validation'
                    USING ERRCODE = '40001';
            END IF;

            IF v_previous.id IS NOT NULL THEN
                UPDATE request_engine.platform_configuration_revisions
                   SET state = 'superseded'
                 WHERE id = v_previous.id;

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
                    capability_key
                ) VALUES (
                    'superseded',
                    v_previous.id,
                    p_configuration_kind,
                    v_previous.revision,
                    v_previous.secret_binding_id,
                    v_actor_id,
                    v_actor_method,
                    v_correlation_id,
                    jsonb_build_object(
                        'result_state',
                        'superseded',
                        'superseded_by_revision',
                        p_revision
                    ),
                    'platform.configuration.activate'
                );
            END IF;

            UPDATE request_engine.platform_configuration_revisions
               SET state = 'active',
                   activated_at = clock_timestamp()
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
                'activated',
                v_target.id,
                p_configuration_kind,
                p_revision,
                v_target.secret_binding_id,
                v_actor_id,
                v_actor_method,
                v_correlation_id,
                jsonb_build_object(
                    'previous_active_revision',
                    p_expected_active_revision,
                    'result_state',
                    'active'
                ),
                'platform.configuration.activate',
                p_idempotency_key_digest,
                p_intent_digest
            );

            PERFORM pg_catalog.pg_notify(
                'request_engine_platform_configuration',
                jsonb_build_object(
                    'configuration_kind',
                    p_configuration_kind,
                    'revision',
                    p_revision,
                    'state',
                    'active'
                )::text
            );

            RETURN QUERY
            SELECT v_target.id, p_revision, 'active'::text;
        END
        $_$;


ALTER FUNCTION request_platform.activate_platform_configuration(p_configuration_kind text, p_revision bigint, p_expected_active_revision bigint, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: activate_platform_owner_invitation(uuid, uuid, uuid, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.activate_platform_owner_invitation(p_invitation_id uuid, p_principal_id uuid, p_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(principal_id uuid, binding_id uuid, invitation_revision bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_invitation record;
            v_instance record;
            v_created uuid;
            v_revision_before bigint;
        BEGIN
            SELECT actor_id
              INTO v_actor_id
              FROM request_platform.assert_platform_owner_actor(
                  'platform.owner.provision'
              );

            SELECT invitation.id, invitation.status, invitation.revision,
                   invitation.native_identity_id, invitation.provenance_reference
              INTO v_invitation
              FROM request_engine.platform_owner_invitations AS invitation
             WHERE invitation.id = p_invitation_id
             FOR UPDATE;
            IF NOT FOUND OR v_invitation.status NOT IN ('enrolled', 'consumed') THEN
                RAISE EXCEPTION 'Platform Owner invitation is not activatable'
                    USING ERRCODE = '22023';
            END IF;

            IF v_invitation.status = 'consumed' THEN
                SELECT fact.principal_id INTO v_created
                  FROM request_engine.platform_owner_provisioning_facts AS fact
                 WHERE fact.native_identity_id = v_invitation.native_identity_id
                 ORDER BY fact.created_at DESC
                 LIMIT 1;
                IF v_created IS NULL THEN
                    RAISE EXCEPTION 'Consumed invitation has no owner authority fact'
                        USING ERRCODE = '55000';
                END IF;
                SELECT binding.id
                  INTO p_binding_id
                  FROM request_engine.identity_bindings AS binding
                 WHERE binding.principal_id = v_created
                   AND binding.principal_plane = 'platform'
                 ORDER BY binding.id
                 LIMIT 1;
                RETURN QUERY SELECT v_created, p_binding_id, v_invitation.revision;
                RETURN;
            END IF;

            SELECT instance.built_in_native_authority_id
              INTO v_instance
              FROM request_engine.platform_instance AS instance
             WHERE instance.singleton_key = 1
               AND instance.state = 'claimed';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Platform instance is unavailable'
                    USING ERRCODE = '55000';
            END IF;

            v_created := request_platform.provision_native_platform_owner(
                p_principal_id,
                p_binding_id,
                v_instance.built_in_native_authority_id,
                v_invitation.native_identity_id,
                'owner-invitation:' || v_invitation.id::text || ':'
                    || v_invitation.provenance_reference,
                p_idempotency_key_digest,
                p_intent_digest
            );

            v_revision_before := v_invitation.revision;
            UPDATE request_engine.platform_owner_invitations
               SET status = 'consumed',
                   revision = revision + 1,
                   consumed_at = clock_timestamp()
             WHERE id = v_invitation.id
            RETURNING revision INTO v_invitation.revision;

            INSERT INTO request_engine.platform_owner_invitation_facts (
                invitation_id, action, actor_principal_id, native_identity_id,
                revision_before, revision_after, correlation_id
            ) VALUES (
                v_invitation.id,
                'activate',
                v_actor_id,
                v_invitation.native_identity_id,
                v_revision_before,
                v_invitation.revision,
                NULLIF(current_setting('request_engine.correlation_id', true), '')::uuid
            );

            RETURN QUERY SELECT v_created, p_binding_id, v_invitation.revision;
        END
        $$;


ALTER FUNCTION request_platform.activate_platform_owner_invitation(p_invitation_id uuid, p_principal_id uuid, p_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: approve_identity_recovery_case(uuid, bigint, text, text, text); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.approve_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) RETURNS TABLE(case_id uuid, target_native_identity_id uuid, status text, delivery_status text, revision bigint, issuance_generation integer, approval_expires_at timestamp with time zone, proof_expires_at timestamp with time zone, created_at timestamp with time zone, approved_at timestamp with time zone, issued_at timestamp with time zone, consumed_at timestamp with time zone, revoked_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor_id uuid;
            v_actor_method text;
            v_correlation_id uuid;
            v_replay record;
            v_case record;
            v_identity_status text;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_case_id IS NULL OR p_expected_revision IS NULL
               OR p_expected_revision < 1
               OR p_reason_code IS NULL
               OR length(btrim(p_reason_code)) NOT BETWEEN 1 AND 80
               OR p_idempotency_key_digest IS NULL
               OR p_idempotency_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest IS NULL
               OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Identity recovery approval input is invalid'
                    USING ERRCODE = '22023';
            END IF;

            SELECT actor_id, actor_method, correlation_id
              INTO v_actor_id, v_actor_method, v_correlation_id
              FROM request_platform.assert_platform_identity_actor(
                  'platform.identity.recovery_approve'
              );

            SELECT fact.case_id, fact.intent_digest
              INTO v_replay
              FROM request_engine.platform_identity_recovery_facts AS fact
             WHERE fact.actor_principal_id = v_actor_id
               AND fact.action = 'approve'
               AND fact.idempotency_key_digest = p_idempotency_key_digest;
            IF FOUND THEN
                IF v_replay.intent_digest <> p_intent_digest THEN
                    RAISE EXCEPTION
                        'Idempotency key was already used for another recovery approval'
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
             WHERE id = p_case_id
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Identity recovery case does not exist'
                    USING ERRCODE = 'P0002';
            END IF;
            IF v_case.status <> 'requested' THEN
                RAISE EXCEPTION 'Only a requested recovery case can be approved'
                    USING ERRCODE = '55000';
            END IF;
            IF v_case.revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Identity recovery case revision is stale'
                    USING ERRCODE = '40001';
            END IF;
            IF v_case.requester_principal_id = v_actor_id THEN
                RAISE EXCEPTION 'The recovery requester cannot approve their own case'
                    USING ERRCODE = '42501';
            END IF;

            -- Authority/identity locks belong to the auth primitives; approval
            -- only revalidates that the target is still reachable today.
            PERFORM 1
              FROM request_engine.identity_authorities AS authority
              JOIN request_engine.native_identities AS native_identity
                ON native_identity.identity_authority_id = authority.id
             WHERE native_identity.id = v_case.target_native_identity_id
               AND authority.kind = 'native' AND authority.status = 'active'
               AND native_identity.status = 'active';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Recovery target is not an active Native identity'
                    USING ERRCODE = '23514';
            END IF;

            UPDATE request_engine.identity_recovery_cases
               SET status = 'approved',
                   approver_principal_id = v_actor_id,
                   approved_at = clock_timestamp(),
                   approval_expires_at = clock_timestamp() + interval '24 hours',
                   revision = identity_recovery_cases.revision + 1,
                   updated_at = clock_timestamp()
             WHERE id = p_case_id;
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
                'approve',
                v_actor_id,
                v_actor_method,
                btrim(p_reason_code),
                v_case.evidence_reference,
                v_case.revision,
                v_case.revision + 1,
                v_correlation_id,
                'platform.identity.recovery_approve',
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


ALTER FUNCTION request_platform.approve_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) OWNER TO request_platform_control_definer;

--
-- Name: assert_other_platform_controller(uuid); Type: FUNCTION; Schema: request_platform; Owner: request_platform_control_definer
--

CREATE FUNCTION request_platform.assert_other_platform_controller(p_excluded_principal_id uuid) RETURNS void
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
