    CONSTRAINT staff_memberships_revision_check CHECK ((revision > 0)),
    CONSTRAINT staff_memberships_state_time_check CHECK ((((status = 'invited'::text) AND (activated_at IS NULL) AND (suspended_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'active'::text) AND (activated_at IS NOT NULL) AND (suspended_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'suspended'::text) AND (activated_at IS NOT NULL) AND (suspended_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT staff_memberships_status_check CHECK ((status = ANY (ARRAY['invited'::text, 'active'::text, 'suspended'::text, 'revoked'::text])))
);

ALTER TABLE ONLY request_engine.staff_memberships FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.staff_memberships OWNER TO request_engine_schema_owner;

--
-- Name: waitlist_entries; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.waitlist_entries (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    preferred_resource_id uuid,
    earliest_start timestamp with time zone,
    latest_start timestamp with time zone,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT waitlist_entries_check CHECK (((latest_start IS NULL) OR (earliest_start IS NULL) OR (latest_start >= earliest_start))),
    CONSTRAINT waitlist_entries_revision_check CHECK ((revision > 0)),
    CONSTRAINT waitlist_entries_status_check CHECK ((status = ANY (ARRAY['active'::text, 'fulfilled'::text, 'cancelled'::text, 'expired'::text])))
);


ALTER TABLE request_engine.waitlist_entries OWNER TO request_engine_schema_owner;

--
-- Name: webauthn_challenges; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.webauthn_challenges (
    id uuid NOT NULL,
    purpose text NOT NULL,
    native_identity_id uuid,
    session_id uuid,
    setup_session_id uuid,
    challenge_digest bytea NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    CONSTRAINT webauthn_challenges_digest_check CHECK ((octet_length(challenge_digest) = 32)),
    CONSTRAINT webauthn_challenges_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT webauthn_challenges_purpose_check CHECK ((purpose = ANY (ARRAY['registration'::text, 'authentication'::text, 'step_up'::text]))),
    CONSTRAINT webauthn_challenges_scope_check CHECK ((((((native_identity_id IS NOT NULL))::integer + ((session_id IS NOT NULL))::integer) + ((setup_session_id IS NOT NULL))::integer) = 1)),
    CONSTRAINT webauthn_challenges_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'expired'::text]))),
    CONSTRAINT webauthn_challenges_terminal_check CHECK ((((status = 'pending'::text) AND (consumed_at IS NULL)) OR ((status = 'consumed'::text) AND (consumed_at IS NOT NULL)) OR ((status = 'expired'::text) AND (consumed_at IS NULL))))
);


ALTER TABLE request_engine.webauthn_challenges OWNER TO request_engine_schema_owner;

--
-- Name: webauthn_credentials; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.webauthn_credentials (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    native_identity_id uuid NOT NULL,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    sign_count bigint DEFAULT 0 NOT NULL,
    aaguid text NOT NULL,
    backup_eligible boolean DEFAULT false NOT NULL,
    backup_state boolean DEFAULT false NOT NULL,
    user_verified boolean DEFAULT true NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    last_regression_at timestamp with time zone,
    CONSTRAINT webauthn_credentials_aaguid_check CHECK ((aaguid ~ '^[0-9a-f]{32}$'::text)),
    CONSTRAINT webauthn_credentials_id_check CHECK (((octet_length(credential_id) >= 16) AND (octet_length(credential_id) <= 1023))),
    CONSTRAINT webauthn_credentials_key_check CHECK ((octet_length(public_key) > 0)),
    CONSTRAINT webauthn_credentials_last_used_check CHECK (((last_used_at IS NULL) OR (last_used_at >= created_at))),
    CONSTRAINT webauthn_credentials_revision_check CHECK ((revision > 0)),
    CONSTRAINT webauthn_credentials_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL)))),
    CONSTRAINT webauthn_credentials_sign_count_check CHECK ((sign_count >= 0)),
    CONSTRAINT webauthn_credentials_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.webauthn_credentials OWNER TO request_engine_schema_owner;

--
-- Name: workload_credentials; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.workload_credentials (
    id uuid NOT NULL,
    workload_identity_id uuid NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT workload_credentials_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT workload_credentials_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT workload_credentials_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text)),
    CONSTRAINT workload_credentials_revision_check CHECK ((revision > 0)),
    CONSTRAINT workload_credentials_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL)))),
    CONSTRAINT workload_credentials_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.workload_credentials OWNER TO request_engine_schema_owner;

--
-- Name: workload_identities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.workload_identities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    identity_authority_id uuid NOT NULL,
    workload_kind text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    disabled_at timestamp with time zone,
    CONSTRAINT workload_identities_disabled_check CHECK ((((status = 'disabled'::text) AND (disabled_at IS NOT NULL)) OR ((status = 'active'::text) AND (disabled_at IS NULL)))),
    CONSTRAINT workload_identities_kind_check CHECK ((workload_kind = ANY (ARRAY['agent'::text, 'integration'::text, 'system'::text]))),
    CONSTRAINT workload_identities_revision_check CHECK ((revision > 0)),
    CONSTRAINT workload_identities_status_check CHECK ((status = ANY (ARRAY['active'::text, 'disabled'::text])))
);


ALTER TABLE request_engine.workload_identities OWNER TO request_engine_schema_owner;

--
-- Name: business_info_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.business_info_v1 WITH (security_invoker='true') AS
 SELECT id AS organization_id,
    organization_key,
    display_name,
    public_profile
   FROM request_engine.organizations o;


ALTER VIEW request_read.business_info_v1 OWNER TO request_engine_schema_owner;

--
-- Name: service_queue_status_v2; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.service_queue_status_v2 WITH (security_invoker='true') AS
 SELECT q.id AS queue_id,
    q.organization_id,
    q.queue_key,
    q.display_name,
    e.id AS queue_entry_id,
    e.subject_party_id,
    e.reservation_id,
    e.offering_id,
    e.status,
    e.arrived_at,
    e.admitted_at,
    e.called_at,
    e.expected_workload_classification_id,
    s.id AS service_session_id,
    s.resource_id AS actual_resource_id,
    s.location_id AS actual_location_id,
    s.actual_workload_classification_id,
    s.status AS service_status,
    s.started_at AS service_started_at,
    s.completed_at AS service_completed_at,
    e.revision AS queue_revision,
    s.revision AS service_revision
   FROM ((request_engine.service_queues q
     LEFT JOIN request_engine.queue_entries e ON (((e.organization_id = q.organization_id) AND (e.service_queue_id = q.id))))
     LEFT JOIN request_engine.service_sessions s ON (((s.organization_id = e.organization_id) AND (s.queue_entry_id = e.id))));


ALTER VIEW request_read.service_queue_status_v2 OWNER TO request_engine_schema_owner;

--
-- Name: live_service_staff_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.live_service_staff_v1 WITH (security_invoker='true') AS
 SELECT v.queue_id,
    v.organization_id,
    v.queue_key,
    v.display_name,
    v.queue_entry_id,
    v.subject_party_id,
    v.reservation_id,
    v.offering_id,
    v.status,
    v.arrived_at,
    v.admitted_at,
    v.called_at,
    v.expected_workload_classification_id,
    v.service_session_id,
    v.actual_resource_id,
    v.actual_location_id,
    v.actual_workload_classification_id,
    v.service_status,
    v.service_started_at,
    v.service_completed_at,
    v.queue_revision,
    v.service_revision,
    p.display_name AS subject_display_name,
    ew.workload_key AS expected_workload_key,
    aw.workload_key AS actual_workload_key,
        CASE
            WHEN (r.id IS NULL) THEN NULL::timestamp with time zone
            ELSE lower(r.during)
        END AS scheduled_at
   FROM ((((request_read.service_queue_status_v2 v
     LEFT JOIN request_engine.parties p ON (((p.organization_id = v.organization_id) AND (p.id = v.subject_party_id))))
     LEFT JOIN request_engine.operational_workload_classifications ew ON (((ew.organization_id = v.organization_id) AND (ew.id = v.expected_workload_classification_id))))
     LEFT JOIN request_engine.operational_workload_classifications aw ON (((aw.organization_id = v.organization_id) AND (aw.id = v.actual_workload_classification_id))))
     LEFT JOIN request_engine.reservations r ON (((r.organization_id = v.organization_id) AND (r.id = v.reservation_id))));


ALTER VIEW request_read.live_service_staff_v1 OWNER TO request_engine_schema_owner;

--
-- Name: locations_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.locations_v1 WITH (security_invoker='true') AS
 SELECT id,
    organization_id,
    location_key,
    display_name,
    timezone,
    public_data,
    active
   FROM request_engine.locations l;


ALTER VIEW request_read.locations_v1 OWNER TO request_engine_schema_owner;

--
-- Name: reservation_access_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.reservation_access_v1 WITH (security_invoker='true') AS
 SELECT id,
    organization_id,
    reservation_id,
    reservation_revision,
    access_key,
    kind,
    provider_key,
    materialization_key,
    status,
    access_uri,
    external_ref,
    public_data,
    provisioned_at,
    revoked_at,
    revision,
    created_at,
    updated_at
   FROM request_engine.reservation_access;


ALTER VIEW request_read.reservation_access_v1 OWNER TO request_engine_schema_owner;

--
-- Name: reservation_day_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.reservation_day_v1 WITH (security_invoker='true') AS
 SELECT r.id AS reservation_id,
    r.organization_id,
    r.offering_version_id,
    r.subject_party_id,
    p.display_name AS subject_display_name,
    r.location_id,
    r.during,
    r.status,
    r.revision,
    COALESCE(ar.response, 'pending'::text) AS attendance_status,
    ar.responded_at AS attendance_responded_at,
    COALESCE(ra.status, 'pending'::text) AS attendance_outcome,
        CASE
            WHEN (ra.status = 'checked_in'::text) THEN ra.checked_in_at
            WHEN (ra.status = 'no_show'::text) THEN ra.no_show_at
            ELSE NULL::timestamp with time zone
        END AS attendance_outcome_at,
    ra.checked_in_at,
    ra.no_show_at,
    ae.estimated_arrival_at AS reported_arrival_estimate_at,
        CASE
            WHEN ((r.status = 'confirmed'::text) AND (COALESCE(ra.status, 'pending'::text) = 'pending'::text)) THEN ae.estimated_arrival_at
            ELSE NULL::timestamp with time zone
        END AS effective_arrival_estimate_at,
    ae.estimated_arrival_at,
    ae.source_kind AS arrival_estimate_source_kind,
    COALESCE(qe.active_queue_entry_count, 0) AS active_queue_entry_count,
        CASE
            WHEN (qe.active_queue_entry_count = 1) THEN qe.id
            ELSE NULL::uuid
        END AS queue_entry_id,
        CASE
            WHEN (qe.active_queue_entry_count = 1) THEN qe.status
            ELSE NULL::text
        END AS queue_entry_status,
        CASE
            WHEN (COALESCE(qe.active_queue_entry_count, 0) <> 1) THEN NULL::boolean
            ELSE ((qe.status = 'waiting'::text) AND (h.id IS NULL) AND (s.id IS NULL))
        END AS recall_eligible,
    h.id AS recall_hold_id,
    h.condition_kind AS recall_hold_kind,
    h.until_at AS recall_hold_until_at,
    h.event_key AS recall_hold_event_key,
    h.reason AS recall_hold_reason,
    s.reason AS active_skip_reason
   FROM (((((((request_engine.reservations r
     JOIN request_engine.parties p ON (((p.organization_id = r.organization_id) AND (p.id = r.subject_party_id))))
     LEFT JOIN LATERAL ( SELECT a.response,
            a.responded_at
           FROM request_engine.attendance_responses a
          WHERE ((a.organization_id = r.organization_id) AND (a.reservation_id = r.id))
          ORDER BY a.responded_at DESC, a.id DESC
         LIMIT 1) ar ON (true))
     LEFT JOIN request_engine.reservation_attendance ra ON (((ra.organization_id = r.organization_id) AND (ra.reservation_id = r.id))))
     LEFT JOIN LATERAL ( SELECT e.estimated_arrival_at,
            e.source_kind
           FROM request_engine.reservation_arrival_estimates e
          WHERE ((e.organization_id = r.organization_id) AND (e.reservation_id = r.id) AND (e.superseded_at IS NULL))
         LIMIT 1) ae ON (true))
     LEFT JOIN LATERAL ( SELECT active.id,
            active.status,
            active.active_queue_entry_count
           FROM ( SELECT q.id,
                    q.status,
                    q.admitted_at,
                    (count(*) OVER ())::integer AS active_queue_entry_count
                   FROM request_engine.queue_entries q
                  WHERE ((q.organization_id = r.organization_id) AND (q.reservation_id = r.id) AND (q.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text])))) active
          ORDER BY active.admitted_at DESC, active.id DESC
         LIMIT 1) qe ON (true))
     LEFT JOIN LATERAL ( SELECT hold.id,
            hold.condition_kind,
            hold.until_at,
            hold.event_key,
            hold.reason
           FROM request_engine.queue_entry_recall_holds hold
          WHERE ((qe.active_queue_entry_count = 1) AND (hold.organization_id = r.organization_id) AND (hold.queue_entry_id = qe.id) AND (hold.released_at IS NULL) AND ((hold.condition_kind <> 'until_time'::text) OR (hold.until_at > clock_timestamp())))
          ORDER BY hold.created_at DESC, hold.id DESC
         LIMIT 1) h ON (true))
     LEFT JOIN LATERAL ( SELECT skip.id,
            skip.reason
           FROM request_engine.queue_entry_skips skip
          WHERE ((qe.active_queue_entry_count = 1) AND (skip.organization_id = r.organization_id) AND (skip.queue_entry_id = qe.id) AND (skip.consumed_at IS NULL))
          ORDER BY skip.created_at DESC, skip.id DESC
         LIMIT 1) s ON (true));


ALTER VIEW request_read.reservation_day_v1 OWNER TO request_engine_schema_owner;

--
-- Name: reservation_status_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.reservation_status_v1 WITH (security_invoker='true') AS
 SELECT r.id AS reservation_id,
    r.organization_id,
    r.offering_version_id,
    r.subject_party_id,
    r.location_id,
    r.during,
    r.status,
    r.revision,
    COALESCE(ar.response, 'pending'::text) AS attendance_status,
    ar.responded_at AS attendance_responded_at,
    ae.estimated_arrival_at
   FROM ((request_engine.reservations r
     LEFT JOIN LATERAL ( SELECT a.response,
            a.responded_at
           FROM request_engine.attendance_responses a
          WHERE ((a.organization_id = r.organization_id) AND (a.reservation_id = r.id))
          ORDER BY a.responded_at DESC, a.id DESC
         LIMIT 1) ar ON (true))
     LEFT JOIN LATERAL ( SELECT e.estimated_arrival_at
           FROM request_engine.reservation_arrival_estimates e
          WHERE ((e.organization_id = r.organization_id) AND (e.reservation_id = r.id) AND (e.superseded_at IS NULL))
         LIMIT 1) ae ON (true));


ALTER VIEW request_read.reservation_status_v1 OWNER TO request_engine_schema_owner;

--
-- Name: service_session_status_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.service_session_status_v1 WITH (security_invoker='true') AS
 SELECT s.id AS service_session_id,
    s.organization_id,
    s.queue_entry_id,
    s.resource_id,
    s.location_id,
    s.actual_workload_classification_id,
    s.status,
    s.started_at,
    s.completed_at,
    s.revision,
    (COALESCE(i.total_interruption_seconds, (0)::numeric))::bigint AS interruption_seconds
   FROM (request_engine.service_sessions s
     LEFT JOIN LATERAL ( SELECT sum(EXTRACT(epoch FROM (COALESCE(i_1.ended_at, clock_timestamp()) - i_1.started_at))) AS total_interruption_seconds
           FROM request_engine.service_session_interruptions i_1
          WHERE ((i_1.organization_id = s.organization_id) AND (i_1.service_session_id = s.id))) i ON (true));


ALTER VIEW request_read.service_session_status_v1 OWNER TO request_engine_schema_owner;

--
-- Data for Name: agent_budget_windows; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: agent_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: agent_profiles; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: attendance_responses; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: audit_records; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: booking_context_terms; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: capacity_claims; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: capacity_holds; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: communication_deliveries; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: communication_escalations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: communication_tasks; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: delegations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: discovery_booking_handoffs; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: discovery_publications; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: external_correlations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: global_identities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: idempotency_records; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_authorities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--

INSERT INTO request_engine.identity_authorities VALUES ('8b2ea2d3-acb2-4442-9709-bff751a31350', 'native', 'request-engine-native', 'active', NULL, 1, '2026-09-27 22:11:02.465504+00');
INSERT INTO request_engine.identity_authorities VALUES ('9e915fcf-775e-4836-8ea3-23119ec9afc3', 'workload', 'request-engine-workload', 'active', NULL, 1, '2026-09-27 22:11:02.465757+00');


--
-- Data for Name: identity_bindings; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_exchange_candidates; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_link_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_link_intents; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_recovery_cases; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_recovery_delivery_tickets; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_recovery_issuance_reservations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: initial_controller_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--

INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v1', 1, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v2', 2, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v3', 3, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v4', 4, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}, {"delegable": true, "capability_key": "controller_policy_upgrade", "authority_plane": "tenant_control"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v5', 5, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}, {"delegable": true, "capability_key": "controller_policy_upgrade", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.inspect_resource", "authority_plane": "operational"}]');


--
-- Data for Name: integration_governance_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: live_capacity_projection_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: live_capacity_workload_estimate_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: location_hours_exceptions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: location_operational_hours; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: location_public_contact_endpoints; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: locations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_credentials; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_identities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_identity_recovery_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_identity_recovery_state; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_recovery_address_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_recovery_address_verifications; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_recovery_addresses; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_recovery_delivery_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_recovery_delivery_requests; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_recovery_intents; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: native_sessions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: offering_resource_requirements; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: offering_service_classifications; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: offering_version_booking_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: offering_version_booking_terms; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: offering_versions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: offerings; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_recovery_actions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_recovery_autonomy_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_recovery_escalations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_recovery_executions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_recovery_incidents; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_recovery_proposals; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: operational_workload_classifications; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: organization_channel_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: organization_party_bindings; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: organization_provisioning_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: organization_public_contact_endpoints; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: organization_root_provisioning_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: organizations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: outbox_messages; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: parties; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: party_administrative_identifiers; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: party_contact_points; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: party_identity_documents; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: party_identity_revisions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_authority_lifecycle_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_bootstrap_intents; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_configuration_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_configuration_revisions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_identity_disable_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_identity_recovery_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_installation_claim_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_instance; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--

INSERT INTO request_engine.platform_instance VALUES (1, '63b59f87-62b8-499c-bb75-fa63e01ae520', 'unclaimed', 1, '8b2ea2d3-acb2-4442-9709-bff751a31350', '9e915fcf-775e-4836-8ea3-23119ec9afc3', '2026-09-27 22:11:02.466113+00', NULL, NULL, NULL);


--
-- Data for Name: platform_owner_invitation_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_owner_invitations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_owner_policies; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--

INSERT INTO request_engine.platform_owner_policies VALUES ('platform-owner-v1', 1, '[{"delegable": true, "capability_key": "platform.principal.provision"}, {"delegable": true, "capability_key": "platform.tenant_provisioner.provision"}, {"delegable": false, "capability_key": "platform.recovery_operator.provision"}, {"delegable": true, "capability_key": "organization.provision"}, {"delegable": false, "capability_key": "platform.identity.recover"}, {"delegable": false, "capability_key": "platform.identity.read"}, {"delegable": false, "capability_key": "platform.identity.recovery_approve"}, {"delegable": false, "capability_key": "platform.provisioner.read"}, {"delegable": false, "capability_key": "platform.provisioner.manage_lifecycle"}]');
INSERT INTO request_engine.platform_owner_policies VALUES ('platform-owner-v2', 2, '[{"delegable": true, "capability_key": "platform.principal.provision"}, {"delegable": true, "capability_key": "platform.tenant_provisioner.provision"}, {"delegable": false, "capability_key": "platform.recovery_operator.provision"}, {"delegable": true, "capability_key": "organization.provision"}, {"delegable": false, "capability_key": "platform.identity.recover"}, {"delegable": false, "capability_key": "platform.identity.read"}, {"delegable": false, "capability_key": "platform.identity.provision"}, {"delegable": false, "capability_key": "platform.identity.recovery_approve"}, {"delegable": false, "capability_key": "platform.provisioner.read"}, {"delegable": false, "capability_key": "platform.provisioner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.owner.read"}, {"delegable": false, "capability_key": "platform.owner.provision"}, {"delegable": false, "capability_key": "platform.owner.manage_lifecycle"}]');
INSERT INTO request_engine.platform_owner_policies VALUES ('platform-owner-v3', 3, '[{"delegable": true, "capability_key": "platform.principal.provision"}, {"delegable": true, "capability_key": "platform.tenant_provisioner.provision"}, {"delegable": false, "capability_key": "platform.recovery_operator.provision"}, {"delegable": true, "capability_key": "organization.provision"}, {"delegable": false, "capability_key": "platform.identity.recover"}, {"delegable": false, "capability_key": "platform.identity.read"}, {"delegable": false, "capability_key": "platform.identity.provision"}, {"delegable": false, "capability_key": "platform.identity.recovery_approve"}, {"delegable": false, "capability_key": "platform.provisioner.read"}, {"delegable": false, "capability_key": "platform.provisioner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.owner.read"}, {"delegable": false, "capability_key": "platform.owner.provision"}, {"delegable": false, "capability_key": "platform.owner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.configuration.read"}, {"delegable": false, "capability_key": "platform.configuration.stage"}, {"delegable": false, "capability_key": "platform.configuration.validate"}, {"delegable": false, "capability_key": "platform.configuration.activate"}, {"delegable": false, "capability_key": "platform.configuration.disable"}, {"delegable": false, "capability_key": "platform.secret.write"}, {"delegable": false, "capability_key": "platform.secret.rotate"}, {"delegable": false, "capability_key": "platform.secret.revoke"}, {"delegable": false, "capability_key": "platform.provider.test"}, {"delegable": false, "capability_key": "platform.readiness.read"}]');


--
-- Data for Name: platform_owner_provisioning_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_recovery_code_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_secret_bindings; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: platform_secret_mutations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: portable_party_identifiers; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: portable_party_identities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: portable_party_profiles; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: principal_authority_grants; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: principal_contacts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: principals; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: provider_events; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: queue_entries; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: queue_entry_operator_selections; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: queue_entry_recall_holds; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: queue_entry_skips; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: recovery_code_sets; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: recovery_codes; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: recovery_source_revisions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reminder_acknowledgements; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reminder_plans; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: representations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: request_definition_versions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: request_definitions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: request_participants; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: requests; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reservation_access; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reservation_arrival_estimates; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reservation_attendance; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reservation_commercial_commitment_context_terms; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reservation_commercial_commitments; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: reservations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_activities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_capabilities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_capability_assignments; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_location_assignments; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_location_availability; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_location_schedule_exceptions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resource_public_profiles; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: resources; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: schedule_exceptions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: scheduled_actions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: service_classification_authority_events; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: service_classifications; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: service_queue_intake_controls; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: service_queues; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: service_session_interruptions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: service_sessions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: setup_pending_identity; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: setup_pending_webauthn_credential; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: setup_sessions; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: shared_capacity_authority_events; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: shared_capacity_bindings; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: shared_capacity_claim_links; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: shared_capacity_identities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: slot_offers; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: slot_opportunities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: staff_memberships; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: waitlist_entries; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: webauthn_challenges; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: webauthn_credentials; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: workload_credentials; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: workload_identities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Name: agent_budget_windows agent_budget_windows_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.agent_budget_windows
    ADD CONSTRAINT agent_budget_windows_pkey PRIMARY KEY (organization_id, agent_principal_id, window_started_at);


--
-- Name: agent_policies agent_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.agent_policies
    ADD CONSTRAINT agent_policies_pkey PRIMARY KEY (organization_id, agent_principal_id);


--
-- Name: agent_profiles agent_profiles_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.agent_profiles
    ADD CONSTRAINT agent_profiles_pkey PRIMARY KEY (principal_id);


--
-- Name: attendance_responses attendance_responses_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.attendance_responses
    ADD CONSTRAINT attendance_responses_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: attendance_responses attendance_responses_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.attendance_responses
    ADD CONSTRAINT attendance_responses_pkey PRIMARY KEY (id);


--
-- Name: audit_records audit_records_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: audit_records audit_records_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_pkey PRIMARY KEY (id);


--
-- Name: booking_context_terms booking_context_terms_no_active_overlap; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.booking_context_terms
    ADD CONSTRAINT booking_context_terms_no_active_overlap EXCLUDE USING gist (organization_id WITH =, resource_location_assignment_id WITH =, offering_version_id WITH =, effective_during WITH &&) WHERE (active);


--
-- Name: booking_context_terms booking_context_terms_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.booking_context_terms
    ADD CONSTRAINT booking_context_terms_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: booking_context_terms booking_context_terms_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.booking_context_terms
    ADD CONSTRAINT booking_context_terms_pkey PRIMARY KEY (id);


--
-- Name: capacity_claims capacity_claims_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: capacity_claims capacity_claims_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_pkey PRIMARY KEY (id);


--
-- Name: capacity_holds capacity_holds_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_holds
    ADD CONSTRAINT capacity_holds_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: capacity_holds capacity_holds_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_holds
    ADD CONSTRAINT capacity_holds_pkey PRIMARY KEY (id);


--
-- Name: communication_deliveries communication_deliveries_organization_id_communication_task_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_deliveries
    ADD CONSTRAINT communication_deliveries_organization_id_communication_task_key UNIQUE (organization_id, communication_task_id, attempt_no);


--
-- Name: communication_deliveries communication_deliveries_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_deliveries
    ADD CONSTRAINT communication_deliveries_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: communication_deliveries communication_deliveries_organization_id_provider_key_provi_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_deliveries
    ADD CONSTRAINT communication_deliveries_organization_id_provider_key_provi_key UNIQUE (organization_id, provider_key, provider_idempotency_key);


--
-- Name: communication_deliveries communication_deliveries_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_deliveries
    ADD CONSTRAINT communication_deliveries_pkey PRIMARY KEY (id);


--
-- Name: communication_escalations communication_escalations_organization_id_parent_task_id_to_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_escalations
    ADD CONSTRAINT communication_escalations_organization_id_parent_task_id_to_key UNIQUE (organization_id, parent_task_id, to_channel, ordinal);


--
-- Name: communication_escalations communication_escalations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_escalations
    ADD CONSTRAINT communication_escalations_pkey PRIMARY KEY (id);


--
-- Name: communication_tasks communication_tasks_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_tasks
    ADD CONSTRAINT communication_tasks_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: communication_tasks communication_tasks_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_tasks
    ADD CONSTRAINT communication_tasks_pkey PRIMARY KEY (id);


--
-- Name: delegations delegations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.delegations
    ADD CONSTRAINT delegations_pkey PRIMARY KEY (id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_pkey PRIMARY KEY (id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_token_hash_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_token_hash_key UNIQUE (token_hash);


--
-- Name: discovery_publications discovery_publications_no_active_overlap; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_no_active_overlap EXCLUDE USING gist (organization_id WITH =, offering_id WITH =, location_id WITH =, COALESCE(resource_id, '00000000-0000-0000-0000-000000000000'::uuid) WITH =, effective_during WITH &&) WHERE ((status = 'active'::text));


--
-- Name: discovery_publications discovery_publications_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: discovery_publications discovery_publications_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_pkey PRIMARY KEY (id);


--
-- Name: external_correlations external_correlations_organization_id_correlation_kind_prov_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.external_correlations
    ADD CONSTRAINT external_correlations_organization_id_correlation_kind_prov_key UNIQUE (organization_id, correlation_kind, provider_key, external_key);


--
-- Name: external_correlations external_correlations_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.external_correlations
    ADD CONSTRAINT external_correlations_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: external_correlations external_correlations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.external_correlations
    ADD CONSTRAINT external_correlations_pkey PRIMARY KEY (id);


--
-- Name: global_identities global_identities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.global_identities
    ADD CONSTRAINT global_identities_pkey PRIMARY KEY (id);


--
-- Name: idempotency_records idempotency_records_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.idempotency_records
    ADD CONSTRAINT idempotency_records_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: idempotency_records idempotency_records_organization_id_principal_id_capability_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.idempotency_records
    ADD CONSTRAINT idempotency_records_organization_id_principal_id_capability_key UNIQUE (organization_id, principal_id, capability, idempotency_key);


--
-- Name: idempotency_records idempotency_records_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.idempotency_records
    ADD CONSTRAINT idempotency_records_pkey PRIMARY KEY (id);


--
-- Name: identity_authorities identity_authorities_kind_issuer_or_environment_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_authorities
    ADD CONSTRAINT identity_authorities_kind_issuer_or_environment_key UNIQUE (kind, issuer_or_environment);


--
-- Name: identity_authorities identity_authorities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_authorities
    ADD CONSTRAINT identity_authorities_pkey PRIMARY KEY (id);


--
-- Name: identity_bindings identity_bindings_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_bindings
    ADD CONSTRAINT identity_bindings_pkey PRIMARY KEY (id);


--
-- Name: identity_bindings identity_bindings_tenant_principal_id_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_bindings
    ADD CONSTRAINT identity_bindings_tenant_principal_id_uq UNIQUE (organization_id, principal_id, id);


--
-- Name: identity_exchange_candidates identity_exchange_candidates_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_exchange_candidates
    ADD CONSTRAINT identity_exchange_candidates_pkey PRIMARY KEY (id);


--
-- Name: identity_link_facts identity_link_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_link_facts
    ADD CONSTRAINT identity_link_facts_pkey PRIMARY KEY (id);


--
-- Name: identity_link_intents identity_link_intents_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_link_intents
    ADD CONSTRAINT identity_link_intents_pkey PRIMARY KEY (id);


--
-- Name: identity_recovery_cases identity_recovery_cases_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_recovery_cases
    ADD CONSTRAINT identity_recovery_cases_pkey PRIMARY KEY (id);


--
-- Name: identity_recovery_delivery_tickets identity_recovery_delivery_tickets_case_generation_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_recovery_delivery_tickets
    ADD CONSTRAINT identity_recovery_delivery_tickets_case_generation_uq UNIQUE (case_id, generation);


--
-- Name: identity_recovery_delivery_tickets identity_recovery_delivery_tickets_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_recovery_delivery_tickets
    ADD CONSTRAINT identity_recovery_delivery_tickets_pkey PRIMARY KEY (id);


--
-- Name: identity_recovery_issuance_reservations identity_recovery_issuance_reservations_key_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_recovery_issuance_reservations
    ADD CONSTRAINT identity_recovery_issuance_reservations_key_uq UNIQUE (case_id, idempotency_key_digest);


--
-- Name: identity_recovery_issuance_reservations identity_recovery_issuance_reservations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_recovery_issuance_reservations
    ADD CONSTRAINT identity_recovery_issuance_reservations_pkey PRIMARY KEY (case_id, generation);


--
-- Name: initial_controller_policies initial_controller_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.initial_controller_policies
    ADD CONSTRAINT initial_controller_policies_pkey PRIMARY KEY (policy_key);


--
-- Name: integration_governance_facts integration_governance_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.integration_governance_facts
    ADD CONSTRAINT integration_governance_facts_pkey PRIMARY KEY (id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_poli_organization_id_service_queue_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_poli_organization_id_service_queue_key UNIQUE (organization_id, service_queue_id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_policies_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_policies_pkey PRIMARY KEY (id);


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estima_organization_id_workload_clas_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies
    ADD CONSTRAINT live_capacity_workload_estima_organization_id_workload_clas_key UNIQUE (organization_id, workload_classification_id);


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estimate_policies_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies
    ADD CONSTRAINT live_capacity_workload_estimate_policies_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estimate_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies
    ADD CONSTRAINT live_capacity_workload_estimate_policies_pkey PRIMARY KEY (id);


--
-- Name: location_hours_exceptions location_hours_exceptions_no_active_overlap; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_hours_exceptions
    ADD CONSTRAINT location_hours_exceptions_no_active_overlap EXCLUDE USING gist (organization_id WITH =, location_id WITH =, during WITH &&) WHERE (active);


--
-- Name: location_hours_exceptions location_hours_exceptions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_hours_exceptions
    ADD CONSTRAINT location_hours_exceptions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: location_hours_exceptions location_hours_exceptions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_hours_exceptions
    ADD CONSTRAINT location_hours_exceptions_pkey PRIMARY KEY (id);


--
-- Name: location_operational_hours location_operational_hours_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_operational_hours
    ADD CONSTRAINT location_operational_hours_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: location_operational_hours location_operational_hours_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_operational_hours
    ADD CONSTRAINT location_operational_hours_pkey PRIMARY KEY (id);


--
-- Name: location_public_contact_endpoints location_public_contact_endpo_organization_id_location_id_c_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_public_contact_endpoints
    ADD CONSTRAINT location_public_contact_endpo_organization_id_location_id_c_key UNIQUE (organization_id, location_id, channel, normalized_value);


--
-- Name: location_public_contact_endpoints location_public_contact_endpoints_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_public_contact_endpoints
    ADD CONSTRAINT location_public_contact_endpoints_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: location_public_contact_endpoints location_public_contact_endpoints_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_public_contact_endpoints
    ADD CONSTRAINT location_public_contact_endpoints_pkey PRIMARY KEY (id);


--
-- Name: locations locations_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.locations
    ADD CONSTRAINT locations_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: locations locations_organization_id_location_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.locations
    ADD CONSTRAINT locations_organization_id_location_key_key UNIQUE (organization_id, location_key);


--
-- Name: locations locations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.locations
    ADD CONSTRAINT locations_pkey PRIMARY KEY (id);


--
-- Name: native_credentials native_credentials_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_credentials
    ADD CONSTRAINT native_credentials_pkey PRIMARY KEY (id);


--
-- Name: native_identities native_identities_identity_authority_id_login_handle_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_identities
    ADD CONSTRAINT native_identities_identity_authority_id_login_handle_key UNIQUE (identity_authority_id, login_handle);


--
-- Name: native_identities native_identities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_identities
    ADD CONSTRAINT native_identities_pkey PRIMARY KEY (id);


--
-- Name: native_identity_recovery_facts native_identity_recovery_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_identity_recovery_facts
    ADD CONSTRAINT native_identity_recovery_facts_pkey PRIMARY KEY (id);


--
-- Name: native_identity_recovery_state native_identity_recovery_state_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_identity_recovery_state
    ADD CONSTRAINT native_identity_recovery_state_pkey PRIMARY KEY (native_identity_id);


--
-- Name: native_recovery_address_facts native_recovery_address_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_address_facts
    ADD CONSTRAINT native_recovery_address_facts_pkey PRIMARY KEY (id);


--
-- Name: native_recovery_address_verifications native_recovery_address_verifications_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_address_verifications
    ADD CONSTRAINT native_recovery_address_verifications_pkey PRIMARY KEY (id);


--
-- Name: native_recovery_address_verifications native_recovery_address_verifications_token_digest_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_address_verifications
    ADD CONSTRAINT native_recovery_address_verifications_token_digest_key UNIQUE (token_digest);


--
-- Name: native_recovery_addresses native_recovery_addresses_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_addresses
    ADD CONSTRAINT native_recovery_addresses_pkey PRIMARY KEY (id);


--
-- Name: native_recovery_delivery_facts native_recovery_delivery_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_delivery_facts
    ADD CONSTRAINT native_recovery_delivery_facts_pkey PRIMARY KEY (id);


--
-- Name: native_recovery_delivery_requests native_recovery_delivery_requests_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_delivery_requests
    ADD CONSTRAINT native_recovery_delivery_requests_pkey PRIMARY KEY (id);


--
-- Name: native_recovery_intents native_recovery_intents_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_recovery_intents
    ADD CONSTRAINT native_recovery_intents_pkey PRIMARY KEY (id);


--
-- Name: native_sessions native_sessions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_sessions
    ADD CONSTRAINT native_sessions_pkey PRIMARY KEY (id);


--
-- Name: offering_resource_requirements offering_resource_requirement_organization_id_offering_vers_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_resource_requirements
    ADD CONSTRAINT offering_resource_requirement_organization_id_offering_vers_key UNIQUE (organization_id, offering_version_id, ordinal);


--
-- Name: offering_resource_requirements offering_resource_requirements_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_resource_requirements
    ADD CONSTRAINT offering_resource_requirements_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: offering_resource_requirements offering_resource_requirements_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_resource_requirements
    ADD CONSTRAINT offering_resource_requirements_pkey PRIMARY KEY (id);


--
-- Name: offering_service_classifications offering_service_classifications_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_service_classifications
    ADD CONSTRAINT offering_service_classifications_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: offering_service_classifications offering_service_classifications_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_service_classifications
    ADD CONSTRAINT offering_service_classifications_pkey PRIMARY KEY (id);


--
-- Name: offering_version_booking_policies offering_version_booking_poli_organization_id_offering_vers_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_policies
    ADD CONSTRAINT offering_version_booking_poli_organization_id_offering_vers_key UNIQUE (organization_id, offering_version_id, revision);


--
-- Name: offering_version_booking_policies offering_version_booking_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_policies
    ADD CONSTRAINT offering_version_booking_policies_pkey PRIMARY KEY (id);


--
-- Name: offering_version_booking_terms offering_version_booking_term_organization_id_offering_vers_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_terms
    ADD CONSTRAINT offering_version_booking_term_organization_id_offering_vers_key UNIQUE (organization_id, offering_version_id);


--
-- Name: offering_version_booking_terms offering_version_booking_terms_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_terms
    ADD CONSTRAINT offering_version_booking_terms_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: offering_version_booking_terms offering_version_booking_terms_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_terms
    ADD CONSTRAINT offering_version_booking_terms_pkey PRIMARY KEY (id);


--
-- Name: offering_versions offering_versions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_versions
    ADD CONSTRAINT offering_versions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: offering_versions offering_versions_organization_id_offering_id_version_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_versions
    ADD CONSTRAINT offering_versions_organization_id_offering_id_version_key UNIQUE (organization_id, offering_id, version);


--
-- Name: offering_versions offering_versions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_versions
    ADD CONSTRAINT offering_versions_pkey PRIMARY KEY (id);


--
-- Name: offerings offerings_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offerings
    ADD CONSTRAINT offerings_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: offerings offerings_organization_id_offering_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offerings
    ADD CONSTRAINT offerings_organization_id_offering_key_key UNIQUE (organization_id, offering_key);


--
-- Name: offerings offerings_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offerings
    ADD CONSTRAINT offerings_pkey PRIMARY KEY (id);


--
-- Name: operational_recovery_actions operational_recovery_actions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_actions
    ADD CONSTRAINT operational_recovery_actions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: operational_recovery_actions operational_recovery_actions_organization_id_principal_id_i_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_actions
    ADD CONSTRAINT operational_recovery_actions_organization_id_principal_id_i_key UNIQUE (organization_id, principal_id, idempotency_key);


--
-- Name: operational_recovery_actions operational_recovery_actions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_actions
    ADD CONSTRAINT operational_recovery_actions_pkey PRIMARY KEY (id);


--
-- Name: operational_recovery_autonomy_policies operational_recovery_autonomy_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_autonomy_policies
    ADD CONSTRAINT operational_recovery_autonomy_policies_pkey PRIMARY KEY (organization_id, service_queue_id);


--
-- Name: operational_recovery_escalations operational_recovery_escalati_organization_id_incident_id_s_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_escalations
    ADD CONSTRAINT operational_recovery_escalati_organization_id_incident_id_s_key UNIQUE (organization_id, incident_id, source_revision);


--
-- Name: operational_recovery_escalations operational_recovery_escalations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_escalations
    ADD CONSTRAINT operational_recovery_escalations_pkey PRIMARY KEY (id);


--
-- Name: operational_recovery_executions operational_recovery_executio_organization_id_communication_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executio_organization_id_communication_key UNIQUE (organization_id, communication_task_id);


--
-- Name: operational_recovery_executions operational_recovery_executio_organization_id_executed_by_p_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executio_organization_id_executed_by_p_key UNIQUE (organization_id, executed_by_principal_id, idempotency_key);


--
-- Name: operational_recovery_executions operational_recovery_executio_organization_id_proposal_id_r_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executio_organization_id_proposal_id_r_key UNIQUE (organization_id, proposal_id, reservation_id);


--
-- Name: operational_recovery_executions operational_recovery_executions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: operational_recovery_executions operational_recovery_executions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executions_pkey PRIMARY KEY (id);


--
-- Name: operational_recovery_incidents operational_recovery_incidents_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incidents_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: operational_recovery_incidents operational_recovery_incidents_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incidents_pkey PRIMARY KEY (id);


--
-- Name: operational_recovery_proposals operational_recovery_proposal_organization_id_created_by_pr_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposal_organization_id_created_by_pr_key UNIQUE (organization_id, created_by_principal_id, idempotency_key);


--
-- Name: operational_recovery_proposals operational_recovery_proposals_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposals_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: operational_recovery_proposals operational_recovery_proposals_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposals_pkey PRIMARY KEY (id);


--
-- Name: operational_workload_classifications operational_workload_classific_organization_id_workload_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_workload_classifications
    ADD CONSTRAINT operational_workload_classific_organization_id_workload_key_key UNIQUE (organization_id, workload_key);


--
-- Name: operational_workload_classifications operational_workload_classifications_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_workload_classifications
    ADD CONSTRAINT operational_workload_classifications_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: operational_workload_classifications operational_workload_classifications_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_workload_classifications
    ADD CONSTRAINT operational_workload_classifications_pkey PRIMARY KEY (id);


--
-- Name: organization_channel_policies organization_channel_policies_organization_id_purpose_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_channel_policies
    ADD CONSTRAINT organization_channel_policies_organization_id_purpose_key UNIQUE (organization_id, purpose);


--
-- Name: organization_channel_policies organization_channel_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_channel_policies
    ADD CONSTRAINT organization_channel_policies_pkey PRIMARY KEY (id);


--
-- Name: organization_party_bindings organization_party_bindings_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_party_bindings
    ADD CONSTRAINT organization_party_bindings_pkey PRIMARY KEY (id);


--
-- Name: organization_provisioning_facts organization_provisioning_facts_organization_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_provisioning_facts
    ADD CONSTRAINT organization_provisioning_facts_organization_id_key UNIQUE (organization_id);


--
-- Name: organization_provisioning_facts organization_provisioning_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_provisioning_facts
    ADD CONSTRAINT organization_provisioning_facts_pkey PRIMARY KEY (id);


--
-- Name: organization_public_contact_endpoints organization_public_contact_e_organization_id_channel_norma_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_public_contact_endpoints
    ADD CONSTRAINT organization_public_contact_e_organization_id_channel_norma_key UNIQUE (organization_id, channel, normalized_value);


--
-- Name: organization_public_contact_endpoints organization_public_contact_endpoints_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_public_contact_endpoints
    ADD CONSTRAINT organization_public_contact_endpoints_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: organization_public_contact_endpoints organization_public_contact_endpoints_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_public_contact_endpoints
    ADD CONSTRAINT organization_public_contact_endpoints_pkey PRIMARY KEY (id);


--
-- Name: organization_root_provisioning_facts organization_root_provisioning_fact_controller_principal_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_root_provisioning_facts
    ADD CONSTRAINT organization_root_provisioning_fact_controller_principal_id_key UNIQUE (controller_principal_id);


--
-- Name: organization_root_provisioning_facts organization_root_provisioning_facts_controller_binding_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_root_provisioning_facts
    ADD CONSTRAINT organization_root_provisioning_facts_controller_binding_id_key UNIQUE (controller_binding_id);


--
-- Name: organization_root_provisioning_facts organization_root_provisioning_facts_organization_party_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_root_provisioning_facts
    ADD CONSTRAINT organization_root_provisioning_facts_organization_party_id_key UNIQUE (organization_party_id);


--
-- Name: organization_root_provisioning_facts organization_root_provisioning_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_root_provisioning_facts
    ADD CONSTRAINT organization_root_provisioning_facts_pkey PRIMARY KEY (organization_id);


--
-- Name: organizations organizations_organization_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organizations
    ADD CONSTRAINT organizations_organization_key_key UNIQUE (organization_key);


--
-- Name: organizations organizations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organizations
    ADD CONSTRAINT organizations_pkey PRIMARY KEY (id);


--
-- Name: outbox_messages outbox_messages_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.outbox_messages
    ADD CONSTRAINT outbox_messages_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: outbox_messages outbox_messages_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.outbox_messages
    ADD CONSTRAINT outbox_messages_pkey PRIMARY KEY (id);


--
-- Name: parties parties_organization_id_external_ref_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.parties
    ADD CONSTRAINT parties_organization_id_external_ref_key UNIQUE (organization_id, external_ref);


--
-- Name: parties parties_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.parties
    ADD CONSTRAINT parties_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: parties parties_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.parties
    ADD CONSTRAINT parties_pkey PRIMARY KEY (id);


--
-- Name: party_administrative_identifiers party_administrative_identifiers_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_administrative_identifiers
    ADD CONSTRAINT party_administrative_identifiers_pkey PRIMARY KEY (id);


--
-- Name: party_contact_points party_contact_points_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_contact_points
    ADD CONSTRAINT party_contact_points_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: party_contact_points party_contact_points_organization_id_party_id_channel_norma_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_contact_points
    ADD CONSTRAINT party_contact_points_organization_id_party_id_channel_norma_key UNIQUE (organization_id, party_id, channel, normalized_value);


--
-- Name: party_contact_points party_contact_points_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_contact_points
    ADD CONSTRAINT party_contact_points_pkey PRIMARY KEY (id);


--
-- Name: party_identity_documents party_identity_documents_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_pkey PRIMARY KEY (id);


--
-- Name: party_identity_revisions party_identity_revisions_organization_id_party_id_revision_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_revisions
    ADD CONSTRAINT party_identity_revisions_organization_id_party_id_revision_key UNIQUE (organization_id, party_id, revision);


--
-- Name: party_identity_revisions party_identity_revisions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_revisions
    ADD CONSTRAINT party_identity_revisions_pkey PRIMARY KEY (id);


--
-- Name: platform_authority_lifecycle_facts platform_authority_lifecycle_facts_actor_key_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_authority_lifecycle_facts
    ADD CONSTRAINT platform_authority_lifecycle_facts_actor_key_uq UNIQUE (actor_principal_id, capability_key, idempotency_key_digest);


--
-- Name: platform_authority_lifecycle_facts platform_authority_lifecycle_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_authority_lifecycle_facts
    ADD CONSTRAINT platform_authority_lifecycle_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_bootstrap_intents platform_bootstrap_intents_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_bootstrap_intents
    ADD CONSTRAINT platform_bootstrap_intents_pkey PRIMARY KEY (id);


--
-- Name: platform_bootstrap_intents platform_bootstrap_intents_token_digest_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_bootstrap_intents
    ADD CONSTRAINT platform_bootstrap_intents_token_digest_key UNIQUE (token_digest);


--
-- Name: platform_configuration_facts platform_configuration_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_configuration_facts
    ADD CONSTRAINT platform_configuration_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_configuration_revisions platform_configuration_revision_configuration_kind_revision_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_configuration_revisions
    ADD CONSTRAINT platform_configuration_revision_configuration_kind_revision_key UNIQUE (configuration_kind, revision);


--
-- Name: platform_configuration_revisions platform_configuration_revisions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_configuration_revisions
    ADD CONSTRAINT platform_configuration_revisions_pkey PRIMARY KEY (id);


--
-- Name: platform_identity_disable_facts platform_identity_disable_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_identity_disable_facts
    ADD CONSTRAINT platform_identity_disable_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_identity_recovery_facts platform_identity_recovery_facts_actor_key_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_identity_recovery_facts
    ADD CONSTRAINT platform_identity_recovery_facts_actor_key_uq UNIQUE (actor_principal_id, action, idempotency_key_digest);


--
-- Name: platform_identity_recovery_facts platform_identity_recovery_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_identity_recovery_facts
    ADD CONSTRAINT platform_identity_recovery_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_installation_claim_facts platform_installation_claim_facts_idempotency_key_digest_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_installation_claim_facts
    ADD CONSTRAINT platform_installation_claim_facts_idempotency_key_digest_key UNIQUE (idempotency_key_digest);


--
-- Name: platform_installation_claim_facts platform_installation_claim_facts_instance_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_installation_claim_facts
    ADD CONSTRAINT platform_installation_claim_facts_instance_id_key UNIQUE (instance_id);


--
-- Name: platform_installation_claim_facts platform_installation_claim_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_installation_claim_facts
    ADD CONSTRAINT platform_installation_claim_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_instance platform_instance_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_instance
    ADD CONSTRAINT platform_instance_id_key UNIQUE (id);


--
-- Name: platform_instance platform_instance_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_instance
    ADD CONSTRAINT platform_instance_pkey PRIMARY KEY (singleton_key);


--
-- Name: platform_owner_invitations platform_owner_invitation_actor_key_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_invitations
    ADD CONSTRAINT platform_owner_invitation_actor_key_uq UNIQUE (invited_by_principal_id, idempotency_key_digest);


--
-- Name: platform_owner_invitation_facts platform_owner_invitation_fact_idempotency_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_invitation_facts
    ADD CONSTRAINT platform_owner_invitation_fact_idempotency_uq UNIQUE (actor_principal_id, action, idempotency_key_digest);


--
-- Name: platform_owner_invitation_facts platform_owner_invitation_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_invitation_facts
    ADD CONSTRAINT platform_owner_invitation_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_owner_invitations platform_owner_invitations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_invitations
    ADD CONSTRAINT platform_owner_invitations_pkey PRIMARY KEY (id);


--
-- Name: platform_owner_invitations platform_owner_invitations_token_digest_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_invitations
    ADD CONSTRAINT platform_owner_invitations_token_digest_key UNIQUE (token_digest);


--
-- Name: platform_owner_policies platform_owner_policies_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_policies
    ADD CONSTRAINT platform_owner_policies_pkey PRIMARY KEY (policy_key);


--
-- Name: platform_owner_provisioning_facts platform_owner_provisioning_actor_key_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_provisioning_facts
    ADD CONSTRAINT platform_owner_provisioning_actor_key_uq UNIQUE (actor_principal_id, idempotency_key_digest);


--
-- Name: platform_owner_provisioning_facts platform_owner_provisioning_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_owner_provisioning_facts
    ADD CONSTRAINT platform_owner_provisioning_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_recovery_code_facts platform_recovery_code_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_recovery_code_facts
    ADD CONSTRAINT platform_recovery_code_facts_pkey PRIMARY KEY (id);


--
-- Name: platform_secret_bindings platform_secret_bindings_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_secret_bindings
    ADD CONSTRAINT platform_secret_bindings_pkey PRIMARY KEY (id);


--
-- Name: platform_secret_bindings platform_secret_bindings_secret_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_secret_bindings
    ADD CONSTRAINT platform_secret_bindings_secret_id_key UNIQUE (secret_id);


--
-- Name: platform_secret_mutations platform_secret_mutations_actor_principal_id_capability_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_secret_mutations
    ADD CONSTRAINT platform_secret_mutations_actor_principal_id_capability_key_key UNIQUE (actor_principal_id, capability_key, idempotency_key_digest);


--
-- Name: platform_secret_mutations platform_secret_mutations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.platform_secret_mutations
    ADD CONSTRAINT platform_secret_mutations_pkey PRIMARY KEY (id);


--
-- Name: portable_party_identifiers portable_party_identifiers_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_identifiers
    ADD CONSTRAINT portable_party_identifiers_pkey PRIMARY KEY (id);


--
-- Name: portable_party_identities portable_party_identities_id_party_kind_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_identities
    ADD CONSTRAINT portable_party_identities_id_party_kind_key UNIQUE (id, party_kind);


--
-- Name: portable_party_identities portable_party_identities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_identities
    ADD CONSTRAINT portable_party_identities_pkey PRIMARY KEY (id);


--
-- Name: portable_party_profiles portable_party_profiles_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_profiles
    ADD CONSTRAINT portable_party_profiles_pkey PRIMARY KEY (portable_party_id, publisher_organization_id);


--
-- Name: principal_authority_grants principal_authority_grants_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_authority_grants
    ADD CONSTRAINT principal_authority_grants_pkey PRIMARY KEY (id);


--
-- Name: principal_contacts principal_contacts_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_contacts
    ADD CONSTRAINT principal_contacts_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: principal_contacts principal_contacts_organization_id_principal_id_channel_nor_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_contacts
    ADD CONSTRAINT principal_contacts_organization_id_principal_id_channel_nor_key UNIQUE (organization_id, principal_id, channel, normalized_value);


--
-- Name: principal_contacts principal_contacts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_contacts
    ADD CONSTRAINT principal_contacts_pkey PRIMARY KEY (id);


--
-- Name: principals principals_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principals
    ADD CONSTRAINT principals_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: principals principals_organization_id_principal_kind_external_subject_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principals
    ADD CONSTRAINT principals_organization_id_principal_kind_external_subject_key UNIQUE (organization_id, principal_kind, external_subject);


--
-- Name: principals principals_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principals
    ADD CONSTRAINT principals_pkey PRIMARY KEY (id);


--
-- Name: provider_events provider_events_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.provider_events
    ADD CONSTRAINT provider_events_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: provider_events provider_events_organization_id_provider_key_connection_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.provider_events
    ADD CONSTRAINT provider_events_organization_id_provider_key_connection_key_key UNIQUE (organization_id, provider_key, connection_key, provider_event_id);


--
-- Name: provider_events provider_events_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.provider_events
    ADD CONSTRAINT provider_events_pkey PRIMARY KEY (id);


--
-- Name: queue_entries queue_entries_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: queue_entries queue_entries_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_pkey PRIMARY KEY (id);


--
-- Name: queue_entry_operator_selections queue_entry_operator_selections_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_operator_selections
    ADD CONSTRAINT queue_entry_operator_selections_pkey PRIMARY KEY (id);


--
-- Name: queue_entry_recall_holds queue_entry_recall_holds_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_recall_holds
    ADD CONSTRAINT queue_entry_recall_holds_pkey PRIMARY KEY (id);


--
-- Name: queue_entry_skips queue_entry_skips_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_skips
    ADD CONSTRAINT queue_entry_skips_pkey PRIMARY KEY (id);


--
-- Name: recovery_code_sets recovery_code_sets_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.recovery_code_sets
    ADD CONSTRAINT recovery_code_sets_pkey PRIMARY KEY (id);


--
-- Name: recovery_codes recovery_codes_code_digest_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.recovery_codes
    ADD CONSTRAINT recovery_codes_code_digest_key UNIQUE (code_digest);


--
-- Name: recovery_codes recovery_codes_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.recovery_codes
    ADD CONSTRAINT recovery_codes_pkey PRIMARY KEY (id);


--
-- Name: recovery_source_revisions recovery_source_revisions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.recovery_source_revisions
    ADD CONSTRAINT recovery_source_revisions_pkey PRIMARY KEY (organization_id, service_queue_id);


--
-- Name: reminder_acknowledgements reminder_acknowledgements_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_acknowledgements
    ADD CONSTRAINT reminder_acknowledgements_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: reminder_acknowledgements reminder_acknowledgements_organization_id_reminder_plan_id__key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_acknowledgements
    ADD CONSTRAINT reminder_acknowledgements_organization_id_reminder_plan_id__key UNIQUE (organization_id, reminder_plan_id, occurrence_at, subject_party_id);


--
-- Name: reminder_acknowledgements reminder_acknowledgements_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_acknowledgements
    ADD CONSTRAINT reminder_acknowledgements_pkey PRIMARY KEY (id);


--
-- Name: reminder_plans reminder_plans_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_plans
    ADD CONSTRAINT reminder_plans_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: reminder_plans reminder_plans_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_plans
    ADD CONSTRAINT reminder_plans_pkey PRIMARY KEY (id);


--
-- Name: representations representations_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.representations
    ADD CONSTRAINT representations_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: representations representations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.representations
    ADD CONSTRAINT representations_pkey PRIMARY KEY (id);


--
-- Name: request_definition_versions request_definition_versions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definition_versions
    ADD CONSTRAINT request_definition_versions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: request_definition_versions request_definition_versions_organization_id_request_definit_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definition_versions
    ADD CONSTRAINT request_definition_versions_organization_id_request_definit_key UNIQUE (organization_id, request_definition_id, version);


--
-- Name: request_definition_versions request_definition_versions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definition_versions
    ADD CONSTRAINT request_definition_versions_pkey PRIMARY KEY (id);


--
-- Name: request_definitions request_definitions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definitions
    ADD CONSTRAINT request_definitions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: request_definitions request_definitions_organization_id_request_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definitions
    ADD CONSTRAINT request_definitions_organization_id_request_key_key UNIQUE (organization_id, request_key);


--
-- Name: request_definitions request_definitions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definitions
    ADD CONSTRAINT request_definitions_pkey PRIMARY KEY (id);


--
-- Name: request_participants request_participants_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_participants
    ADD CONSTRAINT request_participants_pkey PRIMARY KEY (organization_id, request_id, party_id, role_key);


--
-- Name: requests requests_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.requests
    ADD CONSTRAINT requests_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: requests requests_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.requests
    ADD CONSTRAINT requests_pkey PRIMARY KEY (id);


--
-- Name: reservation_access reservation_access_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_access
    ADD CONSTRAINT reservation_access_organization_id_id_key UNIQUE (organization_id, id);


--
