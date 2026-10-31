    template_key text NOT NULL,
    template_version integer NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reminder_plans_channel_policy_check CHECK ((jsonb_typeof(channel_policy) = 'object'::text)),
    CONSTRAINT reminder_plans_purpose_check CHECK ((purpose <> ''::text)),
    CONSTRAINT reminder_plans_revision_check CHECK ((revision > 0)),
    CONSTRAINT reminder_plans_schedule_contract_version_ck CHECK (((jsonb_typeof(schedule_spec) = 'object'::text) AND ((schedule_spec ->> 'type'::text) = 'daily_times'::text) AND (schedule_spec ? 'version'::text) AND (jsonb_typeof((schedule_spec -> 'version'::text)) = 'number'::text) AND ((schedule_spec -> 'version'::text) = '1'::jsonb))),
    CONSTRAINT reminder_plans_schedule_spec_check CHECK ((jsonb_typeof(schedule_spec) = 'object'::text)),
    CONSTRAINT reminder_plans_schedule_spec_check1 CHECK (((schedule_spec ->> 'type'::text) = 'daily_times'::text)),
    CONSTRAINT reminder_plans_status_check CHECK ((status = ANY (ARRAY['active'::text, 'cancelled'::text, 'completed'::text]))),
    CONSTRAINT reminder_plans_template_key_check CHECK ((template_key <> ''::text)),
    CONSTRAINT reminder_plans_template_version_check CHECK ((template_version > 0)),
    CONSTRAINT reminder_plans_timezone_check CHECK ((timezone <> ''::text))
);


ALTER TABLE request_engine.reminder_plans OWNER TO request_engine_schema_owner;

--
-- Name: representations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.representations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    represented_party_id uuid NOT NULL,
    scope_key text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    valid_from timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    valid_until timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    authority_kind text DEFAULT 'delegated'::text NOT NULL,
    CONSTRAINT representations_authority_kind_check CHECK ((authority_kind = ANY (ARRAY['self'::text, 'guardian'::text, 'authorized_contact'::text, 'delegated'::text]))),
    CONSTRAINT representations_check CHECK (((valid_until IS NULL) OR (valid_until > valid_from))),
    CONSTRAINT representations_revision_check CHECK ((revision > 0)),
    CONSTRAINT representations_scope_key_check CHECK ((scope_key <> ''::text)),
    CONSTRAINT representations_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text, 'expired'::text]))),
    CONSTRAINT representations_status_v3_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.representations OWNER TO request_engine_schema_owner;

--
-- Name: request_definition_versions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.request_definition_versions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    request_definition_id uuid NOT NULL,
    version integer NOT NULL,
    input_schema jsonb DEFAULT '{}'::jsonb NOT NULL,
    result_schema jsonb,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT request_definition_versions_input_schema_check CHECK ((jsonb_typeof(input_schema) = 'object'::text)),
    CONSTRAINT request_definition_versions_result_schema_check CHECK (((result_schema IS NULL) OR (jsonb_typeof(result_schema) = 'object'::text))),
    CONSTRAINT request_definition_versions_version_check CHECK ((version > 0))
);


ALTER TABLE request_engine.request_definition_versions OWNER TO request_engine_schema_owner;

--
-- Name: request_definitions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.request_definitions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    request_key text NOT NULL,
    display_name text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    CONSTRAINT request_definitions_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT request_definitions_request_key_check CHECK ((request_key <> ''::text)),
    CONSTRAINT request_definitions_revision_check CHECK ((revision > 0))
);


ALTER TABLE request_engine.request_definitions OWNER TO request_engine_schema_owner;

--
-- Name: request_participants; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.request_participants (
    organization_id uuid NOT NULL,
    request_id uuid NOT NULL,
    party_id uuid NOT NULL,
    role_key text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT request_participants_role_key_check CHECK ((role_key <> ''::text))
);


ALTER TABLE request_engine.request_participants OWNER TO request_engine_schema_owner;

--
-- Name: requests; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.requests (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    request_definition_version_id uuid NOT NULL,
    requester_party_id uuid,
    recipient_party_id uuid,
    status text DEFAULT 'open'::text NOT NULL,
    payload jsonb NOT NULL,
    result_payload jsonb,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT requests_check CHECK ((((status = 'open'::text) AND (completed_at IS NULL)) OR (status <> 'open'::text))),
    CONSTRAINT requests_revision_check CHECK ((revision > 0)),
    CONSTRAINT requests_status_check CHECK ((status = ANY (ARRAY['open'::text, 'completed'::text, 'cancelled'::text, 'failed'::text])))
);


ALTER TABLE request_engine.requests OWNER TO request_engine_schema_owner;

--
-- Name: reservation_access; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reservation_access (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    reservation_revision bigint NOT NULL,
    access_key text NOT NULL,
    kind text NOT NULL,
    provider_key text,
    materialization_key text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    access_uri text,
    external_ref text,
    public_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    provisioned_at timestamp with time zone,
    revoked_at timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reservation_access_access_key_check CHECK ((access_key <> ''::text)),
    CONSTRAINT reservation_access_check CHECK (((status <> 'ready'::text) OR ((provisioned_at IS NOT NULL) AND ((access_uri IS NOT NULL) OR (external_ref IS NOT NULL) OR (public_data <> '{}'::jsonb))))),
    CONSTRAINT reservation_access_check1 CHECK (((status <> 'revoked'::text) OR (revoked_at IS NOT NULL))),
    CONSTRAINT reservation_access_check2 CHECK (((status = 'revoked'::text) OR (revoked_at IS NULL))),
    CONSTRAINT reservation_access_kind_check CHECK ((kind = ANY (ARRAY['video_link'::text, 'phone'::text, 'physical_location'::text, 'instructions'::text, 'external_session'::text]))),
    CONSTRAINT reservation_access_materialization_key_check CHECK ((materialization_key <> ''::text)),
    CONSTRAINT reservation_access_public_data_check CHECK ((jsonb_typeof(public_data) = 'object'::text)),
    CONSTRAINT reservation_access_reservation_revision_check CHECK ((reservation_revision > 0)),
    CONSTRAINT reservation_access_revision_check CHECK ((revision > 0)),
    CONSTRAINT reservation_access_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'ready'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.reservation_access OWNER TO request_engine_schema_owner;

--
-- Name: reservation_arrival_estimates; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reservation_arrival_estimates (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    estimated_arrival_at timestamp with time zone NOT NULL,
    source_kind text NOT NULL,
    asserted_by_principal_id uuid,
    asserted_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    superseded_at timestamp with time zone,
    CONSTRAINT reservation_arrival_estimates_check CHECK (((superseded_at IS NULL) OR (superseded_at >= asserted_at))),
    CONSTRAINT reservation_arrival_estimates_source_kind_check CHECK ((source_kind = ANY (ARRAY['customer'::text, 'operator'::text])))
);

ALTER TABLE ONLY request_engine.reservation_arrival_estimates FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.reservation_arrival_estimates OWNER TO request_engine_schema_owner;

--
-- Name: reservation_attendance; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reservation_attendance (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    checked_in_at timestamp with time zone,
    no_show_at timestamp with time zone,
    source_key text,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reservation_attendance_check CHECK ((((status = 'pending'::text) AND (checked_in_at IS NULL) AND (no_show_at IS NULL)) OR ((status = 'checked_in'::text) AND (checked_in_at IS NOT NULL) AND (no_show_at IS NULL)) OR ((status = 'no_show'::text) AND (checked_in_at IS NULL) AND (no_show_at IS NOT NULL)))),
    CONSTRAINT reservation_attendance_revision_check CHECK ((revision > 0)),
    CONSTRAINT reservation_attendance_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'checked_in'::text, 'no_show'::text])))
);


ALTER TABLE request_engine.reservation_attendance OWNER TO request_engine_schema_owner;

--
-- Name: reservation_commercial_commitment_context_terms; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reservation_commercial_commitment_context_terms (
    organization_id uuid CONSTRAINT reservation_commercial_commitment_cont_organization_id_not_null NOT NULL,
    reservation_id uuid CONSTRAINT reservation_commercial_commitment_conte_reservation_id_not_null NOT NULL,
    booking_context_terms_id uuid CONSTRAINT reservation_commercial_commit_booking_context_terms_id_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() CONSTRAINT reservation_commercial_commitment_context_t_created_at_not_null NOT NULL
);

ALTER TABLE ONLY request_engine.reservation_commercial_commitment_context_terms FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.reservation_commercial_commitment_context_terms OWNER TO request_engine_schema_owner;

--
-- Name: reservation_commercial_commitments; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reservation_commercial_commitments (
    reservation_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_booking_terms_id uuid,
    amount numeric(20,6) NOT NULL,
    currency text NOT NULL,
    planned_duration_minutes integer CONSTRAINT reservation_commercial_commit_planned_duration_minutes_not_null NOT NULL,
    configuration_fingerprint text CONSTRAINT reservation_commercial_commi_configuration_fingerprint_not_null NOT NULL,
    committed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reservation_commercial_commitme_configuration_fingerprint_check CHECK ((configuration_fingerprint <> ''::text)),
    CONSTRAINT reservation_commercial_commitmen_planned_duration_minutes_check CHECK ((planned_duration_minutes > 0)),
    CONSTRAINT reservation_commercial_commitments_amount_check CHECK ((amount >= (0)::numeric)),
    CONSTRAINT reservation_commercial_commitments_currency_check CHECK ((currency ~ '^[A-Z]{3}$'::text))
);

ALTER TABLE ONLY request_engine.reservation_commercial_commitments FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.reservation_commercial_commitments OWNER TO request_engine_schema_owner;

--
-- Name: reservations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reservations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    origin_request_id uuid,
    during tstzrange NOT NULL,
    status text DEFAULT 'confirmed'::text NOT NULL,
    booking_policy_snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    cancelled_at timestamp with time zone,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reservations_booking_policy_snapshot_check CHECK ((jsonb_typeof(booking_policy_snapshot) = 'object'::text)),
    CONSTRAINT reservations_check CHECK (((status = 'cancelled'::text) = (cancelled_at IS NOT NULL))),
    CONSTRAINT reservations_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT reservations_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT reservations_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT reservations_revision_check CHECK ((revision > 0)),
    CONSTRAINT reservations_status_check CHECK ((status = ANY (ARRAY['confirmed'::text, 'cancelled'::text])))
);


ALTER TABLE request_engine.reservations OWNER TO request_engine_schema_owner;

--
-- Name: resource_activities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_activities (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid,
    activity_kind text NOT NULL,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    ended_at timestamp with time zone,
    started_by_principal_id uuid NOT NULL,
    ended_by_principal_id uuid,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resource_activities_activity_kind_check CHECK ((activity_kind = ANY (ARRAY['break'::text, 'emergency'::text, 'administrative'::text, 'other_operational'::text]))),
    CONSTRAINT resource_activities_check CHECK (((ended_at IS NULL) OR (ended_at >= started_at))),
    CONSTRAINT resource_activities_end_actor_ck CHECK (((ended_at IS NULL) = (ended_by_principal_id IS NULL))),
    CONSTRAINT resource_activities_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.resource_activities FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.resource_activities OWNER TO request_engine_schema_owner;

--
-- Name: resource_capabilities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_capabilities (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    capability_key text NOT NULL,
    display_name text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resource_capabilities_capability_key_check CHECK ((capability_key <> ''::text)),
    CONSTRAINT resource_capabilities_display_name_check CHECK ((display_name <> ''::text))
);


ALTER TABLE request_engine.resource_capabilities OWNER TO request_engine_schema_owner;

--
-- Name: resource_capability_assignments; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_capability_assignments (
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    capability_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);


ALTER TABLE request_engine.resource_capability_assignments OWNER TO request_engine_schema_owner;

--
-- Name: resource_location_assignments; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_location_assignments (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    effective_during tstzrange NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resource_location_assignments_effective_during_check CHECK ((NOT isempty(effective_during))),
    CONSTRAINT resource_location_assignments_effective_during_check1 CHECK ((lower(effective_during) IS NOT NULL)),
    CONSTRAINT resource_location_assignments_effective_during_check2 CHECK ((lower_inc(effective_during) AND (NOT upper_inc(effective_during)))),
    CONSTRAINT resource_location_assignments_revision_check CHECK ((revision > 0)),
    CONSTRAINT resource_location_assignments_status_check CHECK ((status = ANY (ARRAY['active'::text, 'retired'::text])))
);

ALTER TABLE ONLY request_engine.resource_location_assignments FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.resource_location_assignments OWNER TO request_engine_schema_owner;

--
-- Name: resource_location_availability; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_location_availability (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid CONSTRAINT resource_location_availabil_resource_location_assignme_not_null NOT NULL,
    weekday smallint NOT NULL,
    local_start time without time zone NOT NULL,
    local_end time without time zone NOT NULL,
    valid_from date,
    valid_until date,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resource_location_availability_check CHECK ((local_start < local_end)),
    CONSTRAINT resource_location_availability_check1 CHECK (((valid_until IS NULL) OR (valid_from IS NULL) OR (valid_until >= valid_from))),
    CONSTRAINT resource_location_availability_weekday_check CHECK (((weekday >= 0) AND (weekday <= 6)))
);

ALTER TABLE ONLY request_engine.resource_location_availability FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.resource_location_availability OWNER TO request_engine_schema_owner;

--
-- Name: resource_location_schedule_exceptions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_location_schedule_exceptions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid CONSTRAINT resource_location_schedule__resource_location_assignme_not_null NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resource_location_schedule_exceptions_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT resource_location_schedule_exceptions_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT resource_location_schedule_exceptions_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT resource_location_schedule_exceptions_exception_kind_check CHECK ((exception_kind = ANY (ARRAY['available'::text, 'unavailable'::text])))
);

ALTER TABLE ONLY request_engine.resource_location_schedule_exceptions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.resource_location_schedule_exceptions OWNER TO request_engine_schema_owner;

--
-- Name: resource_public_profiles; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resource_public_profiles (
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    display_name text NOT NULL,
    role_label text,
    profile_image_ref text,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resource_public_profiles_display_name_check CHECK ((btrim(display_name) <> ''::text)),
    CONSTRAINT resource_public_profiles_profile_image_ref_check CHECK (((profile_image_ref IS NULL) OR (btrim(profile_image_ref) <> ''::text))),
    CONSTRAINT resource_public_profiles_revision_check CHECK ((revision > 0)),
    CONSTRAINT resource_public_profiles_role_label_check CHECK (((role_label IS NULL) OR (btrim(role_label) <> ''::text)))
);

ALTER TABLE ONLY request_engine.resource_public_profiles FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.resource_public_profiles OWNER TO request_engine_schema_owner;

--
-- Name: resources; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.resources (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_key text NOT NULL,
    display_name text NOT NULL,
    capacity_model text NOT NULL,
    capacity_units integer DEFAULT 1 NOT NULL,
    active boolean DEFAULT true NOT NULL,
    availability_revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT resources_availability_revision_check CHECK ((availability_revision > 0)),
    CONSTRAINT resources_capacity_model_check CHECK ((capacity_model = ANY (ARRAY['exclusive'::text, 'units'::text]))),
    CONSTRAINT resources_capacity_units_check CHECK ((capacity_units > 0)),
    CONSTRAINT resources_check CHECK (((capacity_model <> 'exclusive'::text) OR (capacity_units = 1))),
    CONSTRAINT resources_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT resources_resource_key_check CHECK ((resource_key <> ''::text))
);


ALTER TABLE request_engine.resources OWNER TO request_engine_schema_owner;

--
-- Name: schedule_exceptions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.schedule_exceptions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT schedule_exceptions_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT schedule_exceptions_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT schedule_exceptions_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT schedule_exceptions_exception_kind_check CHECK ((exception_kind = ANY (ARRAY['available'::text, 'unavailable'::text])))
);


ALTER TABLE request_engine.schedule_exceptions OWNER TO request_engine_schema_owner;

--
-- Name: service_classification_authority_events; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.service_classification_authority_events (
    id uuid DEFAULT uuidv7() NOT NULL,
    service_classification_id uuid CONSTRAINT service_classification_autho_service_classification_id_not_null NOT NULL,
    action text NOT NULL,
    authority_ref text NOT NULL,
    reason text NOT NULL,
    database_session_user text DEFAULT SESSION_USER CONSTRAINT service_classification_authority_database_session_user_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT service_classification_authority_events_action_check CHECK ((action = ANY (ARRAY['created'::text, 'retired'::text]))),
    CONSTRAINT service_classification_authority_events_authority_ref_check CHECK ((btrim(authority_ref) <> ''::text)),
    CONSTRAINT service_classification_authority_events_reason_check CHECK ((btrim(reason) <> ''::text))
);


ALTER TABLE request_engine.service_classification_authority_events OWNER TO request_engine_schema_owner;

--
-- Name: service_classifications; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.service_classifications (
    id uuid DEFAULT uuidv7() NOT NULL,
    classification_key text NOT NULL,
    canonical_name text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT service_classifications_canonical_name_check CHECK ((btrim(canonical_name) <> ''::text)),
    CONSTRAINT service_classifications_classification_key_check CHECK ((classification_key ~ '^[a-z0-9]+(_[a-z0-9]+)*$'::text)),
    CONSTRAINT service_classifications_revision_check CHECK ((revision > 0)),
    CONSTRAINT service_classifications_status_check CHECK ((status = ANY (ARRAY['active'::text, 'retired'::text])))
);


ALTER TABLE request_engine.service_classifications OWNER TO request_engine_schema_owner;

--
-- Name: service_queue_intake_controls; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.service_queue_intake_controls (
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    accepting boolean DEFAULT true NOT NULL,
    reason text,
    effective_until timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    updated_by_principal_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT service_queue_intake_controls_reason_check CHECK (((reason IS NULL) OR (btrim(reason) <> ''::text))),
    CONSTRAINT service_queue_intake_controls_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.service_queue_intake_controls FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.service_queue_intake_controls OWNER TO request_engine_schema_owner;

--
-- Name: service_queues; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.service_queues (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid,
    offering_id uuid,
    queue_key text NOT NULL,
    display_name text NOT NULL,
    policy_key text DEFAULT 'fifo'::text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT service_queues_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT service_queues_policy_key_check CHECK ((policy_key = 'fifo'::text)),
    CONSTRAINT service_queues_queue_key_check CHECK ((queue_key <> ''::text)),
    CONSTRAINT service_queues_revision_check CHECK ((revision > 0))
);


ALTER TABLE request_engine.service_queues OWNER TO request_engine_schema_owner;

--
-- Name: service_session_interruptions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.service_session_interruptions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    service_session_id uuid NOT NULL,
    kind text NOT NULL,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    ended_at timestamp with time zone,
    started_by_principal_id uuid NOT NULL,
    ended_by_principal_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT service_session_interruptions_check CHECK (((ended_at IS NULL) OR (ended_at >= started_at))),
    CONSTRAINT service_session_interruptions_end_actor_ck CHECK (((ended_at IS NULL) = (ended_by_principal_id IS NULL))),
    CONSTRAINT service_session_interruptions_kind_check CHECK ((kind = ANY (ARRAY['emergency'::text, 'break'::text, 'administrative'::text, 'other_operational'::text])))
);

ALTER TABLE ONLY request_engine.service_session_interruptions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.service_session_interruptions OWNER TO request_engine_schema_owner;

--
-- Name: service_sessions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.service_sessions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    actual_workload_classification_id uuid,
    status text DEFAULT 'active'::text NOT NULL,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT service_sessions_check CHECK (((status = 'completed'::text) = (completed_at IS NOT NULL))),
    CONSTRAINT service_sessions_check1 CHECK (((completed_at IS NULL) OR (completed_at >= started_at))),
    CONSTRAINT service_sessions_revision_check CHECK ((revision > 0)),
    CONSTRAINT service_sessions_status_check CHECK ((status = ANY (ARRAY['active'::text, 'paused'::text, 'completed'::text])))
);

ALTER TABLE ONLY request_engine.service_sessions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.service_sessions OWNER TO request_engine_schema_owner;

--
-- Name: setup_pending_identity; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.setup_pending_identity (
    id uuid NOT NULL,
    setup_session_id uuid NOT NULL,
    login_handle text NOT NULL,
    verifier text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    promoted_at timestamp with time zone,
    CONSTRAINT setup_pending_identity_handle_check CHECK (((length(btrim(login_handle)) >= 1) AND (length(btrim(login_handle)) <= 320))),
    CONSTRAINT setup_pending_identity_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'promoted'::text]))),
    CONSTRAINT setup_pending_identity_terminal_check CHECK ((((status = 'pending'::text) AND (promoted_at IS NULL)) OR ((status = 'promoted'::text) AND (promoted_at IS NOT NULL)))),
    CONSTRAINT setup_pending_identity_verifier_check CHECK (((length(verifier) > 32) AND ((verifier ~~ 'scrypt$%'::text) OR (verifier ~~ '$argon2id$%'::text))))
);


ALTER TABLE request_engine.setup_pending_identity OWNER TO request_engine_schema_owner;

--
-- Name: setup_pending_webauthn_credential; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.setup_pending_webauthn_credential (
    id uuid NOT NULL,
    setup_session_id uuid NOT NULL,
    credential_id bytea NOT NULL,
    public_key bytea NOT NULL,
    sign_count bigint DEFAULT 0 NOT NULL,
    aaguid text NOT NULL,
    backup_eligible boolean DEFAULT false NOT NULL,
    backup_state boolean DEFAULT false NOT NULL,
    user_verified boolean DEFAULT true NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    promoted_at timestamp with time zone,
    user_handle bytea,
    CONSTRAINT setup_pending_webauthn_aaguid_check CHECK ((aaguid ~ '^[0-9a-f]{32}$'::text)),
    CONSTRAINT setup_pending_webauthn_credential_check CHECK (((octet_length(credential_id) >= 16) AND (octet_length(credential_id) <= 1023))),
    CONSTRAINT setup_pending_webauthn_key_check CHECK ((octet_length(public_key) > 0)),
    CONSTRAINT setup_pending_webauthn_sign_check CHECK ((sign_count >= 0)),
    CONSTRAINT setup_pending_webauthn_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'promoted'::text]))),
    CONSTRAINT setup_pending_webauthn_terminal_check CHECK ((((status = 'pending'::text) AND (promoted_at IS NULL)) OR ((status = 'promoted'::text) AND (promoted_at IS NOT NULL)))),
    CONSTRAINT setup_pending_webauthn_user_handle_length_ck CHECK (((user_handle IS NULL) OR ((octet_length(user_handle) >= 16) AND (octet_length(user_handle) <= 64))))
);


ALTER TABLE request_engine.setup_pending_webauthn_credential OWNER TO request_engine_schema_owner;

--
-- Name: setup_sessions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.setup_sessions (
    id uuid NOT NULL,
    instance_id uuid NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    mode text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT setup_sessions_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT setup_sessions_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT setup_sessions_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text)),
    CONSTRAINT setup_sessions_mode_check CHECK ((mode = ANY (ARRAY['interactive'::text, 'protected'::text, 'automated'::text]))),
    CONSTRAINT setup_sessions_revision_check CHECK ((revision > 0)),
    CONSTRAINT setup_sessions_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'expired'::text, 'revoked'::text]))),
    CONSTRAINT setup_sessions_terminal_check CHECK ((((status = 'pending'::text) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'consumed'::text) AND (consumed_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL) AND (consumed_at IS NULL)) OR ((status = 'expired'::text) AND (consumed_at IS NULL) AND (revoked_at IS NULL))))
);


ALTER TABLE request_engine.setup_sessions OWNER TO request_engine_schema_owner;

--
-- Name: shared_capacity_authority_events; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.shared_capacity_authority_events (
    id uuid DEFAULT uuidv7() NOT NULL,
    event_kind text NOT NULL,
    global_identity_id uuid,
    shared_capacity_identity_id uuid,
    binding_id uuid,
    resource_organization_id uuid,
    resource_id uuid,
    authority_ref text NOT NULL,
    reason text NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT shared_capacity_authority_events_authority_ref_check CHECK ((authority_ref <> ''::text)),
    CONSTRAINT shared_capacity_authority_events_details_check CHECK ((jsonb_typeof(details) = 'object'::text)),
    CONSTRAINT shared_capacity_authority_events_event_kind_check CHECK ((event_kind = ANY (ARRAY['global_identity.created'::text, 'shared_capacity.created'::text, 'binding.activated'::text, 'binding.revoked'::text]))),
    CONSTRAINT shared_capacity_authority_events_reason_check CHECK ((reason <> ''::text))
);


ALTER TABLE request_engine.shared_capacity_authority_events OWNER TO request_engine_schema_owner;

--
-- Name: shared_capacity_bindings; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.shared_capacity_bindings (
    id uuid DEFAULT uuidv7() NOT NULL,
    shared_capacity_identity_id uuid NOT NULL,
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    valid_from timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    valid_until timestamp with time zone,
    authorized_by text NOT NULL,
    authorization_reason text NOT NULL,
    revoked_by text,
    revocation_reason text,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT shared_capacity_bindings_authorization_reason_check CHECK ((authorization_reason <> ''::text)),
    CONSTRAINT shared_capacity_bindings_authorized_by_check CHECK ((authorized_by <> ''::text)),
    CONSTRAINT shared_capacity_bindings_check CHECK (((valid_until IS NULL) OR (valid_until >= valid_from))),
    CONSTRAINT shared_capacity_bindings_check1 CHECK ((((status = 'active'::text) AND (valid_until IS NULL) AND (revoked_by IS NULL) AND (revocation_reason IS NULL)) OR ((status = 'revoked'::text) AND (valid_until IS NOT NULL) AND (revoked_by IS NOT NULL) AND (revoked_by <> ''::text) AND (revocation_reason IS NOT NULL) AND (revocation_reason <> ''::text)))),
    CONSTRAINT shared_capacity_bindings_revision_check CHECK ((revision > 0)),
    CONSTRAINT shared_capacity_bindings_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);


ALTER TABLE request_engine.shared_capacity_bindings OWNER TO request_engine_schema_owner;

--
-- Name: shared_capacity_claim_links; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.shared_capacity_claim_links (
    capacity_claim_id uuid NOT NULL,
    shared_capacity_identity_id uuid CONSTRAINT shared_capacity_claim_links_shared_capacity_identity_i_not_null NOT NULL,
    linked_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL
);


ALTER TABLE request_engine.shared_capacity_claim_links OWNER TO request_engine_schema_owner;

--
-- Name: shared_capacity_identities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.shared_capacity_identities (
    id uuid DEFAULT uuidv7() NOT NULL,
    global_identity_id uuid NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_authority_ref text NOT NULL,
    creation_reason text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    retired_at timestamp with time zone,
    CONSTRAINT shared_capacity_identities_check CHECK (((status = 'retired'::text) = (retired_at IS NOT NULL))),
    CONSTRAINT shared_capacity_identities_created_authority_ref_check CHECK ((created_authority_ref <> ''::text)),
    CONSTRAINT shared_capacity_identities_creation_reason_check CHECK ((creation_reason <> ''::text)),
    CONSTRAINT shared_capacity_identities_revision_check CHECK ((revision > 0)),
    CONSTRAINT shared_capacity_identities_status_check CHECK ((status = ANY (ARRAY['active'::text, 'retired'::text])))
);


ALTER TABLE request_engine.shared_capacity_identities OWNER TO request_engine_schema_owner;

--
-- Name: slot_offers; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.slot_offers (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    slot_opportunity_id uuid NOT NULL,
    waitlist_entry_id uuid NOT NULL,
    capacity_hold_id uuid NOT NULL,
    status text DEFAULT 'offered'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT slot_offers_check CHECK ((expires_at > created_at)),
    CONSTRAINT slot_offers_revision_check CHECK ((revision > 0)),
    CONSTRAINT slot_offers_status_check CHECK ((status = ANY (ARRAY['offered'::text, 'accepted'::text, 'declined'::text, 'expired'::text, 'cancelled'::text])))
);


ALTER TABLE request_engine.slot_offers OWNER TO request_engine_schema_owner;

--
-- Name: slot_opportunities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.slot_opportunities (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    location_id uuid,
    source_reservation_id uuid,
    source_event_id uuid NOT NULL,
    during tstzrange NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT slot_opportunities_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT slot_opportunities_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT slot_opportunities_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT slot_opportunities_revision_check CHECK ((revision > 0)),
    CONSTRAINT slot_opportunities_status_check CHECK ((status = ANY (ARRAY['open'::text, 'filled'::text, 'closed'::text, 'expired'::text])))
);


ALTER TABLE request_engine.slot_opportunities OWNER TO request_engine_schema_owner;

--
-- Name: staff_invitation_deliveries; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.staff_invitation_deliveries (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    invitation_id uuid NOT NULL,
    generation integer NOT NULL,
    destination_address text NOT NULL,
    secret_reference text NOT NULL,
    secret_digest text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    attempt_no integer DEFAULT 0 NOT NULL,
    attempted_at timestamp with time zone,
    retry_at timestamp with time zone,
    last_error_class text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT staff_invitation_deliveries_attempt_no_check CHECK ((attempt_no >= 0)),
    CONSTRAINT staff_invitation_deliveries_check CHECK ((expires_at > created_at)),
    CONSTRAINT staff_invitation_deliveries_destination_address_check CHECK (((length(destination_address) BETWEEN 3 AND 320) AND (destination_address = lower(btrim(destination_address))) AND (destination_address ~ '^[a-z0-9._%+-]+@[a-z0-9.-]+$'::text))),
    CONSTRAINT staff_invitation_deliveries_generation_check CHECK ((generation > 0)),
    CONSTRAINT staff_invitation_deliveries_last_error_class_check CHECK ((length(last_error_class) <= 100)),
    CONSTRAINT staff_invitation_deliveries_secret_digest_check CHECK ((secret_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT staff_invitation_deliveries_secret_reference_check CHECK ((length(secret_reference) > 0)),
    CONSTRAINT staff_invitation_deliveries_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'attempting'::text, 'delivered'::text, 'unknown'::text, 'failed'::text, 'cancelled'::text, 'expired'::text])))
);

ALTER TABLE ONLY request_engine.staff_invitation_deliveries FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.staff_invitation_deliveries OWNER TO request_engine_schema_owner;

--
-- Name: staff_invitation_proposals; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.staff_invitation_proposals (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    email text NOT NULL,
    display_name text,
    note text,
    proposed_by_principal_id uuid NOT NULL,
    provenance_reference text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    decided_at timestamp with time zone,
    decided_by_principal_id uuid,
    decision_provenance_reference text,
    invitation_id uuid,
    rejection_reason text,
    CONSTRAINT staff_invitation_proposals_approval_link CHECK (((status = 'approved'::text) = (invitation_id IS NOT NULL))),
    CONSTRAINT staff_invitation_proposals_check CHECK (((decided_at IS NULL) OR (decided_at >= created_at))),
    CONSTRAINT staff_invitation_proposals_decision_fields CHECK (((status = 'pending'::text) = ((decided_at IS NULL) AND (decided_by_principal_id IS NULL) AND (decision_provenance_reference IS NULL)))),
    CONSTRAINT staff_invitation_proposals_decision_provenance_reference_check CHECK (((length(btrim(decision_provenance_reference)) >= 1) AND (length(btrim(decision_provenance_reference)) <= 500))),
    CONSTRAINT staff_invitation_proposals_display_name_check CHECK (((display_name IS NULL) OR ((display_name = btrim(display_name)) AND ((length(display_name) >= 1) AND (length(display_name) <= 200))))),
    CONSTRAINT staff_invitation_proposals_email_check CHECK (((length(email) BETWEEN 3 AND 320) AND (email = lower(btrim(email))) AND (email ~ '^[a-z0-9._%+-]+@[a-z0-9.-]+$'::text))),
    CONSTRAINT staff_invitation_proposals_note_check CHECK (((note IS NULL) OR ((note = btrim(note)) AND ((length(note) >= 1) AND (length(note) <= 1000))))),
    CONSTRAINT staff_invitation_proposals_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT staff_invitation_proposals_rejection_reason CHECK (((status = 'rejected'::text) OR (rejection_reason IS NULL))),
    CONSTRAINT staff_invitation_proposals_rejection_reason_check CHECK (((rejection_reason IS NULL) OR ((rejection_reason = btrim(rejection_reason)) AND ((length(rejection_reason) >= 1) AND (length(rejection_reason) <= 500))))),
    CONSTRAINT staff_invitation_proposals_revision_check CHECK ((revision > 0)),
    CONSTRAINT staff_invitation_proposals_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text])))
);

ALTER TABLE ONLY request_engine.staff_invitation_proposals FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.staff_invitation_proposals OWNER TO request_engine_schema_owner;

--
-- Name: staff_member_profiles; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.staff_member_profiles (
    organization_id uuid NOT NULL,
    membership_id uuid NOT NULL,
    display_name text,
    revision bigint NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_by_principal_id uuid NOT NULL,
    provenance_reference text NOT NULL,
    CONSTRAINT staff_member_profiles_display_name_check CHECK (((display_name IS NULL) OR ((display_name = btrim(display_name)) AND ((length(display_name) >= 1) AND (length(display_name) <= 200)) AND (display_name !~ '[[:cntrl:]]'::text)))),
    CONSTRAINT staff_member_profiles_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT staff_member_profiles_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.staff_member_profiles FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.staff_member_profiles OWNER TO request_engine_schema_owner;

--
-- Name: staff_memberships; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.staff_memberships (
    id uuid NOT NULL,
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    identity_binding_id uuid NOT NULL,
    authority_anchor_party_id uuid NOT NULL,
    status text DEFAULT 'invited'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    established_by_principal_id uuid NOT NULL,
    provenance_kind text NOT NULL,
    provenance_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    activated_at timestamp with time zone,
    suspended_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT staff_memberships_provenance_kind_check CHECK ((provenance_kind = ANY (ARRAY['root_provisioning'::text, 'staff_invitation'::text]))),
    CONSTRAINT staff_memberships_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT staff_memberships_revision_check CHECK ((revision > 0)),
    CONSTRAINT staff_memberships_state_time_check CHECK ((((status = 'invited'::text) AND (activated_at IS NULL) AND (suspended_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'active'::text) AND (activated_at IS NOT NULL) AND (suspended_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'suspended'::text) AND (activated_at IS NOT NULL) AND (suspended_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT staff_memberships_status_check CHECK ((status = ANY (ARRAY['invited'::text, 'active'::text, 'suspended'::text, 'revoked'::text])))
);

ALTER TABLE ONLY request_engine.staff_memberships FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.staff_memberships OWNER TO request_engine_schema_owner;

--
-- Name: temporary_proof_cleanup_results; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.temporary_proof_cleanup_results (
    work_id uuid NOT NULL,
    lease_token uuid NOT NULL,
    attempt integer NOT NULL,
    outcome text NOT NULL,
    admission_id uuid NOT NULL,
    admission_digest text NOT NULL,
    observed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT temporary_proof_cleanup_results_admission_digest_check CHECK ((admission_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT temporary_proof_cleanup_results_admission_id_check CHECK ((admission_id <> '00000000-0000-0000-0000-000000000000'::uuid)),
    CONSTRAINT temporary_proof_cleanup_results_attempt_check CHECK ((attempt > 0)),
    CONSTRAINT temporary_proof_cleanup_results_outcome_check CHECK ((outcome = ANY (ARRAY['destroyed'::text, 'absent'::text, 'unverified'::text, 'denied'::text, 'unresolved'::text, 'retained'::text])))
);

ALTER TABLE ONLY request_engine.temporary_proof_cleanup_results FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.temporary_proof_cleanup_results OWNER TO request_engine_schema_owner;

--
-- Name: temporary_proof_cleanup_work; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.temporary_proof_cleanup_work (
    id uuid DEFAULT uuidv7() NOT NULL,
    backend_id uuid NOT NULL,
    mount text NOT NULL,
    reference text NOT NULL,
    version bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    lease_token uuid,
    lease_until timestamp with time zone,
    attempts integer DEFAULT 0 NOT NULL,
    next_attempt_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    terminal boolean DEFAULT false NOT NULL,
    CONSTRAINT temporary_proof_cleanup_work_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT temporary_proof_cleanup_work_check CHECK (((lease_token IS NULL) = (lease_until IS NULL))),
    CONSTRAINT temporary_proof_cleanup_work_lease_until_check CHECK (((lease_until IS NULL) OR isfinite(lease_until))),
    CONSTRAINT temporary_proof_cleanup_work_next_attempt_at_check CHECK (isfinite(next_attempt_at))
);

ALTER TABLE ONLY request_engine.temporary_proof_cleanup_work FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.temporary_proof_cleanup_work OWNER TO request_engine_schema_owner;

--
-- Name: temporary_proof_retention_receipts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.temporary_proof_retention_receipts (
    backend_id uuid NOT NULL,
    mount text NOT NULL,
    reference text NOT NULL,
    version bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    deletion_at timestamp with time zone NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT temporary_proof_retention_receipts_backend_id_check CHECK ((backend_id <> '00000000-0000-0000-0000-000000000000'::uuid)),
    CONSTRAINT temporary_proof_retention_receipts_check CHECK (((created_at < deletion_at) AND (deletion_at <= expires_at))),
    CONSTRAINT temporary_proof_retention_receipts_check1 CHECK ((isfinite(created_at) AND isfinite(deletion_at) AND isfinite(expires_at))),
    CONSTRAINT temporary_proof_retention_receipts_mount_check CHECK (((length(mount) BETWEEN 1 AND 64) AND (mount ~ '^[A-Za-z0-9_-]+$'::text))),
    CONSTRAINT temporary_proof_retention_receipts_reference_check CHECK ((reference ~ '^request-engine/identity-recovery/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/[1-9][0-9]*$'::text)),
    CONSTRAINT temporary_proof_retention_receipts_reference_check1 CHECK ((length(reference) <= 128)),
    CONSTRAINT temporary_proof_retention_receipts_version_check CHECK ((version > 0))
);

ALTER TABLE ONLY request_engine.temporary_proof_retention_receipts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.temporary_proof_retention_receipts OWNER TO request_engine_schema_owner;

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
    user_handle bytea,
    CONSTRAINT webauthn_challenge_user_handle_length_ck CHECK (((user_handle IS NULL) OR ((octet_length(user_handle) >= 16) AND (octet_length(user_handle) <= 64)))),
    CONSTRAINT webauthn_challenges_digest_check CHECK ((octet_length(challenge_digest) = 32)),
    CONSTRAINT webauthn_challenges_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT webauthn_challenges_purpose_check CHECK ((purpose = ANY (ARRAY['registration'::text, 'authentication'::text, 'step_up'::text, 'authentication_discoverable'::text]))),
    CONSTRAINT webauthn_challenges_scope_check CHECK (((((((native_identity_id IS NOT NULL))::integer + ((session_id IS NOT NULL))::integer) + ((setup_session_id IS NOT NULL))::integer) = 1) OR ((purpose = 'authentication_discoverable'::text) AND (native_identity_id IS NULL) AND (session_id IS NULL) AND (setup_session_id IS NULL)))),
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
    user_handle bytea,
    CONSTRAINT webauthn_credential_user_handle_length_ck CHECK (((user_handle IS NULL) OR ((octet_length(user_handle) >= 16) AND (octet_length(user_handle) <= 64)))),
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
-- Name: change_feed_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.change_feed_v1 WITH (security_invoker='true') AS
 SELECT o.organization_id,
    o.id AS event_id,
    o.event_type,
    o.aggregate_kind,
    o.aggregate_id,
    o.change_xid,
    o.occurred_at,
        CASE o.aggregate_kind
            WHEN 'QueueEntry'::text THEN qe.service_queue_id
            WHEN 'ServiceSession'::text THEN sqe.service_queue_id
            ELSE NULL::uuid
        END AS queue_id,
        CASE o.aggregate_kind
            WHEN 'Reservation'::text THEN r.location_id
            WHEN 'QueueEntry'::text THEN q.location_id
            WHEN 'ServiceSession'::text THEN ss.location_id
            ELSE NULL::uuid
        END AS location_id,
        CASE o.aggregate_kind
            WHEN 'Reservation'::text THEN ((lower(r.during) AT TIME ZONE rl.timezone))::date
            WHEN 'QueueEntry'::text THEN ((o.occurred_at AT TIME ZONE el.timezone))::date
            WHEN 'ServiceSession'::text THEN ((o.occurred_at AT TIME ZONE el.timezone))::date
            ELSE NULL::date
        END AS business_date,
        CASE o.aggregate_kind
            WHEN 'Reservation'::text THEN r.id
            WHEN 'QueueEntry'::text THEN qe.reservation_id
            WHEN 'ServiceSession'::text THEN sqe.reservation_id
            ELSE NULL::uuid
        END AS reservation_id
   FROM (((((((request_engine.outbox_messages o
     LEFT JOIN request_engine.reservations r ON (((o.aggregate_kind = 'Reservation'::text) AND (r.organization_id = o.organization_id) AND (r.id = o.aggregate_id))))
     LEFT JOIN request_engine.locations rl ON (((rl.organization_id = r.organization_id) AND (rl.id = r.location_id))))
     LEFT JOIN request_engine.queue_entries qe ON (((o.aggregate_kind = 'QueueEntry'::text) AND (qe.organization_id = o.organization_id) AND (qe.id = o.aggregate_id))))
     LEFT JOIN request_engine.service_sessions ss ON (((o.aggregate_kind = 'ServiceSession'::text) AND (ss.organization_id = o.organization_id) AND (ss.id = o.aggregate_id))))
     LEFT JOIN request_engine.queue_entries sqe ON (((sqe.organization_id = ss.organization_id) AND (sqe.id = ss.queue_entry_id))))
     LEFT JOIN request_engine.service_queues q ON (((q.organization_id = qe.organization_id) AND (q.id = qe.service_queue_id))))
     LEFT JOIN request_engine.locations el ON (((el.organization_id = o.organization_id) AND (el.id =
        CASE o.aggregate_kind
            WHEN 'QueueEntry'::text THEN q.location_id
            WHEN 'ServiceSession'::text THEN ss.location_id
            ELSE NULL::uuid
        END))))
  WHERE (o.change_xid IS NOT NULL);


ALTER VIEW request_read.change_feed_v1 OWNER TO request_engine_schema_owner;

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
-- Name: reservation_calendar_v1; Type: VIEW; Schema: request_read; Owner: request_engine_schema_owner
--

CREATE VIEW request_read.reservation_calendar_v1 WITH (security_invoker='true') AS
 SELECT r.id AS reservation_id,
    r.organization_id,
    r.offering_version_id,
    o.display_name AS offering_display_name,
    r.subject_party_id,
    p.display_name AS subject_display_name,
    r.location_id,
    r.during,
    r.status,
    r.revision,
    COALESCE(ar.response, 'pending'::text) AS attendance_status,
    COALESCE(ra.status, 'pending'::text) AS attendance_outcome,
    ra.checked_in_at,
    ra.no_show_at,
    sv.queue_entry_id AS served_queue_entry_id,
    sv.completed_at AS served_at,
    va.visit_arrived_at,
    COALESCE(cl.claimed_resources, '[]'::jsonb) AS claimed_resources,
    COALESCE(cl.claimed_resource_ids, ARRAY[]::uuid[]) AS claimed_resource_ids
   FROM ((((((((request_engine.reservations r
     JOIN request_engine.parties p ON (((p.organization_id = r.organization_id) AND (p.id = r.subject_party_id))))
     JOIN request_engine.offering_versions ov ON (((ov.organization_id = r.organization_id) AND (ov.id = r.offering_version_id))))
     JOIN request_engine.offerings o ON (((o.organization_id = ov.organization_id) AND (o.id = ov.offering_id))))
     LEFT JOIN LATERAL ( SELECT a.response
           FROM request_engine.attendance_responses a
          WHERE ((a.organization_id = r.organization_id) AND (a.reservation_id = r.id))
          ORDER BY a.responded_at DESC, a.id DESC
         LIMIT 1) ar ON (true))
     LEFT JOIN request_engine.reservation_attendance ra ON (((ra.organization_id = r.organization_id) AND (ra.reservation_id = r.id))))
     LEFT JOIN LATERAL ( SELECT served.id AS queue_entry_id,
            session.completed_at
           FROM (request_engine.queue_entries served
             JOIN request_engine.service_sessions session ON (((session.organization_id = served.organization_id) AND (session.queue_entry_id = served.id))))
          WHERE ((served.organization_id = r.organization_id) AND (served.reservation_id = r.id) AND (served.status = 'completed'::text) AND (session.status = 'completed'::text))
          ORDER BY session.completed_at DESC, served.id DESC
         LIMIT 1) sv ON (true))
     LEFT JOIN LATERAL ( SELECT min(visit.arrived_at) AS visit_arrived_at
           FROM request_engine.queue_entries visit
          WHERE ((visit.organization_id = r.organization_id) AND (visit.reservation_id = r.id) AND (visit.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text, 'completed'::text])))) va ON (true))
     LEFT JOIN LATERAL ( SELECT jsonb_agg(jsonb_build_object('resource_id', c.resource_id, 'display_name', res.display_name, 'claim_active', (c.status = 'active'::text)) ORDER BY res.display_name, c.resource_id) AS claimed_resources,
            array_agg(c.resource_id ORDER BY c.resource_id) AS claimed_resource_ids
           FROM (request_engine.capacity_claims c
             JOIN request_engine.resources res ON (((res.organization_id = c.organization_id) AND (res.id = c.resource_id))))
          WHERE ((c.organization_id = r.organization_id) AND (c.reservation_id = r.id) AND (c.status <> 'replaced'::text))) cl ON (true));


ALTER VIEW request_read.reservation_calendar_v1 OWNER TO request_engine_schema_owner;

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
    s.reason AS active_skip_reason,
    sv.queue_entry_id AS served_queue_entry_id,
    sv.completed_at AS served_at,
    va.visit_arrived_at
   FROM (((((((((request_engine.reservations r
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
         LIMIT 1) s ON (true))
     LEFT JOIN LATERAL ( SELECT served.id AS queue_entry_id,
            session.completed_at
           FROM (request_engine.queue_entries served
             JOIN request_engine.service_sessions session ON (((session.organization_id = served.organization_id) AND (session.queue_entry_id = served.id))))
          WHERE ((served.organization_id = r.organization_id) AND (served.reservation_id = r.id) AND (served.status = 'completed'::text) AND (session.status = 'completed'::text))
          ORDER BY session.completed_at DESC, served.id DESC
         LIMIT 1) sv ON (true))
     LEFT JOIN LATERAL ( SELECT min(visit.arrived_at) AS visit_arrived_at
           FROM request_engine.queue_entries visit
          WHERE ((visit.organization_id = r.organization_id) AND (visit.reservation_id = r.id) AND (visit.status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text, 'completed'::text])))) va ON (true));


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
-- Data for Name: controller_policy_adoption_facts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: controller_policy_adoption_requests; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
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
-- Data for Name: http_auth_admission_state; Type: TABLE DATA; Schema: request_engine; Owner: postgres
--

INSERT INTO request_engine.http_auth_admission_state VALUES (true, NULL, '{}');


--
-- Data for Name: idempotency_records; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: identity_authorities; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--

INSERT INTO request_engine.identity_authorities (
    kind, issuer_or_environment
) VALUES (
    'native', 'request-engine-native'
);
INSERT INTO request_engine.identity_authorities (
    kind, issuer_or_environment
) VALUES (
    'workload', 'request-engine-workload'
);


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
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v6', 6, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}, {"delegable": true, "capability_key": "controller_policy_upgrade", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.inspect_resource", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.read_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.create_definition", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.publish_definition_version", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.set_definition_active", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_definitions", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_inbox", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.configure", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.submit", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.party_override", "authority_plane": "operational"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v7', 7, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}, {"delegable": true, "capability_key": "controller_policy_upgrade", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.inspect_resource", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.read_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.create_definition", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.publish_definition_version", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.set_definition_active", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_definitions", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_inbox", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.configure", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.submit", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.party_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.read_configuration", "authority_plane": "operational"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v8', 8, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}, {"delegable": true, "capability_key": "controller_policy_upgrade", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.inspect_resource", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.read_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.create_definition", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.publish_definition_version", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.set_definition_active", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_definitions", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_inbox", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.configure", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.submit", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.party_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "staff.propose_invitation", "authority_plane": "operational"}]');
INSERT INTO request_engine.initial_controller_policies VALUES ('tenant-controller-v9', 9, '[{"delegable": true, "capability_key": "agent.policy.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "agent.manage_policy", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.provision", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.manage_authority", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "integration.suspend", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.create", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "delegation.revoke", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "organization.bootstrap", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.manage_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "discovery.manage", "authority_plane": "operational"}, {"delegable": true, "capability_key": "onboarding.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "business.get_info", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.search_offerings", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.get_offering_details", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.register", "authority_plane": "operational"}, {"delegable": true, "capability_key": "parties.lookup", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.find_slots", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.book", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.reschedule", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.subject_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.day_board", "authority_plane": "operational"}, {"delegable": true, "capability_key": "agent.read", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.read_self", "authority_plane": "operational"}, {"delegable": true, "capability_key": "controller_policy_upgrade", "authority_plane": "tenant_control"}, {"delegable": true, "capability_key": "authority.inspect_resource", "authority_plane": "operational"}, {"delegable": true, "capability_key": "booking.read_supply", "authority_plane": "operational"}, {"delegable": true, "capability_key": "catalog.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.create_definition", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.publish_definition_version", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.set_definition_active", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_definitions", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read_inbox", "authority_plane": "operational"}, {"delegable": true, "capability_key": "communications.configure", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.submit", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.cancel", "authority_plane": "operational"}, {"delegable": true, "capability_key": "requests.party_override", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.read_configuration", "authority_plane": "operational"}, {"delegable": true, "capability_key": "staff.propose_invitation", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.configure", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.list", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.staff_read", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.check_in", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.call_next", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.skip", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.mark_no_show", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.operator_select", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.recall_hold", "authority_plane": "operational"}, {"delegable": true, "capability_key": "queue.release_recall_hold", "authority_plane": "operational"}, {"delegable": true, "capability_key": "service_session.start", "authority_plane": "operational"}, {"delegable": true, "capability_key": "service_session.complete", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.confirm_attendance", "authority_plane": "operational"}, {"delegable": true, "capability_key": "appointments.record_arrival_estimate", "authority_plane": "operational"}, {"delegable": true, "capability_key": "organization.manage_profile", "authority_plane": "operational"}]');


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
-- Data for Name: native_identity_provision_receipts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
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
