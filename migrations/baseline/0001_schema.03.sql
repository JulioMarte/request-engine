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
-- Name: lock_staff_command_authority(text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_staff_command_authority(p_capability text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF p_capability IS NULL OR p_capability NOT IN
                ('staff.invite','staff.manage_authority','staff.manage_membership') THEN
                RAISE EXCEPTION 'unsupported staff command capability' USING ERRCODE='22023';
            END IF;
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            RETURN request_engine.assert_staff_manager(p_capability);
        END;
        $$;


ALTER FUNCTION request_cmd.lock_staff_command_authority(p_capability text) OWNER TO request_engine_schema_owner;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: staff_invitations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.staff_invitations (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    email text NOT NULL,
    invited_by_principal_id uuid NOT NULL,
    provenance_reference text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    generation integer DEFAULT 1 NOT NULL,
    token_digest text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    accepted_native_identity_id uuid,
    membership_id uuid,
    principal_id uuid,
    binding_id uuid,
    CONSTRAINT staff_invitations_check CHECK (((status = 'accepted'::text) = ((accepted_native_identity_id IS NOT NULL) AND (membership_id IS NOT NULL) AND (principal_id IS NOT NULL) AND (binding_id IS NOT NULL)))),
    CONSTRAINT staff_invitations_check1 CHECK (((status = 'accepted'::text) OR ((accepted_native_identity_id IS NULL) AND (membership_id IS NULL) AND (principal_id IS NULL) AND (binding_id IS NULL)))),
    CONSTRAINT staff_invitations_check2 CHECK ((expires_at > created_at)),
    CONSTRAINT staff_invitations_email_check CHECK (((length(email) BETWEEN 3 AND 320) AND (email = lower(btrim(email))) AND (email ~ '^[a-z0-9._%+-]+@[a-z0-9.-]+$'::text))),
    CONSTRAINT staff_invitations_generation_check CHECK ((generation > 0)),
    CONSTRAINT staff_invitations_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT staff_invitations_revision_check CHECK ((revision > 0)),
    CONSTRAINT staff_invitations_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'accepted'::text, 'revoked'::text, 'expired'::text]))),
    CONSTRAINT staff_invitations_token_digest_check CHECK ((token_digest ~ '^[0-9a-f]{64}$'::text))
);

ALTER TABLE ONLY request_engine.staff_invitations FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.staff_invitations OWNER TO request_engine_schema_owner;

--
-- Name: lock_staff_invitation_acceptance(uuid, text, uuid, uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_staff_invitation_acceptance(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid) RETURNS SETOF request_engine.staff_invitations
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE v_invitation request_engine.staff_invitations%ROWTYPE; v_org uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            IF p_id IS NULL OR p_digest IS NULL OR p_digest !~ '^[0-9a-f]{64}$'
                OR p_authority IS NULL OR p_identity IS NULL OR p_session IS NULL THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            v_org := request_auth.staff_invitation_target(p_id,p_digest);
            IF v_org IS NULL THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            PERFORM set_config('request_engine.organization_id',v_org::text,true);
            SELECT * INTO v_invitation FROM request_engine.staff_invitations WHERE id = p_id;
            IF NOT FOUND OR v_invitation.token_digest IS DISTINCT FROM p_digest THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            PERFORM id FROM request_engine.staff_memberships
                WHERE organization_id = v_invitation.organization_id AND status = 'active'
                ORDER BY principal_id FOR UPDATE;
            SELECT * INTO v_invitation FROM request_engine.staff_invitations WHERE id = p_id FOR
                UPDATE;
            IF v_invitation.token_digest IS DISTINCT FROM p_digest THEN
                RAISE EXCEPTION 'Invitation unavailable' USING ERRCODE = 'P0002';
            END IF;
            PERFORM 1 FROM request_engine.organizations
                WHERE id = v_invitation.organization_id AND operational_status = 'active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Organization unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.identity_authorities
                WHERE id = p_authority AND kind = 'native' AND status = 'active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Native authority unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.native_identities
                WHERE id = p_identity AND identity_authority_id = p_authority AND status =
                'active' FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Native identity unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.native_sessions AS s
                JOIN request_engine.native_identities AS i ON i.id = s.native_identity_id
                LEFT JOIN request_engine.native_credentials AS c ON c.id = s.password_credential_id
                LEFT JOIN request_engine.webauthn_credentials AS w ON w.id =
                s.webauthn_credential_id
                LEFT JOIN request_engine.native_identity_recovery_state AS r ON
                r.native_identity_id = i.id
                WHERE s.id = p_session AND s.native_identity_id = p_identity AND s.status = 'active'
                AND s.expires_at > clock_timestamp() AND s.session_epoch = i.session_epoch
                AND NOT s.recovery_derived AND coalesce(r.state,'normal') <> 'recovery_restricted'
                AND (c.status = 'active' OR w.status = 'active') FOR SHARE OF s;
            IF NOT FOUND THEN RAISE EXCEPTION 'Native session unavailable' USING ERRCODE =
                '42501'; END IF;
            PERFORM 1 FROM request_engine.native_credentials
                WHERE id = (SELECT password_credential_id FROM request_engine.native_sessions
                WHERE id = p_session)
                AND status = 'active' FOR SHARE;
            IF NOT FOUND THEN
                PERFORM 1 FROM request_engine.webauthn_credentials
                    WHERE id = (SELECT webauthn_credential_id FROM
                request_engine.native_sessions WHERE id = p_session)
                    AND status = 'active' FOR SHARE;
                IF NOT FOUND THEN RAISE EXCEPTION 'Session authenticator unavailable' USING
                ERRCODE = '42501'; END IF;
            END IF;
            IF v_invitation.status = 'accepted' THEN
                IF v_invitation.accepted_native_identity_id <> p_identity THEN
                    RAISE EXCEPTION 'Invitation belongs to another identity' USING ERRCODE =
                '42501';
                END IF;
            ELSE
                IF v_invitation.status <> 'pending' OR v_invitation.expires_at <=
                clock_timestamp() THEN
                    RAISE EXCEPTION 'Invitation no longer pending' USING ERRCODE = '55000';
                END IF;
                PERFORM 1 FROM request_engine.principals AS p
                    JOIN request_engine.staff_memberships AS m ON m.principal_id = p.id
                        AND m.organization_id = p.organization_id AND m.status = 'active'
                    JOIN request_engine.principal_authority_grants AS g ON g.principal_id = p.id
                        AND g.organization_id = p.organization_id AND g.status = 'active'
                        AND g.capability_key = 'staff.invite'
                    WHERE p.id = v_invitation.invited_by_principal_id
                        AND p.organization_id = v_invitation.organization_id
                        AND p.active AND p.principal_kind = 'human' AND p.principal_plane = 'tenant'
                    AND EXISTS (
                        SELECT 1 FROM request_engine.identity_bindings b
                        JOIN request_engine.identity_authorities a
                            ON a.id=b.identity_authority_id AND a.status='active'
                        LEFT JOIN request_engine.native_identities n
                            ON a.kind='native' AND n.id::text=b.subject_id
                            AND n.identity_authority_id=a.id
                        WHERE b.principal_id=p.id AND b.organization_id=p.organization_id
                            AND b.status='active'
                            AND (a.kind <> 'native' OR n.status='active')
                    ) FOR SHARE OF p,m,g;
                IF NOT FOUND THEN RAISE EXCEPTION 'Inviter authority withdrawn' USING ERRCODE =
                '42501'; END IF;
            END IF;
            PERFORM set_config('request_engine.organization_id',
                v_invitation.organization_id::text,true);
            PERFORM set_config('request_engine.staff_invitation_id',p_id::text,true);
            PERFORM set_config('request_engine.staff_invitation_subject',p_identity::text,true);
            RETURN NEXT v_invitation;
        END $_$;


ALTER FUNCTION request_cmd.lock_staff_invitation_acceptance(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_staff_invitation_admin(uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_staff_invitation_admin(p_id uuid) RETURNS SETOF request_engine.staff_invitations
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            PERFORM request_engine.assert_staff_manager('staff.invite');
            RETURN QUERY SELECT * FROM request_engine.staff_invitations
                WHERE id = p_id AND organization_id = request_engine.current_organization_id()
                FOR UPDATE;
        END $$;


ALTER FUNCTION request_cmd.lock_staff_invitation_admin(p_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: lock_staff_member_profile(uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.lock_staff_member_profile(p_membership uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE v_status text;
        BEGIN
            PERFORM request_engine.lock_tenant_staff_root();
            PERFORM request_engine.assert_staff_manager('staff.manage_membership');
            SELECT status INTO v_status FROM request_engine.staff_memberships
                WHERE organization_id=request_engine.current_organization_id()
                  AND id=p_membership FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Staff member not found'
                USING ERRCODE='P0002'; END IF;
            IF v_status='revoked' THEN RAISE EXCEPTION 'Revoked staff profile is immutable'
                USING ERRCODE='55000'; END IF;
        END $$;


ALTER FUNCTION request_cmd.lock_staff_member_profile(p_membership uuid) OWNER TO request_engine_schema_owner;

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
-- Name: materialize_invited_staff(uuid, text, uuid, uuid, uuid, uuid, uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.materialize_invited_staff(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid, p_membership uuid, p_principal uuid, p_binding uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE v_invitation request_engine.staff_invitations%ROWTYPE; v_anchor uuid;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            SELECT * INTO STRICT v_invitation FROM request_cmd.lock_staff_invitation_acceptance(
                p_id,p_digest,p_authority,p_identity,p_session);
            IF v_invitation.status = 'accepted' THEN RETURN; END IF;
            SELECT organization_party_id INTO v_anchor FROM
                request_engine.organization_root_provisioning_facts
                WHERE organization_id = v_invitation.organization_id;
            IF v_anchor IS NULL THEN RAISE EXCEPTION 'Tenant root unavailable' USING ERRCODE =
                '23514'; END IF;
            INSERT INTO request_engine.principals(id,organization_id,
                principal_plane,principal_kind,external_subject)
                VALUES(p_principal,v_invitation.organization_id,'tenant','human','native:'||p_identity::text);
            INSERT INTO request_engine.identity_bindings(id,organization_id,
                principal_id,principal_plane,
                identity_authority_id,subject_id,status)
                VALUES(p_binding,v_invitation.organization_id,p_principal,'tenant',p_authority,p_identity::text,'active');
            INSERT INTO request_engine.staff_memberships(id,organization_id,
                principal_id,identity_binding_id,
                authority_anchor_party_id,status,established_by_principal_id,provenance_kind,provenance_reference,activated_at)
                VALUES(p_membership,v_invitation.organization_id,p_principal,p_binding,v_anchor,'active',
                    v_invitation.invited_by_principal_id,'staff_invitation',v_invitation.provenance_reference,clock_timestamp());
            UPDATE request_engine.staff_invitations SET status='accepted',revision=revision+1,
                accepted_native_identity_id=p_identity,membership_id=p_membership,principal_id=p_principal,binding_id=p_binding,
                updated_at=clock_timestamp() WHERE id=p_id;
            INSERT INTO request_engine.audit_records(organization_id,actor_principal_id,
                command_name,aggregate_kind,aggregate_id,details)
                VALUES(v_invitation.organization_id,p_principal,'staff.invitation.accept','StaffInvitation',p_id,
                jsonb_build_object('action','accept','reason_code','staff_invitation_accepted',
                    'revision_before',v_invitation.revision,'revision_after',v_invitation.revision+1,
                    'provenance_reference',v_invitation.provenance_reference));
        END $$;


ALTER FUNCTION request_cmd.materialize_invited_staff(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid, p_membership uuid, p_principal uuid, p_binding uuid) OWNER TO request_engine_schema_owner;

--
-- Name: read_controller_policy_adoption(uuid, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.read_controller_policy_adoption(p_request_id uuid, p_binding_id uuid) RETURNS TABLE(request_id uuid, organization_id uuid, controller_principal_id uuid, source_policy_key text, target_policy_key text, expected_authority_revision bigint, status text, revision bigint, created_at timestamp with time zone, expires_at timestamp with time zone, authority_revision_before bigint, authority_revision_after bigint, added_capabilities text[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'request_cmd', 'pg_temp'
    AS $$
        DECLARE v_org uuid:=request_engine.current_organization_id();
                v_actor uuid:=NULLIF(current_setting(
                    'request_engine.authenticated_principal_id',true),'')::uuid;
                v_row request_engine.controller_policy_adoption_requests%ROWTYPE;
        BEGIN
            IF v_org IS NULL OR v_actor IS NULL OR p_binding_id IS NULL OR NOT EXISTS(
                SELECT 1 FROM request_engine.organization_root_provisioning_facts f
                JOIN request_engine.principals p ON p.id=f.controller_principal_id
                JOIN request_engine.identity_bindings b ON b.id=f.controller_binding_id
                WHERE f.organization_id=v_org AND f.controller_principal_id=v_actor
                  AND f.controller_binding_id=p_binding_id AND p.principal_plane='tenant'
                  AND p.principal_kind='human' AND p.active AND b.principal_id=v_actor
                  AND b.organization_id=v_org AND b.principal_plane='tenant'
                  AND b.status='active'
            ) THEN
                RAISE EXCEPTION 'Only the active original controller may inspect consent'
                    USING ERRCODE='42501';
            END IF;
            SELECT r.* INTO v_row FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id AND r.organization_id=v_org
               AND r.controller_principal_id=v_actor AND r.controller_binding_id=p_binding_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Adoption request unavailable' USING ERRCODE='P0002';
            END IF;
            RETURN QUERY SELECT v_row.id,v_row.organization_id,v_row.controller_principal_id,
                v_row.source_policy_key,v_row.target_policy_key,v_row.expected_authority_revision,
                CASE WHEN v_row.status='pending' AND v_row.expires_at<=clock_timestamp()
                     THEN 'expired' ELSE v_row.status END,
                v_row.revision,v_row.created_at,v_row.expires_at,f.authority_revision_before,
                f.authority_revision_after,f.added_capabilities
              FROM (SELECT 1) singleton
              LEFT JOIN request_engine.controller_policy_adoption_facts f
                ON f.request_id=v_row.id;
        END $$;


ALTER FUNCTION request_cmd.read_controller_policy_adoption(p_request_id uuid, p_binding_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: record_temporary_proof_retention(uuid, text, text, bigint, timestamp with time zone, timestamp with time zone, timestamp with time zone); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.record_temporary_proof_retention(p_backend uuid, p_mount text, p_reference text, p_version bigint, p_created timestamp with time zone, p_deletion timestamp with time zone, p_expiry timestamp with time zone) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE retained request_engine.temporary_proof_retention_receipts;
        BEGIN
            INSERT INTO request_engine.temporary_proof_retention_receipts
                (backend_id,mount,reference,version,created_at,deletion_at,expires_at)
                VALUES(p_backend,p_mount,p_reference,p_version,p_created,p_deletion,p_expiry)
                ON CONFLICT DO NOTHING;
            SELECT * INTO STRICT retained FROM request_engine.temporary_proof_retention_receipts
                WHERE backend_id=p_backend AND mount=p_mount AND reference=p_reference
                  AND version=p_version AND created_at=p_created;
            IF (retained.deletion_at,retained.expires_at)
                IS DISTINCT FROM (p_deletion,p_expiry) THEN
                RAISE EXCEPTION 'retention receipt conflicts' USING ERRCODE='23505';
            END IF;
        END;
        $$;


ALTER FUNCTION request_cmd.record_temporary_proof_retention(p_backend uuid, p_mount text, p_reference text, p_version bigint, p_created timestamp with time zone, p_deletion timestamp with time zone, p_expiry timestamp with time zone) OWNER TO request_engine_schema_owner;

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
-- Name: request_controller_policy_adoption(uuid, bigint, text, text, text, uuid); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.request_controller_policy_adoption(p_binding_id uuid, p_expected_authority_revision bigint, p_reason text, p_key_digest text, p_intent_digest text, p_correlation_id uuid) RETURNS TABLE(request_id uuid, source_policy_key text, target_policy_key text, authority_revision bigint, request_revision bigint, status text, expires_at timestamp with time zone)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'request_cmd', 'pg_temp'
    AS $_$
        DECLARE
            v_org uuid:=request_engine.current_organization_id();
            v_actor uuid;
            v_root uuid;
            v_root_binding uuid;
            v_policy text;
            v_revision bigint;
            v_existing request_engine.controller_policy_adoption_requests%ROWTYPE;
            v_id uuid;
            v_expiry timestamptz;
            v_identity_authority_id uuid;
            v_identity_subject text;
            v_native_identity_id uuid;
            v_locked_authority_id uuid;
            v_identity_status text;
            v_recovery_state text;
            v_recovery_epoch bigint;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor:=request_engine.assert_staff_manager('organization.bootstrap');
            SELECT f.controller_principal_id,f.controller_binding_id,
                   COALESCE((SELECT fact.target_policy_key
                       FROM request_engine.controller_policy_adoption_facts fact
                      WHERE fact.organization_id=f.organization_id
                      ORDER BY fact.applied_at DESC,fact.id DESC LIMIT 1),
                       f.initial_controller_policy_key)
              INTO v_root,v_root_binding,v_policy
              FROM request_engine.organization_root_provisioning_facts f
             WHERE f.organization_id=v_org;
            IF NOT FOUND OR v_root IS DISTINCT FROM v_actor
               OR v_root_binding IS DISTINCT FROM p_binding_id
               OR p_binding_id IS NULL
               OR NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b
                    JOIN request_engine.principals p ON p.id=b.principal_id
                   WHERE b.id=p_binding_id AND b.organization_id=v_org
                     AND b.principal_plane='tenant' AND b.principal_id=v_actor
                     AND b.status='active' AND p.principal_plane='tenant'
                     AND p.principal_kind='human' AND p.active)
            THEN
                RAISE EXCEPTION 'Only the active original HUMAN root controller may consent'
                    USING ERRCODE='42501';
            END IF;
            SELECT binding.identity_authority_id,binding.subject_id
              INTO v_identity_authority_id,v_identity_subject
              FROM request_engine.identity_bindings binding
             WHERE binding.id=p_binding_id AND binding.principal_id=v_actor
               AND binding.organization_id=v_org AND binding.status='active';
            IF v_identity_subject !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
                RAISE EXCEPTION 'Active bound native controller is required'
                    USING ERRCODE='42501';
            END IF;
            v_native_identity_id:=v_identity_subject::uuid;
            SELECT posture.identity_authority_id,posture.identity_status,
                   posture.recovery_state,posture.recovery_epoch
              INTO v_locked_authority_id,v_identity_status,
                   v_recovery_state,v_recovery_epoch
              FROM request_auth.lock_native_identity_recovery_postures(
                  ARRAY[v_native_identity_id]) posture
             WHERE posture.native_identity_id=v_native_identity_id
               AND posture.identity_status='active';
            IF NOT FOUND OR v_locked_authority_id IS DISTINCT FROM v_identity_authority_id
               OR v_identity_status<>'active' OR v_recovery_state<>'normal' THEN
                RAISE EXCEPTION 'Recovery-restricted controller cannot consent'
                    USING ERRCODE='42501';
            END IF;
            IF p_expected_authority_revision IS NULL OR p_expected_authority_revision<1
               OR p_reason IS NULL OR length(btrim(p_reason)) NOT BETWEEN 1 AND 500
               OR p_key_digest !~ '^[0-9a-f]{64}$'
               OR p_intent_digest !~ '^[0-9a-f]{64}$' OR p_correlation_id IS NULL
            THEN RAISE EXCEPTION 'Invalid controller adoption request'
                USING ERRCODE='22023'; END IF;
            SELECT principal.authority_revision INTO v_revision
              FROM request_engine.principals principal
             WHERE principal.id=v_root AND principal.organization_id=v_org
               AND principal.active FOR SHARE;
            IF v_policy IS NULL OR v_policy NOT IN
                 ('tenant-controller-v1','tenant-controller-v2','tenant-controller-v3',
                  'tenant-controller-v4','tenant-controller-v5','tenant-controller-v6','tenant-controller-v7','tenant-controller-v8','tenant-controller-v9')
               OR NOT EXISTS(SELECT 1 FROM request_engine.initial_controller_policies
                              WHERE policy_key='tenant-controller-v9')
            THEN RAISE EXCEPTION 'No supported policy transition exists'
                USING ERRCODE='55000'; END IF;

            SELECT * INTO v_existing FROM request_engine.controller_policy_adoption_requests r
             WHERE r.controller_principal_id=v_actor AND r.idempotency_key_digest=p_key_digest;
            IF FOUND THEN
                IF v_existing.intent_digest<>p_intent_digest THEN
                    RAISE EXCEPTION 'Idempotency key conflicts' USING ERRCODE='23505';
                END IF;
                RETURN QUERY SELECT v_existing.id,v_existing.source_policy_key,
                    v_existing.target_policy_key,v_existing.expected_authority_revision,
                    v_existing.revision,
                    CASE WHEN v_existing.status='pending'
                              AND v_existing.expires_at<=clock_timestamp()
                         THEN 'expired' ELSE v_existing.status END,
                    v_existing.expires_at;
                RETURN;
            END IF;
            IF v_policy NOT IN ('tenant-controller-v1','tenant-controller-v2',
                'tenant-controller-v3','tenant-controller-v4','tenant-controller-v5','tenant-controller-v6','tenant-controller-v7','tenant-controller-v8') THEN
                RAISE EXCEPTION 'No supported policy transition exists' USING ERRCODE='55000';
            END IF;
            IF v_revision IS DISTINCT FROM p_expected_authority_revision THEN
                RAISE EXCEPTION 'Controller authority changed' USING ERRCODE='40001';
            END IF;
            UPDATE request_engine.controller_policy_adoption_requests r
               SET status='expired',closed_at=clock_timestamp(),revision=revision+1
             WHERE r.organization_id=v_org AND r.status='pending'
               AND r.expires_at<=clock_timestamp();
            IF EXISTS(SELECT 1 FROM request_engine.controller_policy_adoption_requests r
                WHERE r.organization_id=v_org AND r.status='pending') THEN
                RAISE EXCEPTION 'A policy adoption request is already pending'
                    USING ERRCODE='23505';
            END IF;
            v_id:=uuidv7();
            v_expiry:=clock_timestamp()+interval '24 hours';
            INSERT INTO request_engine.controller_policy_adoption_requests(
                id,organization_id,controller_principal_id,controller_binding_id,
                source_policy_key,target_policy_key,expected_authority_revision,reason,
                idempotency_key_digest,intent_digest,correlation_id,expires_at,controller_native_identity_id,controller_recovery_epoch)
            VALUES(v_id,v_org,v_actor,p_binding_id,v_policy,'tenant-controller-v9',v_revision,
                btrim(p_reason),p_key_digest,p_intent_digest,p_correlation_id,v_expiry,v_native_identity_id,v_recovery_epoch);
            RETURN QUERY SELECT v_id,v_policy,'tenant-controller-v9',v_revision,1::bigint,
                'pending'::text,v_expiry;
        END $_$;


ALTER FUNCTION request_cmd.request_controller_policy_adoption(p_binding_id uuid, p_expected_authority_revision bigint, p_reason text, p_key_digest text, p_intent_digest text, p_correlation_id uuid) OWNER TO request_engine_schema_owner;

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
-- Name: rotate_agent_credential(uuid, bigint, uuid, bytea, text, timestamp with time zone); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.rotate_agent_credential(p_target uuid, p_expected bigint, p_credential uuid, p_digest bytea, p_fingerprint text, p_expiry timestamp with time zone) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE v_identity uuid; v_revision bigint;
        BEGIN
            v_identity := request_cmd.lock_agent_credential_manager(p_target);
            IF p_expected IS NULL OR p_expected<1 OR p_credential IS NULL OR p_digest IS NULL
               OR octet_length(p_digest)<>32 OR p_fingerprint IS NULL
               OR p_fingerprint !~ '^[0-9a-f]{16}$' OR p_expiry IS NULL
               OR p_expiry<=clock_timestamp() THEN
                RAISE EXCEPTION 'Invalid rotation input' USING ERRCODE='22023';
            END IF;
            SELECT authority_revision INTO v_revision FROM request_engine.principals
             WHERE organization_id=request_engine.current_organization_id() AND id=p_target;
            IF v_revision<>p_expected THEN
                RAISE EXCEPTION 'Agent authority revision is stale' USING ERRCODE='40001';
            END IF;
            UPDATE request_engine.workload_credentials SET status='revoked',
                revision=revision+1, revoked_at=clock_timestamp()
             WHERE workload_identity_id=v_identity AND status='active';
            INSERT INTO request_engine.workload_credentials
                (id,workload_identity_id,token_digest,token_fingerprint,expires_at)
             VALUES(p_credential,v_identity,p_digest,p_fingerprint,p_expiry);
            UPDATE request_engine.principals SET authority_revision=authority_revision+1
             WHERE organization_id=request_engine.current_organization_id() AND id=p_target
             RETURNING authority_revision INTO v_revision;
            RETURN v_revision;
        END $_$;


ALTER FUNCTION request_cmd.rotate_agent_credential(p_target uuid, p_expected bigint, p_credential uuid, p_digest bytea, p_fingerprint text, p_expiry timestamp with time zone) OWNER TO request_engine_schema_owner;

--
-- Name: rotate_integration_credential(uuid, bigint, uuid, bytea, text, timestamp with time zone, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $_$
        DECLARE
            v_actor uuid;
            v_revision bigint;
            v_identity uuid;
        BEGIN
            v_actor := request_engine.assert_staff_manager('integration.provision');
            SELECT authority_revision INTO v_revision FROM request_engine.principals
             WHERE id = p_principal_id AND principal_kind = 'integration'
               AND organization_id = request_engine.current_organization_id()
             FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Integration not found' USING ERRCODE = 'P0002';
            END IF;
            IF p_expected_revision IS NULL OR p_expected_revision < 1
               OR p_expires_at IS NULL OR p_expires_at <= clock_timestamp()
               OR p_credential_id IS NULL OR p_digest IS NULL OR octet_length(p_digest) <> 32
               OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{16}$'
               OR p_reference IS NULL OR length(btrim(p_reference)) NOT BETWEEN 1 AND 500 THEN
                RAISE EXCEPTION 'Invalid credential replacement input' USING ERRCODE = '22023';
            END IF;
            IF v_revision <> p_expected_revision THEN
                RAISE EXCEPTION 'Integration revision is stale' USING ERRCODE = '40001';
            END IF;
            SELECT wi.id INTO v_identity
              FROM request_engine.workload_identities wi
              JOIN request_engine.identity_bindings b
                ON b.subject_id = wi.id::text AND b.identity_authority_id = wi.identity_authority_id
              JOIN request_engine.identity_authorities ia ON ia.id = wi.identity_authority_id
             WHERE b.principal_id = p_principal_id
               AND b.organization_id = request_engine.current_organization_id()
               AND b.status IN ('pending', 'active', 'suspended')
               AND wi.status = 'active' AND wi.workload_kind = 'integration'
               AND ia.status = 'active' AND ia.kind = 'workload'
             FOR UPDATE OF wi FOR SHARE OF b, ia;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Revoked integration or inactive identity authority'
                    USING ERRCODE = '55000';
            END IF;
            UPDATE request_engine.workload_credentials
               SET status = 'revoked', revision = revision + 1, revoked_at = clock_timestamp()
             WHERE workload_identity_id = v_identity AND status = 'active';
            INSERT INTO request_engine.workload_credentials (
                id, workload_identity_id, token_digest, token_fingerprint, expires_at
            ) VALUES (p_credential_id, v_identity, p_digest, p_fingerprint, p_expires_at);
            UPDATE request_engine.principals SET authority_revision = authority_revision + 1
             WHERE id = p_principal_id RETURNING authority_revision INTO v_revision;
            PERFORM request_engine.append_integration_fact(
                p_principal_id, v_actor, 'credential_rotate', p_reference, 'integration.provision'
            );
            RETURN v_revision;
        END $_$;


ALTER FUNCTION request_cmd.rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text) OWNER TO request_engine_schema_owner;

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
-- Name: withdraw_controller_policy_adoption(uuid, bigint, uuid, text, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.withdraw_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_binding_id uuid, p_key_digest text, p_intent_digest text) RETURNS TABLE(request_revision bigint, status text)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'request_cmd', 'pg_temp'
    AS $_$
        DECLARE v_org uuid:=request_engine.current_organization_id(); v_actor uuid;
                v_root uuid; v_binding uuid;
                v_row request_engine.controller_policy_adoption_requests%ROWTYPE;
        BEGIN
            PERFORM request_engine.acquire_identity_topology_share();
            PERFORM request_engine.lock_tenant_staff_root();
            v_actor:=request_engine.assert_staff_manager('organization.bootstrap');
            SELECT controller_principal_id,controller_binding_id INTO v_root,v_binding
              FROM request_engine.organization_root_provisioning_facts
             WHERE organization_id=v_org;
            IF NOT FOUND OR v_root IS DISTINCT FROM v_actor
               OR v_binding IS DISTINCT FROM p_binding_id
               OR NOT EXISTS(SELECT 1 FROM request_engine.identity_bindings b
                  WHERE b.id=v_binding AND b.organization_id=v_org AND b.principal_id=v_actor
                    AND b.principal_plane='tenant' AND b.status='active') THEN
                RAISE EXCEPTION 'Only the active original root controller may withdraw consent'
                    USING ERRCODE='42501';
            END IF;
            SELECT * INTO v_row FROM request_engine.controller_policy_adoption_requests r
             WHERE r.id=p_request_id AND r.organization_id=v_org FOR UPDATE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Adoption request unavailable'
                USING ERRCODE='P0002'; END IF;
            IF p_expected_revision IS NULL OR p_expected_revision<1
               OR p_key_digest !~ '^[0-9a-f]{64}$' OR p_intent_digest !~ '^[0-9a-f]{64}$' THEN
                RAISE EXCEPTION 'Invalid withdrawal input' USING ERRCODE='22023';
            END IF;
            IF v_row.status='withdrawn' AND v_row.withdrawn_key_digest=p_key_digest
               AND v_row.withdrawn_intent_digest=p_intent_digest THEN
                RETURN QUERY SELECT v_row.revision,v_row.status; RETURN;
            END IF;
            IF v_row.status<>'pending' OR v_row.expires_at<=clock_timestamp()
               OR v_row.revision<>p_expected_revision THEN
                RAISE EXCEPTION 'Adoption request is no longer withdrawable' USING ERRCODE='40001';
            END IF;
            UPDATE request_engine.controller_policy_adoption_requests r SET status='withdrawn',
                revision=revision+1,closed_at=clock_timestamp(),withdrawn_key_digest=p_key_digest,
                withdrawn_intent_digest=p_intent_digest
             WHERE r.id=p_request_id RETURNING r.revision,r.status INTO request_revision,status;
            RETURN NEXT;
        END $_$;


ALTER FUNCTION request_cmd.withdraw_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_binding_id uuid, p_key_digest text, p_intent_digest text) OWNER TO request_engine_schema_owner;

--
-- Name: write_staff_member_profile(uuid, bigint, text, text); Type: FUNCTION; Schema: request_cmd; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_cmd.write_staff_member_profile(p_membership uuid, p_expected bigint, p_name text, p_provenance text) RETURNS bigint
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE v_revision bigint; v_org uuid:=request_engine.current_organization_id();
        BEGIN
            PERFORM request_cmd.lock_staff_member_profile(p_membership);
            IF p_expected IS NULL OR p_expected<0 OR p_provenance IS NULL
                OR length(btrim(p_provenance)) NOT BETWEEN 1 AND 500
                OR (p_name IS NOT NULL AND (p_name<>btrim(p_name)
                    OR length(p_name) NOT BETWEEN 1 AND 200 OR p_name ~ '[[:cntrl:]]')) THEN
                RAISE EXCEPTION 'Invalid profile input' USING ERRCODE='22023'; END IF;
            SELECT revision INTO v_revision FROM request_engine.staff_member_profiles
                WHERE organization_id=v_org AND membership_id=p_membership FOR UPDATE;
            IF COALESCE(v_revision,0)<>p_expected THEN
                RAISE EXCEPTION 'Staff profile revision is stale' USING ERRCODE='40001'; END IF;
            INSERT INTO request_engine.staff_member_profiles(
                organization_id,membership_id,display_name,revision,updated_by_principal_id,provenance_reference)
                VALUES(v_org,p_membership,p_name,p_expected+1,
                    current_setting('request_engine.authenticated_principal_id')::uuid,btrim(p_provenance))
                ON CONFLICT(organization_id,membership_id) DO UPDATE SET
                    display_name=EXCLUDED.display_name,revision=EXCLUDED.revision,
                    updated_at=clock_timestamp(),updated_by_principal_id=EXCLUDED.updated_by_principal_id,
                    provenance_reference=EXCLUDED.provenance_reference;
            RETURN p_expected+1;
        END $$;


ALTER FUNCTION request_cmd.write_staff_member_profile(p_membership uuid, p_expected bigint, p_name text, p_provenance text) OWNER TO request_engine_schema_owner;

--
-- Name: acquire_identity_topology_exclusive(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.acquire_identity_topology_exclusive() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock(1380274257, 1902476357);
        END
        $$;


ALTER FUNCTION request_engine.acquire_identity_topology_exclusive() OWNER TO request_engine_schema_owner;

--
-- Name: acquire_identity_topology_share(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.acquire_identity_topology_share() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            PERFORM pg_catalog.pg_advisory_xact_lock_shared(1380274257, 1902476357);
        END
        $$;


ALTER FUNCTION request_engine.acquire_identity_topology_share() OWNER TO request_engine_schema_owner;

--
-- Name: adopt_platform_owner_v3(); Type: FUNCTION; Schema: request_engine; Owner: request_platform_control_definer
--

CREATE FUNCTION request_engine.adopt_platform_owner_v3() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        BEGIN
            IF NEW.principal_plane <> 'platform'
               OR NEW.authority_plane <> 'platform'
               OR NEW.status <> 'active'
               OR NEW.capability_key <> 'platform.owner.manage_lifecycle'
            THEN
                RETURN NEW;
            END IF;

            INSERT INTO request_engine.principal_authority_grants (
                principal_id,
                principal_plane,
                authority_plane,
                capability_key,
                delegable,
                granted_by_principal_id,
                provenance_kind,
                provenance_reference
            )
            SELECT
                NEW.principal_id,
                'platform',
                'platform',
                v3_grant.capability_key,
                v3_grant.delegable,
                CASE
                    WHEN NEW.provenance_kind = 'trust_bootstrap'
                    THEN NULL
                    ELSE NEW.granted_by_principal_id
                END,
                CASE
                    WHEN NEW.provenance_kind = 'trust_bootstrap'
                    THEN 'trust_bootstrap'
                    ELSE 'platform_owner_policy_upgrade'
                END,
                'platform-owner-v3-adoption:' || NEW.id::text
              FROM (
                  SELECT
                      item ->> 'capability_key' AS capability_key,
                      coalesce((item ->> 'delegable')::boolean, false) AS delegable
                    FROM request_engine.platform_owner_policies AS policy,
                         LATERAL jsonb_array_elements(policy.grants) AS item
                   WHERE policy.policy_key = 'platform-owner-v3'
              ) AS v3_grant
             WHERE NOT EXISTS (
                       SELECT 1
                         FROM request_engine.platform_owner_policies AS policy,
                              LATERAL jsonb_array_elements(policy.grants) AS item
                        WHERE policy.policy_key = 'platform-owner-v2'
                          AND item ->> 'capability_key' = v3_grant.capability_key
                   )
               AND NOT EXISTS (
                       SELECT 1
                         FROM request_engine.principal_authority_grants AS historical
                        WHERE historical.principal_id = NEW.principal_id
                          AND historical.capability_key = v3_grant.capability_key
                   );

            RETURN NEW;
        END
        $$;


ALTER FUNCTION request_engine.adopt_platform_owner_v3() OWNER TO request_platform_control_definer;

--
-- Name: adopt_platform_owner_v4(); Type: FUNCTION; Schema: request_engine; Owner: request_platform_control_definer
--

CREATE FUNCTION request_engine.adopt_platform_owner_v4() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
BEGIN
    IF NEW.principal_plane = 'platform'
       AND NEW.authority_plane = 'platform'
       AND NEW.capability_key = 'platform.owner.manage_lifecycle'
       AND NEW.status = 'active'
       AND NOT EXISTS (
           SELECT 1 FROM request_engine.principal_authority_grants AS historical
            WHERE historical.principal_id = NEW.principal_id
              AND historical.capability_key = 'platform.organization.read'
       ) THEN
        INSERT INTO request_engine.principal_authority_grants (
            organization_id, principal_id, principal_plane, authority_plane,
            capability_key, delegable, granted_by_principal_id,
            provenance_kind, provenance_reference
        ) VALUES (
            NULL, NEW.principal_id, 'platform', 'platform',
            'platform.organization.read', false,
            CASE WHEN NEW.provenance_kind = 'trust_bootstrap' THEN NULL
                 ELSE NEW.granted_by_principal_id END,
            CASE WHEN NEW.provenance_kind = 'trust_bootstrap' THEN 'trust_bootstrap'
                 ELSE 'platform_owner_policy_upgrade' END,
            'platform-owner-v4-adoption:' || NEW.id::text
        );
    END IF;
    RETURN NEW;
END
$$;


ALTER FUNCTION request_engine.adopt_platform_owner_v4() OWNER TO request_platform_control_definer;

--
-- Name: append_integration_fact(uuid, uuid, text, text, text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.append_integration_fact(p_principal_id uuid, p_actor_id uuid, p_operation text, p_reference text, p_capability text) RETURNS void
    LANGUAGE sql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
            INSERT INTO request_engine.integration_governance_facts (
                organization_id, integration_principal_id, actor_principal_id,
                actor_authority_revision, operation, provenance_reference,
                authority_revision, snapshot
            )
            SELECT pr.organization_id, pr.id, actor.id, actor.authority_revision,
                   p_operation, btrim(p_reference), pr.authority_revision,
                   jsonb_build_object(
                       'authority_source', p_capability,
                       'active', pr.active,
                       'grants', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', g.id, 'capability', g.capability_key,
                               'delegable', g.delegable, 'revision', g.revision
                           ) ORDER BY g.capability_key)
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id
                             AND g.principal_id = pr.id AND g.status = 'active'
                       ), '[]'::jsonb),
                       'delegable_ceiling', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', g.id, 'capability', g.capability_key,
                               'revision', g.revision
                           ) ORDER BY g.capability_key)
                           FROM request_engine.principal_authority_grants g
                           WHERE g.organization_id = pr.organization_id
                             AND g.principal_id = actor.id AND g.status = 'active'
                             AND g.delegable AND g.authority_plane = 'operational'
                       ), '[]'::jsonb),
                       'bindings', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', b.id, 'authority_id', b.identity_authority_id,
                               'subject_id', b.subject_id, 'status', b.status,
                               'revision', b.revision
                           ) ORDER BY b.id)
                           FROM request_engine.identity_bindings b
                           WHERE b.organization_id = pr.organization_id
                             AND b.principal_id = pr.id
                       ), '[]'::jsonb),
                       'credentials', COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'id', c.id, 'status', c.status, 'expires_at', c.expires_at
                           ) ORDER BY c.id)
                           FROM request_engine.identity_bindings b
                           JOIN request_engine.workload_credentials c
                             ON c.workload_identity_id::text = b.subject_id
                           WHERE b.organization_id = pr.organization_id
                             AND b.principal_id = pr.id AND c.status = 'active'
                       ), '[]'::jsonb)
                   )
              FROM request_engine.principals pr
              JOIN request_engine.principals actor
                ON actor.id = p_actor_id AND actor.organization_id = pr.organization_id
             WHERE pr.id = p_principal_id
               AND pr.organization_id = request_engine.current_organization_id()
        $$;


ALTER FUNCTION request_engine.append_integration_fact(p_principal_id uuid, p_actor_id uuid, p_operation text, p_reference text, p_capability text) OWNER TO request_engine_schema_owner;

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
-- Name: assert_organization_has_controller(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_organization_has_controller(p_organization_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_candidate uuid;
        BEGIN
            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = p_organization_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       p_organization_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '55000';
            END IF;
        END
        $$;


ALTER FUNCTION request_engine.assert_organization_has_controller(p_organization_id uuid) OWNER TO request_engine_schema_owner;

--
-- Name: assert_other_tenant_controller(uuid); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_other_tenant_controller(p_excluded_principal_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            PERFORM id
              FROM request_engine.staff_memberships
             WHERE organization_id = v_org_id
               AND status = 'active'
             ORDER BY principal_id
             FOR UPDATE;

            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
               AND membership.principal_id <> p_excluded_principal_id
               AND request_engine.principal_is_effective_tenant_controller(
                       v_org_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_engine.assert_other_tenant_controller(p_excluded_principal_id uuid) OWNER TO request_engine_schema_owner;

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
-- Name: assert_staff_manager(text); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_staff_manager(p_capability text) RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_actor_id uuid;
            v_org_id uuid;
        BEGIN
            BEGIN
                v_actor_id := current_setting(
                    'request_engine.authenticated_principal_id', true
                )::uuid;
                v_org_id := request_engine.current_organization_id();
            EXCEPTION WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'Tenant actor provenance is malformed'
                    USING ERRCODE = '28000';
            END;
            IF v_actor_id IS NULL OR v_org_id IS NULL THEN
                RAISE EXCEPTION 'Tenant actor provenance is required'
                    USING ERRCODE = '28000';
            END IF;
            PERFORM 1
              FROM request_engine.principals AS principal
              JOIN request_engine.staff_memberships AS membership
                ON membership.principal_id = principal.id
               AND membership.organization_id = v_org_id
               AND membership.status = 'active'
              JOIN request_engine.principal_authority_grants AS grant_row
                ON grant_row.principal_id = principal.id
               AND grant_row.organization_id = v_org_id
               AND grant_row.capability_key = p_capability
               AND grant_row.status = 'active'
             WHERE principal.id = v_actor_id
               AND principal.organization_id = v_org_id
               AND principal.principal_plane = 'tenant'
               AND principal.principal_kind = 'human'
               AND principal.active
             FOR SHARE OF principal, membership, grant_row;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Current Principal lacks active staff authority'
                    USING ERRCODE = '42501';
            END IF;
            RETURN v_actor_id;
        END
        $$;


ALTER FUNCTION request_engine.assert_staff_manager(p_capability text) OWNER TO request_engine_schema_owner;

--
-- Name: assert_temporary_proof_worker(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_temporary_proof_worker() RETURNS void
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE caller record; worker record; BEGIN
            SELECT * INTO STRICT caller FROM pg_roles WHERE rolname=session_user;
            SELECT * INTO STRICT worker FROM pg_roles WHERE rolname='request_proof_cleanup_worker';
            IF NOT caller.rolcanlogin OR caller.rolsuper OR caller.rolbypassrls
                OR caller.rolcreatedb
                OR caller.rolcreaterole OR caller.rolreplication OR caller.rolconfig IS NOT NULL
                OR NOT pg_has_role(session_user,worker.oid,'MEMBER')
                OR worker.rolcanlogin OR worker.rolsuper OR worker.rolbypassrls
                OR worker.rolcreatedb
                OR worker.rolcreaterole OR worker.rolreplication OR worker.rolconfig IS NOT NULL
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=worker.oid)
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member=caller.oid
                    AND (roleid<>worker.oid OR admin_option))
                OR EXISTS(SELECT 1 FROM pg_db_role_setting
                    WHERE setrole IN(caller.oid,worker.oid)) THEN
                RAISE EXCEPTION 'retention worker login is not isolated' USING ERRCODE='42501';
            END IF;
        END $$;


ALTER FUNCTION request_engine.assert_temporary_proof_worker() OWNER TO request_engine_schema_owner;

--
-- Name: assert_tenant_has_controller(); Type: FUNCTION; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE FUNCTION request_engine.assert_tenant_has_controller() RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'request_engine', 'pg_temp'
    AS $$
        DECLARE
            v_org_id uuid := request_engine.current_organization_id();
            v_candidate uuid;
        BEGIN
            SELECT membership.principal_id
              INTO v_candidate
              FROM request_engine.staff_memberships AS membership
             WHERE membership.organization_id = v_org_id
               AND membership.status = 'active'
               AND request_engine.principal_is_effective_tenant_controller(
                       v_org_id, membership.principal_id)
             ORDER BY membership.principal_id
             LIMIT 1;
            IF v_candidate IS NULL THEN
                RAISE EXCEPTION 'Tenant must retain an active recovery-capable controller'
                    USING ERRCODE = '23514';
            END IF;
        END
        $$;


ALTER FUNCTION request_engine.assert_tenant_has_controller() OWNER TO request_engine_schema_owner;

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


