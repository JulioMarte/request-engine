    CONSTRAINT provider_events_terminal_timestamp_check CHECK ((((status = ANY (ARRAY['processed'::text, 'rejected'::text])) AND (processed_at IS NOT NULL)) OR ((status <> ALL (ARRAY['processed'::text, 'rejected'::text])) AND (processed_at IS NULL))))
);


ALTER TABLE request_engine.provider_events OWNER TO request_engine_schema_owner;

--
-- Name: scheduled_actions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.scheduled_actions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    owner_module text NOT NULL,
    action_type text NOT NULL,
    action_version integer DEFAULT 1 NOT NULL,
    subject_kind text,
    subject_id uuid,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    dedupe_key text NOT NULL,
    execute_at timestamp with time zone NOT NULL,
    next_attempt_at timestamp with time zone NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    claim_token uuid,
    lease_until timestamp with time zone,
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 8 NOT NULL,
    last_error_class text,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    replay_count integer DEFAULT 0 NOT NULL,
    last_replayed_at timestamp with time zone,
    correlation_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT scheduled_actions_action_type_check CHECK ((action_type <> ''::text)),
    CONSTRAINT scheduled_actions_action_version_check CHECK ((action_version > 0)),
    CONSTRAINT scheduled_actions_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT scheduled_actions_check CHECK (((status = 'leased'::text) = ((claim_token IS NOT NULL) AND (lease_until IS NOT NULL)))),
    CONSTRAINT scheduled_actions_check1 CHECK (((status <> 'completed'::text) OR (completed_at IS NOT NULL))),
    CONSTRAINT scheduled_actions_correlation_data_object_ck CHECK ((jsonb_typeof(correlation_data) = 'object'::text)),
    CONSTRAINT scheduled_actions_dedupe_key_check CHECK ((dedupe_key <> ''::text)),
    CONSTRAINT scheduled_actions_max_attempts_check CHECK ((max_attempts > 0)),
    CONSTRAINT scheduled_actions_owner_module_check CHECK ((owner_module <> ''::text)),
    CONSTRAINT scheduled_actions_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT scheduled_actions_replay_count_check CHECK ((replay_count >= 0)),
    CONSTRAINT scheduled_actions_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'leased'::text, 'completed'::text, 'cancelled'::text, 'dead'::text])))
);


ALTER TABLE request_engine.scheduled_actions OWNER TO request_engine_schema_owner;

--
-- Name: worker_dead_letters_v1; Type: VIEW; Schema: request_admin; Owner: request_engine_schema_owner
--

CREATE VIEW request_admin.worker_dead_letters_v1 AS
 SELECT scheduled_actions.organization_id,
    'scheduled_action'::text AS work_kind,
    scheduled_actions.id AS work_id,
    scheduled_actions.attempt_count,
    scheduled_actions.max_attempts,
    scheduled_actions.replay_count,
    scheduled_actions.last_error_class,
    scheduled_actions.updated_at
   FROM request_engine.scheduled_actions
  WHERE (scheduled_actions.status = 'dead'::text)
UNION ALL
 SELECT outbox_messages.organization_id,
    'outbox_message'::text AS work_kind,
    outbox_messages.id AS work_id,
    outbox_messages.attempt_count,
    outbox_messages.max_attempts,
    outbox_messages.replay_count,
    outbox_messages.last_error_class,
    outbox_messages.updated_at
   FROM request_engine.outbox_messages
  WHERE (outbox_messages.status = 'dead'::text)
UNION ALL
 SELECT provider_events.organization_id,
    'provider_event'::text AS work_kind,
    provider_events.id AS work_id,
    provider_events.attempt_count,
    provider_events.max_attempts,
    provider_events.replay_count,
    provider_events.last_error_class,
    provider_events.updated_at
   FROM request_engine.provider_events
  WHERE (provider_events.status = ANY (ARRAY['dead'::text, 'rejected'::text]));


ALTER VIEW request_admin.worker_dead_letters_v1 OWNER TO request_engine_schema_owner;

--
-- Name: attendance_responses; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.attendance_responses (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    response text NOT NULL,
    actor_principal_id uuid,
    source_key text NOT NULL,
    responded_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT attendance_responses_response_check CHECK ((response = ANY (ARRAY['accepted'::text, 'declined'::text]))),
    CONSTRAINT attendance_responses_source_key_check CHECK ((source_key <> ''::text))
);


ALTER TABLE request_engine.attendance_responses OWNER TO request_engine_schema_owner;

--
-- Name: audit_records; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.audit_records (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    actor_principal_id uuid,
    command_name text NOT NULL,
    aggregate_kind text,
    aggregate_id uuid,
    represented_party_id uuid,
    representation_id uuid,
    policy_key text,
    idempotency_record_id uuid,
    correlation_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT audit_records_command_name_check CHECK ((command_name <> ''::text)),
    CONSTRAINT audit_records_correlation_data_check CHECK ((jsonb_typeof(correlation_data) = 'object'::text)),
    CONSTRAINT audit_records_details_check CHECK ((jsonb_typeof(details) = 'object'::text))
);


ALTER TABLE request_engine.audit_records OWNER TO request_engine_schema_owner;

--
-- Name: booking_context_terms; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.booking_context_terms (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_location_assignment_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    effective_during tstzrange NOT NULL,
    amount numeric(20,6),
    currency text,
    planned_duration_minutes integer,
    bookable boolean DEFAULT true NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT booking_context_terms_amount_check CHECK (((amount IS NULL) OR (amount >= (0)::numeric))),
    CONSTRAINT booking_context_terms_check CHECK (((amount IS NULL) = (currency IS NULL))),
    CONSTRAINT booking_context_terms_check1 CHECK (((amount IS NOT NULL) OR (planned_duration_minutes IS NOT NULL) OR (NOT bookable))),
    CONSTRAINT booking_context_terms_currency_check CHECK (((currency IS NULL) OR (currency ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT booking_context_terms_effective_during_check CHECK ((NOT isempty(effective_during))),
    CONSTRAINT booking_context_terms_effective_during_check1 CHECK ((lower(effective_during) IS NOT NULL)),
    CONSTRAINT booking_context_terms_effective_during_check2 CHECK ((lower_inc(effective_during) AND (NOT upper_inc(effective_during)))),
    CONSTRAINT booking_context_terms_planned_duration_minutes_check CHECK (((planned_duration_minutes IS NULL) OR (planned_duration_minutes > 0))),
    CONSTRAINT booking_context_terms_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.booking_context_terms FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.booking_context_terms OWNER TO request_engine_schema_owner;

--
-- Name: capacity_claims; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.capacity_claims (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    requirement_id uuid NOT NULL,
    hold_id uuid,
    reservation_id uuid,
    during tstzrange NOT NULL,
    quantity integer NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    released_at timestamp with time zone,
    replaced_by_claim_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    resource_location_assignment_id uuid,
    CONSTRAINT capacity_claims_check CHECK (((hold_id IS NOT NULL) OR (reservation_id IS NOT NULL))),
    CONSTRAINT capacity_claims_check1 CHECK (((status = 'active'::text) = (released_at IS NULL))),
    CONSTRAINT capacity_claims_check2 CHECK (((status <> 'replaced'::text) OR (replaced_by_claim_id IS NOT NULL))),
    CONSTRAINT capacity_claims_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT capacity_claims_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT capacity_claims_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT capacity_claims_quantity_check CHECK ((quantity > 0)),
    CONSTRAINT capacity_claims_status_check CHECK ((status = ANY (ARRAY['active'::text, 'released'::text, 'replaced'::text])))
);


ALTER TABLE request_engine.capacity_claims OWNER TO request_engine_schema_owner;

--
-- Name: capacity_holds; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.capacity_holds (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    location_id uuid,
    during tstzrange NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT capacity_holds_check CHECK ((expires_at > created_at)),
    CONSTRAINT capacity_holds_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT capacity_holds_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT capacity_holds_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT capacity_holds_revision_check CHECK ((revision > 0)),
    CONSTRAINT capacity_holds_status_check CHECK ((status = ANY (ARRAY['active'::text, 'consumed'::text, 'released'::text, 'expired'::text])))
);


ALTER TABLE request_engine.capacity_holds OWNER TO request_engine_schema_owner;

--
-- Name: communication_deliveries; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.communication_deliveries (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    communication_task_id uuid NOT NULL,
    attempt_no integer NOT NULL,
    channel text NOT NULL,
    provider_key text NOT NULL,
    provider_idempotency_key text NOT NULL,
    provider_message_id text,
    status text NOT NULL,
    result_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT communication_deliveries_attempt_no_check CHECK ((attempt_no > 0)),
    CONSTRAINT communication_deliveries_channel_check CHECK ((channel <> ''::text)),
    CONSTRAINT communication_deliveries_provider_idempotency_key_check CHECK ((provider_idempotency_key <> ''::text)),
    CONSTRAINT communication_deliveries_provider_key_check CHECK ((provider_key <> ''::text)),
    CONSTRAINT communication_deliveries_result_data_check CHECK ((jsonb_typeof(result_data) = 'object'::text)),
    CONSTRAINT communication_deliveries_status_check CHECK ((status = ANY (ARRAY['attempting'::text, 'accepted'::text, 'delivered'::text, 'failed'::text, 'ambiguous'::text])))
);


ALTER TABLE request_engine.communication_deliveries OWNER TO request_engine_schema_owner;

--
-- Name: communication_escalations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.communication_escalations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    parent_task_id uuid NOT NULL,
    child_task_id uuid NOT NULL,
    trigger text NOT NULL,
    from_channel text NOT NULL,
    to_channel text NOT NULL,
    ordinal integer NOT NULL,
    failure_class text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT communication_escalations_ordinal_check CHECK ((ordinal >= 1)),
    CONSTRAINT communication_escalations_trigger_check CHECK ((trigger = ANY (ARRAY['delivery_deadline_missed'::text, 'definitive_failure'::text, 'recipient_unreachable'::text])))
);

ALTER TABLE ONLY request_engine.communication_escalations FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.communication_escalations OWNER TO request_engine_schema_owner;

--
-- Name: communication_tasks; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.communication_tasks (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    recipient_party_id uuid NOT NULL,
    contact_point_id uuid,
    purpose text NOT NULL,
    source_kind text,
    source_id uuid,
    channel_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    template_key text NOT NULL,
    template_version integer NOT NULL,
    render_context jsonb DEFAULT '{}'::jsonb NOT NULL,
    dedupe_key text,
    not_before timestamp with time zone,
    expires_at timestamp with time zone,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    parent_task_id uuid,
    lineage_id uuid,
    escalation_ordinal integer,
    CONSTRAINT communication_tasks_channel_policy_check CHECK ((jsonb_typeof(channel_policy) = 'object'::text)),
    CONSTRAINT communication_tasks_check CHECK (((expires_at IS NULL) OR (not_before IS NULL) OR (expires_at > not_before))),
    CONSTRAINT communication_tasks_escalation_ordinal_check CHECK (((escalation_ordinal IS NULL) OR (escalation_ordinal >= 1))),
    CONSTRAINT communication_tasks_lineage_shape_check CHECK ((((parent_task_id IS NULL) AND (lineage_id IS NULL) AND (escalation_ordinal IS NULL)) OR ((parent_task_id IS NOT NULL) AND (lineage_id IS NOT NULL) AND (escalation_ordinal IS NOT NULL)))),
    CONSTRAINT communication_tasks_purpose_check CHECK ((purpose <> ''::text)),
    CONSTRAINT communication_tasks_render_context_check CHECK ((jsonb_typeof(render_context) = 'object'::text)),
    CONSTRAINT communication_tasks_revision_check CHECK ((revision > 0)),
    CONSTRAINT communication_tasks_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'delivering'::text, 'completed'::text, 'cancelled'::text, 'failed'::text]))),
    CONSTRAINT communication_tasks_template_key_check CHECK ((template_key <> ''::text)),
    CONSTRAINT communication_tasks_template_version_check CHECK ((template_version > 0))
);


ALTER TABLE request_engine.communication_tasks OWNER TO request_engine_schema_owner;

--
-- Name: discovery_booking_handoffs; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.discovery_booking_handoffs (
    id uuid DEFAULT uuidv7() NOT NULL,
    token_hash text NOT NULL,
    organization_id uuid NOT NULL,
    publication_id uuid NOT NULL,
    publication_revision bigint NOT NULL,
    mapping_id uuid NOT NULL,
    mapping_revision bigint NOT NULL,
    offering_version_id uuid NOT NULL,
    location_id uuid NOT NULL,
    selection jsonb NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_reservation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT discovery_booking_handoffs_mapping_revision_check CHECK ((mapping_revision > 0)),
    CONSTRAINT discovery_booking_handoffs_publication_revision_check CHECK ((publication_revision > 0)),
    CONSTRAINT discovery_booking_handoffs_selection_check CHECK ((jsonb_typeof(selection) = 'object'::text)),
    CONSTRAINT discovery_booking_handoffs_token_hash_check CHECK ((token_hash ~ '^[0-9a-f]{64}$'::text))
);

ALTER TABLE ONLY request_engine.discovery_booking_handoffs FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.discovery_booking_handoffs OWNER TO request_engine_schema_owner;

--
-- Name: discovery_publications; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.discovery_publications (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    location_id uuid NOT NULL,
    resource_id uuid,
    effective_during tstzrange NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    provider_visibility text DEFAULT 'hidden'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT discovery_publications_effective_during_check CHECK ((NOT isempty(effective_during))),
    CONSTRAINT discovery_publications_effective_during_check1 CHECK ((lower(effective_during) IS NOT NULL)),
    CONSTRAINT discovery_publications_effective_during_check2 CHECK ((lower_inc(effective_during) AND (NOT upper_inc(effective_during)))),
    CONSTRAINT discovery_publications_provider_visibility_check CHECK ((provider_visibility = ANY (ARRAY['hidden'::text, 'public'::text]))),
    CONSTRAINT discovery_publications_public_provider_scope_ck CHECK (((provider_visibility <> 'public'::text) OR (resource_id IS NOT NULL))),
    CONSTRAINT discovery_publications_revision_check CHECK ((revision > 0)),
    CONSTRAINT discovery_publications_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);

ALTER TABLE ONLY request_engine.discovery_publications FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.discovery_publications OWNER TO request_engine_schema_owner;

--
-- Name: external_correlations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.external_correlations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    request_id uuid,
    correlation_kind text NOT NULL,
    provider_key text NOT NULL,
    external_key text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT external_correlations_correlation_kind_check CHECK ((correlation_kind <> ''::text)),
    CONSTRAINT external_correlations_external_key_check CHECK ((external_key <> ''::text)),
    CONSTRAINT external_correlations_provider_key_check CHECK ((provider_key <> ''::text))
);


ALTER TABLE request_engine.external_correlations OWNER TO request_engine_schema_owner;

--
-- Name: global_identities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.global_identities (
    id uuid DEFAULT uuidv7() NOT NULL,
    identity_kind text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    evidence_ref text,
    created_authority_ref text NOT NULL,
    creation_reason text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    retired_at timestamp with time zone,
    CONSTRAINT global_identities_check CHECK (((status = 'retired'::text) = (retired_at IS NOT NULL))),
    CONSTRAINT global_identities_created_authority_ref_check CHECK ((created_authority_ref <> ''::text)),
    CONSTRAINT global_identities_creation_reason_check CHECK ((creation_reason <> ''::text)),
    CONSTRAINT global_identities_identity_kind_check CHECK ((identity_kind = ANY (ARRAY['person'::text, 'organization'::text]))),
    CONSTRAINT global_identities_status_check CHECK ((status = ANY (ARRAY['active'::text, 'retired'::text])))
);


ALTER TABLE request_engine.global_identities OWNER TO request_engine_schema_owner;

--
-- Name: idempotency_records; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.idempotency_records (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    capability text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL,
    status text DEFAULT 'in_progress'::text NOT NULL,
    result_data jsonb,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT idempotency_records_capability_check CHECK ((capability <> ''::text)),
    CONSTRAINT idempotency_records_check CHECK (((status = 'completed'::text) = (completed_at IS NOT NULL))),
    CONSTRAINT idempotency_records_idempotency_key_check CHECK ((idempotency_key <> ''::text)),
    CONSTRAINT idempotency_records_request_fingerprint_check CHECK ((request_fingerprint <> ''::text)),
    CONSTRAINT idempotency_records_status_check CHECK ((status = ANY (ARRAY['in_progress'::text, 'completed'::text])))
);


ALTER TABLE request_engine.idempotency_records OWNER TO request_engine_schema_owner;

--
-- Name: identity_exchange_candidates; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.identity_exchange_candidates (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    portable_party_id uuid NOT NULL,
    kind text NOT NULL,
    authority text NOT NULL,
    fingerprint text NOT NULL,
    created_by_principal_id uuid NOT NULL,
    expires_at timestamp with time zone DEFAULT (clock_timestamp() + '00:10:00'::interval) NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT identity_exchange_candidate_authority_ck CHECK ((((kind = 'cedula'::text) AND (authority = 'DO:JCE'::text)) OR ((kind = 'passport'::text) AND (authority ~ '^[A-Z]{2}$'::text)) OR ((kind = 'rnc'::text) AND (authority = 'DO:DGII'::text)))),
    CONSTRAINT identity_exchange_candidates_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT identity_exchange_candidates_kind_check CHECK ((kind = ANY (ARRAY['cedula'::text, 'passport'::text, 'rnc'::text])))
);

ALTER TABLE ONLY request_engine.identity_exchange_candidates FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.identity_exchange_candidates OWNER TO request_engine_schema_owner;

--
-- Name: live_capacity_projection_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.live_capacity_projection_policies (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT live_capacity_projection_policies_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.live_capacity_projection_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.live_capacity_projection_policies OWNER TO request_engine_schema_owner;

--
-- Name: live_capacity_workload_estimate_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.live_capacity_workload_estimate_policies (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid CONSTRAINT live_capacity_workload_estimate_polici_organization_id_not_null NOT NULL,
    workload_classification_id uuid CONSTRAINT live_capacity_workload_esti_workload_classification_id_not_null NOT NULL,
    duration_seconds integer CONSTRAINT live_capacity_workload_estimate_polic_duration_seconds_not_null NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT live_capacity_workload_estimate_policies_duration_seconds_check CHECK ((duration_seconds > 0)),
    CONSTRAINT live_capacity_workload_estimate_policies_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.live_capacity_workload_estimate_policies OWNER TO request_engine_schema_owner;

--
-- Name: location_hours_exceptions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.location_hours_exceptions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    during tstzrange NOT NULL,
    exception_kind text NOT NULL,
    reason text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT location_hours_exceptions_during_check CHECK ((NOT isempty(during))),
    CONSTRAINT location_hours_exceptions_during_check1 CHECK (((lower(during) IS NOT NULL) AND (upper(during) IS NOT NULL))),
    CONSTRAINT location_hours_exceptions_during_check2 CHECK ((lower_inc(during) AND (NOT upper_inc(during)))),
    CONSTRAINT location_hours_exceptions_exception_kind_check CHECK ((exception_kind = ANY (ARRAY['available'::text, 'unavailable'::text])))
);

ALTER TABLE ONLY request_engine.location_hours_exceptions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.location_hours_exceptions OWNER TO request_engine_schema_owner;

--
-- Name: location_operational_hours; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.location_operational_hours (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    weekday smallint NOT NULL,
    local_start time without time zone NOT NULL,
    local_end time without time zone NOT NULL,
    valid_from date,
    valid_until date,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT location_operational_hours_check CHECK ((local_start < local_end)),
    CONSTRAINT location_operational_hours_check1 CHECK (((valid_until IS NULL) OR (valid_from IS NULL) OR (valid_until >= valid_from))),
    CONSTRAINT location_operational_hours_weekday_check CHECK (((weekday >= 0) AND (weekday <= 6)))
);

ALTER TABLE ONLY request_engine.location_operational_hours FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.location_operational_hours OWNER TO request_engine_schema_owner;

--
-- Name: location_public_contact_endpoints; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.location_public_contact_endpoints (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    label text,
    active boolean DEFAULT true NOT NULL,
    is_public boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT location_public_contact_endpoints_channel_check CHECK ((channel = ANY (ARRAY['phone'::text, 'whatsapp'::text, 'email'::text]))),
    CONSTRAINT location_public_contact_endpoints_label_check CHECK (((label IS NULL) OR (btrim(label) <> ''::text))),
    CONSTRAINT location_public_contact_endpoints_normalized_value_check CHECK ((normalized_value <> ''::text))
);

ALTER TABLE ONLY request_engine.location_public_contact_endpoints FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.location_public_contact_endpoints OWNER TO request_engine_schema_owner;

--
-- Name: locations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.locations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    location_key text NOT NULL,
    display_name text NOT NULL,
    timezone text NOT NULL,
    public_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    address_line1 text,
    address_line2 text,
    locality text,
    administrative_area text,
    postal_code text,
    country_code text,
    latitude numeric(9,6),
    longitude numeric(9,6),
    geocoding_source text,
    geocoded_at timestamp with time zone,
    operational_revision bigint DEFAULT 1 NOT NULL,
    CONSTRAINT locations_address_line1_ck CHECK (((address_line1 IS NULL) OR (btrim(address_line1) <> ''::text))),
    CONSTRAINT locations_coordinate_pair_ck CHECK (((latitude IS NULL) = (longitude IS NULL))),
    CONSTRAINT locations_country_code_ck CHECK (((country_code IS NULL) OR (country_code ~ '^[A-Z]{2}$'::text))),
    CONSTRAINT locations_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT locations_latitude_ck CHECK (((latitude IS NULL) OR ((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric)))),
    CONSTRAINT locations_location_key_check CHECK ((location_key <> ''::text)),
    CONSTRAINT locations_longitude_ck CHECK (((longitude IS NULL) OR ((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)))),
    CONSTRAINT locations_operational_revision_ck CHECK ((operational_revision > 0)),
    CONSTRAINT locations_public_data_check CHECK ((jsonb_typeof(public_data) = 'object'::text)),
    CONSTRAINT locations_timezone_check CHECK ((timezone <> ''::text))
);


ALTER TABLE request_engine.locations OWNER TO request_engine_schema_owner;

--
-- Name: offering_resource_requirements; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.offering_resource_requirements (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    capability_id uuid NOT NULL,
    ordinal integer NOT NULL,
    quantity integer DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT offering_resource_requirements_ordinal_check CHECK ((ordinal > 0)),
    CONSTRAINT offering_resource_requirements_quantity_check CHECK ((quantity > 0))
);


ALTER TABLE request_engine.offering_resource_requirements OWNER TO request_engine_schema_owner;

--
-- Name: offering_service_classifications; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.offering_service_classifications (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    service_classification_id uuid CONSTRAINT offering_service_classificat_service_classification_id_not_null NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT offering_service_classifications_revision_check CHECK ((revision > 0)),
    CONSTRAINT offering_service_classifications_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text])))
);

ALTER TABLE ONLY request_engine.offering_service_classifications FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.offering_service_classifications OWNER TO request_engine_schema_owner;

--
-- Name: offering_version_booking_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.offering_version_booking_policies (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    revision integer NOT NULL,
    booking_policy jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT offering_version_booking_policies_booking_policy_check CHECK ((jsonb_typeof(booking_policy) = 'object'::text)),
    CONSTRAINT offering_version_booking_policies_revision_check CHECK ((revision >= 1))
);

ALTER TABLE ONLY request_engine.offering_version_booking_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.offering_version_booking_policies OWNER TO request_engine_schema_owner;

--
-- Name: offering_version_booking_terms; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.offering_version_booking_terms (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_version_id uuid NOT NULL,
    amount numeric(20,6) NOT NULL,
    currency text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT offering_version_booking_terms_amount_check CHECK ((amount >= (0)::numeric)),
    CONSTRAINT offering_version_booking_terms_currency_check CHECK ((currency ~ '^[A-Z]{3}$'::text))
);

ALTER TABLE ONLY request_engine.offering_version_booking_terms FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.offering_version_booking_terms OWNER TO request_engine_schema_owner;

--
-- Name: offering_versions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.offering_versions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_id uuid NOT NULL,
    version integer NOT NULL,
    duration_minutes integer,
    bookable boolean DEFAULT false NOT NULL,
    requestable boolean DEFAULT true NOT NULL,
    booking_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    public_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    delivery_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT offering_versions_booking_policy_check CHECK ((jsonb_typeof(booking_policy) = 'object'::text)),
    CONSTRAINT offering_versions_check CHECK (((NOT bookable) OR (duration_minutes IS NOT NULL))),
    CONSTRAINT offering_versions_delivery_policy_object_ck CHECK ((jsonb_typeof(delivery_policy) = 'object'::text)),
    CONSTRAINT offering_versions_duration_minutes_check CHECK (((duration_minutes IS NULL) OR (duration_minutes > 0))),
    CONSTRAINT offering_versions_public_data_check CHECK ((jsonb_typeof(public_data) = 'object'::text)),
    CONSTRAINT offering_versions_version_check CHECK ((version > 0))
);


ALTER TABLE request_engine.offering_versions OWNER TO request_engine_schema_owner;

--
-- Name: offerings; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.offerings (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    offering_key text NOT NULL,
    display_name text NOT NULL,
    description text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT offerings_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT offerings_offering_key_check CHECK ((offering_key <> ''::text))
);


ALTER TABLE request_engine.offerings OWNER TO request_engine_schema_owner;

--
-- Name: operational_recovery_actions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_recovery_actions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    incident_id uuid NOT NULL,
    action_kind text NOT NULL,
    status text DEFAULT 'prepared'::text NOT NULL,
    principal_id uuid NOT NULL,
    idempotency_key text NOT NULL,
    command_fingerprint text NOT NULL,
    expected_source_revision bigint NOT NULL,
    payload jsonb NOT NULL,
    owner_steps jsonb DEFAULT '{}'::jsonb NOT NULL,
    failure_code text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    CONSTRAINT operational_recovery_actions_action_kind_check CHECK ((action_kind = ANY (ARRAY['stop_intake'::text, 'reopen_intake'::text, 'extend_day'::text, 'reschedule'::text, 'replace_resource'::text, 'communicate_impact'::text]))),
    CONSTRAINT operational_recovery_actions_command_fingerprint_check CHECK ((btrim(command_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_actions_expected_source_revision_check CHECK ((expected_source_revision > 0)),
    CONSTRAINT operational_recovery_actions_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT operational_recovery_actions_owner_steps_check CHECK ((jsonb_typeof(owner_steps) = 'object'::text)),
    CONSTRAINT operational_recovery_actions_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT operational_recovery_actions_status_check CHECK ((status = ANY (ARRAY['prepared'::text, 'running'::text, 'succeeded'::text, 'rejected'::text, 'partially_applied'::text])))
);

ALTER TABLE ONLY request_engine.operational_recovery_actions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_recovery_actions OWNER TO request_engine_schema_owner;

--
-- Name: operational_recovery_autonomy_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_recovery_autonomy_policies (
    organization_id uuid NOT NULL,
    service_queue_id uuid CONSTRAINT operational_recovery_autonomy_policie_service_queue_id_not_null NOT NULL,
    enabled boolean NOT NULL,
    max_delay_minutes integer CONSTRAINT operational_recovery_autonomy_polici_max_delay_minutes_not_null NOT NULL,
    max_auto_actions_per_incident integer CONSTRAINT operational_recovery_autono_max_auto_actions_per_incid_not_null NOT NULL,
    granted_by uuid NOT NULL,
    granted_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT operational_recovery_autonom_max_auto_actions_per_inciden_check CHECK ((max_auto_actions_per_incident > 0)),
    CONSTRAINT operational_recovery_autonomy_policies_check CHECK ((granted_at <= updated_at)),
    CONSTRAINT operational_recovery_autonomy_policies_max_delay_minutes_check CHECK ((max_delay_minutes > 0))
);

ALTER TABLE ONLY request_engine.operational_recovery_autonomy_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_recovery_autonomy_policies OWNER TO request_engine_schema_owner;

--
-- Name: operational_recovery_escalations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_recovery_escalations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    incident_id uuid NOT NULL,
    source_revision bigint NOT NULL,
    escalation_level integer NOT NULL,
    operator_escalation_required boolean CONSTRAINT operational_recovery_escala_operator_escalation_requir_not_null NOT NULL,
    escalation_reason text,
    customer_impact_required boolean CONSTRAINT operational_recovery_escalati_customer_impact_required_not_null NOT NULL,
    impact_recipient_party_ids jsonb DEFAULT '[]'::jsonb CONSTRAINT operational_recovery_escala_impact_recipient_party_ids_not_null NOT NULL,
    source_fingerprint text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT operational_recovery_escalatio_impact_recipient_party_ids_check CHECK ((jsonb_typeof(impact_recipient_party_ids) = 'array'::text)),
    CONSTRAINT operational_recovery_escalations_check CHECK ((operator_escalation_required = (escalation_reason IS NOT NULL))),
    CONSTRAINT operational_recovery_escalations_check1 CHECK ((customer_impact_required = (jsonb_array_length(impact_recipient_party_ids) > 0))),
    CONSTRAINT operational_recovery_escalations_escalation_level_check CHECK ((escalation_level >= 0)),
    CONSTRAINT operational_recovery_escalations_escalation_reason_check CHECK (((escalation_reason IS NULL) OR (escalation_reason = ANY (ARRAY['newly_material'::text, 'worsening_severity'::text])))),
    CONSTRAINT operational_recovery_escalations_source_fingerprint_check CHECK ((btrim(source_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_escalations_source_revision_check CHECK ((source_revision > 0))
);

ALTER TABLE ONLY request_engine.operational_recovery_escalations FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_recovery_escalations OWNER TO request_engine_schema_owner;

--
-- Name: operational_recovery_executions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_recovery_executions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    proposal_id uuid NOT NULL,
    reservation_id uuid NOT NULL,
    executed_by_principal_id uuid CONSTRAINT operational_recovery_executio_executed_by_principal_id_not_null NOT NULL,
    idempotency_key text NOT NULL,
    command_fingerprint text NOT NULL,
    source_fingerprint text NOT NULL,
    proposal_fingerprint text NOT NULL,
    original_reservation_revision bigint CONSTRAINT operational_recovery_execut_original_reservation_revis_not_null NOT NULL,
    resulting_reservation_revision bigint,
    target jsonb NOT NULL,
    status text DEFAULT 'prepared'::text NOT NULL,
    failure_code text,
    notification_requested boolean DEFAULT true NOT NULL,
    communication_task_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    completed_at timestamp with time zone,
    CONSTRAINT operational_recovery_executi_original_reservation_revisio_check CHECK ((original_reservation_revision > 0)),
    CONSTRAINT operational_recovery_executions_check CHECK ((((status = 'prepared'::text) AND (resulting_reservation_revision IS NULL) AND (failure_code IS NULL) AND (completed_at IS NULL) AND (communication_task_id IS NULL)) OR ((status = 'succeeded'::text) AND (resulting_reservation_revision IS NOT NULL) AND (resulting_reservation_revision = (original_reservation_revision + 1)) AND (failure_code IS NULL) AND (completed_at IS NOT NULL)) OR ((status = 'rejected'::text) AND (resulting_reservation_revision IS NULL) AND (failure_code IS NOT NULL) AND (btrim(failure_code) <> ''::text) AND (completed_at IS NOT NULL) AND (communication_task_id IS NULL)))),
    CONSTRAINT operational_recovery_executions_check1 CHECK (((completed_at IS NULL) OR (completed_at >= created_at))),
    CONSTRAINT operational_recovery_executions_check2 CHECK (((communication_task_id IS NULL) OR (notification_requested AND (status = 'succeeded'::text)))),
    CONSTRAINT operational_recovery_executions_command_fingerprint_check CHECK ((btrim(command_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_executions_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT operational_recovery_executions_proposal_fingerprint_check CHECK ((btrim(proposal_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_executions_source_fingerprint_check CHECK ((btrim(source_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_executions_status_check CHECK ((status = ANY (ARRAY['prepared'::text, 'succeeded'::text, 'rejected'::text]))),
    CONSTRAINT operational_recovery_executions_target_check CHECK ((jsonb_typeof(target) = 'object'::text))
);

ALTER TABLE ONLY request_engine.operational_recovery_executions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_recovery_executions OWNER TO request_engine_schema_owner;

--
-- Name: operational_recovery_incidents; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_recovery_incidents (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    impact_kind text NOT NULL,
    escalation_level integer DEFAULT 0 NOT NULL,
    source_revision bigint NOT NULL,
    source_fingerprint text NOT NULL,
    current_proposal_id uuid,
    opened_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_assessed_at timestamp with time zone NOT NULL,
    resolved_at timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT operational_recovery_incidents_check CHECK (((status = 'resolved'::text) = (resolved_at IS NOT NULL))),
    CONSTRAINT operational_recovery_incidents_escalation_level_check CHECK ((escalation_level >= 0)),
    CONSTRAINT operational_recovery_incidents_impact_kind_check CHECK ((impact_kind = ANY (ARRAY['delay'::text, 'capacity_shortfall'::text, 'indeterminate'::text]))),
    CONSTRAINT operational_recovery_incidents_revision_check CHECK ((revision > 0)),
    CONSTRAINT operational_recovery_incidents_source_fingerprint_check CHECK ((btrim(source_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_incidents_source_revision_check CHECK ((source_revision > 0)),
    CONSTRAINT operational_recovery_incidents_status_check CHECK ((status = ANY (ARRAY['open'::text, 'mitigating'::text, 'resolved'::text])))
);

ALTER TABLE ONLY request_engine.operational_recovery_incidents FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_recovery_incidents OWNER TO request_engine_schema_owner;

--
-- Name: operational_recovery_proposals; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_recovery_proposals (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    resource_id uuid NOT NULL,
    location_id uuid NOT NULL,
    created_by_principal_id uuid,
    idempotency_key text NOT NULL,
    command_fingerprint text NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    horizon_end timestamp with time zone NOT NULL,
    source_fingerprint text NOT NULL,
    proposal_fingerprint text NOT NULL,
    executable_capacity_seconds integer CONSTRAINT operational_recovery_propos_executable_capacity_second_not_null NOT NULL,
    committed_capacity_seconds integer CONSTRAINT operational_recovery_propos_committed_capacity_seconds_not_null NOT NULL,
    shortfall_seconds integer NOT NULL,
    snapshot jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    creation_kind text DEFAULT 'operator'::text NOT NULL,
    source_revision bigint,
    CONSTRAINT operational_recovery_proposal_actor_ck CHECK ((((creation_kind = 'operator'::text) AND (created_by_principal_id IS NOT NULL) AND (source_revision IS NULL)) OR ((creation_kind = 'automatic'::text) AND (created_by_principal_id IS NULL) AND (source_revision IS NOT NULL)))),
    CONSTRAINT operational_recovery_proposal_creation_kind_ck CHECK ((creation_kind = ANY (ARRAY['operator'::text, 'automatic'::text]))),
    CONSTRAINT operational_recovery_proposal_executable_capacity_seconds_check CHECK ((executable_capacity_seconds >= 0)),
    CONSTRAINT operational_recovery_proposal_source_revision_ck CHECK (((source_revision IS NULL) OR (source_revision > 0))),
    CONSTRAINT operational_recovery_proposals_check CHECK ((horizon_end > observed_at)),
    CONSTRAINT operational_recovery_proposals_command_fingerprint_check CHECK ((btrim(command_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_proposals_committed_capacity_seconds_check CHECK ((committed_capacity_seconds >= 0)),
    CONSTRAINT operational_recovery_proposals_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT operational_recovery_proposals_proposal_fingerprint_check CHECK ((btrim(proposal_fingerprint) <> ''::text)),
    CONSTRAINT operational_recovery_proposals_shortfall_seconds_check CHECK ((shortfall_seconds > 0)),
    CONSTRAINT operational_recovery_proposals_snapshot_check CHECK ((jsonb_typeof(snapshot) = 'object'::text)),
    CONSTRAINT operational_recovery_proposals_source_fingerprint_check CHECK ((btrim(source_fingerprint) <> ''::text))
);

ALTER TABLE ONLY request_engine.operational_recovery_proposals FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_recovery_proposals OWNER TO request_engine_schema_owner;

--
-- Name: operational_workload_classifications; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.operational_workload_classifications (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    workload_key text NOT NULL,
    display_name text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT operational_workload_classifications_display_name_check CHECK ((btrim(display_name) <> ''::text)),
    CONSTRAINT operational_workload_classifications_revision_check CHECK ((revision > 0)),
    CONSTRAINT operational_workload_classifications_workload_key_check CHECK ((btrim(workload_key) <> ''::text)),
    CONSTRAINT operational_workload_display_name_trimmed_ck CHECK ((display_name = btrim(display_name))),
    CONSTRAINT operational_workload_key_trimmed_ck CHECK ((workload_key = btrim(workload_key)))
);

ALTER TABLE ONLY request_engine.operational_workload_classifications FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.operational_workload_classifications OWNER TO request_engine_schema_owner;

--
-- Name: organization_channel_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.organization_channel_policies (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    purpose text NOT NULL,
    enabled boolean NOT NULL,
    channel_policy jsonb NOT NULL,
    revision integer NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT organization_channel_policies_channel_policy_check CHECK ((jsonb_typeof(channel_policy) = 'object'::text)),
    CONSTRAINT organization_channel_policies_purpose_check CHECK ((purpose = ANY (ARRAY['appointment_confirmation'::text, 'appointment_reminder'::text, 'attendance_confirmation_request'::text, 'slot_offer_available'::text, 'operational_recovery_impact'::text, 'operational_recovery_rescheduled'::text]))),
    CONSTRAINT organization_channel_policies_revision_check CHECK ((revision >= 1))
);

ALTER TABLE ONLY request_engine.organization_channel_policies FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.organization_channel_policies OWNER TO request_engine_schema_owner;

--
-- Name: organization_party_bindings; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.organization_party_bindings (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    party_id uuid NOT NULL,
    portable_party_id uuid NOT NULL,
    proof_kind text NOT NULL,
    consented_fields text[] NOT NULL,
    created_by_principal_id uuid NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT organization_party_bindings_consented_fields_check CHECK ((cardinality(consented_fields) > 0)),
    CONSTRAINT organization_party_bindings_proof_kind_check CHECK ((proof_kind = 'operator_document_witness'::text))
);

ALTER TABLE ONLY request_engine.organization_party_bindings FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.organization_party_bindings OWNER TO request_engine_schema_owner;

--
-- Name: organization_public_contact_endpoints; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.organization_public_contact_endpoints (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    label text,
    active boolean DEFAULT true NOT NULL,
    is_public boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT organization_public_contact_endpoints_channel_check CHECK ((channel = ANY (ARRAY['phone'::text, 'whatsapp'::text, 'email'::text]))),
    CONSTRAINT organization_public_contact_endpoints_label_check CHECK (((label IS NULL) OR (btrim(label) <> ''::text))),
    CONSTRAINT organization_public_contact_endpoints_normalized_value_check CHECK ((normalized_value <> ''::text))
);

ALTER TABLE ONLY request_engine.organization_public_contact_endpoints FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.organization_public_contact_endpoints OWNER TO request_engine_schema_owner;

--
-- Name: organizations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.organizations (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_key text NOT NULL,
    display_name text NOT NULL,
    public_profile jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    legal_name text,
    default_timezone text,
    default_locale text,
    default_currency text,
    operational_status text DEFAULT 'active'::text NOT NULL,
    CONSTRAINT organizations_default_currency_ck CHECK (((default_currency IS NULL) OR (default_currency ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT organizations_default_locale_ck CHECK (((default_locale IS NULL) OR (btrim(default_locale) <> ''::text))),
    CONSTRAINT organizations_default_timezone_ck CHECK (((default_timezone IS NULL) OR (btrim(default_timezone) <> ''::text))),
    CONSTRAINT organizations_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT organizations_legal_name_ck CHECK (((legal_name IS NULL) OR (btrim(legal_name) <> ''::text))),
    CONSTRAINT organizations_operational_status_ck CHECK ((operational_status = ANY (ARRAY['active'::text, 'inactive'::text]))),
    CONSTRAINT organizations_organization_key_check CHECK ((organization_key <> ''::text)),
    CONSTRAINT organizations_public_profile_check CHECK ((jsonb_typeof(public_profile) = 'object'::text))
);


ALTER TABLE request_engine.organizations OWNER TO request_engine_schema_owner;

--
-- Name: parties; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.parties (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    party_kind text NOT NULL,
    display_name text NOT NULL,
    external_ref text,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_by_principal_id uuid,
    source_kind text,
    platform text,
    relay_principal_id uuid,
    identity_revision bigint DEFAULT 1 NOT NULL,
    CONSTRAINT parties_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT parties_identity_revision_positive CHECK ((identity_revision >= 1)),
    CONSTRAINT parties_party_kind_check CHECK ((party_kind = ANY (ARRAY['person'::text, 'organization'::text]))),
    CONSTRAINT parties_platform_check CHECK (((platform IS NULL) OR ((length(platform) <= 64) AND (platform <> ''::text)))),
    CONSTRAINT parties_source_kind_check CHECK ((source_kind = ANY (ARRAY['operator'::text, 'subject'::text])))
);


ALTER TABLE request_engine.parties OWNER TO request_engine_schema_owner;

--
-- Name: party_administrative_identifiers; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.party_administrative_identifiers (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    party_id uuid NOT NULL,
    kind text NOT NULL,
    issuer text NOT NULL,
    normalized_issuer text NOT NULL,
    value text NOT NULL,
    normalized_value text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_by_principal_id uuid CONSTRAINT party_administrative_identifie_created_by_principal_id_not_null NOT NULL,
    source_kind text NOT NULL,
    platform text,
    relay_principal_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT party_administrative_identifiers_issuer_check CHECK (((issuer <> ''::text) AND (length(issuer) <= 128))),
    CONSTRAINT party_administrative_identifiers_kind_check CHECK ((kind = 'insurance_member'::text)),
    CONSTRAINT party_administrative_identifiers_normalized_issuer_check CHECK (((normalized_issuer <> ''::text) AND (length(normalized_issuer) <= 128))),
    CONSTRAINT party_administrative_identifiers_normalized_value_check CHECK (((normalized_value <> ''::text) AND (length(normalized_value) <= 256))),
    CONSTRAINT party_administrative_identifiers_platform_check CHECK (((platform IS NULL) OR ((length(platform) <= 64) AND (platform <> ''::text)))),
    CONSTRAINT party_administrative_identifiers_source_kind_check CHECK ((source_kind = ANY (ARRAY['operator'::text, 'subject'::text]))),
    CONSTRAINT party_administrative_identifiers_value_check CHECK (((value <> ''::text) AND (length(value) <= 256)))
);

ALTER TABLE ONLY request_engine.party_administrative_identifiers FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.party_administrative_identifiers OWNER TO request_engine_schema_owner;

--
-- Name: party_contact_points; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.party_contact_points (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    party_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_by_principal_id uuid,
    source_kind text,
    platform text,
    relay_principal_id uuid,
    CONSTRAINT party_contact_points_channel_check CHECK ((channel = ANY (ARRAY['phone'::text, 'email'::text, 'whatsapp'::text]))),
    CONSTRAINT party_contact_points_normalized_value_check CHECK ((normalized_value <> ''::text)),
    CONSTRAINT party_contact_points_platform_check CHECK (((platform IS NULL) OR ((length(platform) <= 64) AND (platform <> ''::text)))),
    CONSTRAINT party_contact_points_source_kind_check CHECK ((source_kind = ANY (ARRAY['operator'::text, 'subject'::text])))
);


ALTER TABLE request_engine.party_contact_points OWNER TO request_engine_schema_owner;

--
-- Name: party_identity_documents; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.party_identity_documents (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    party_id uuid NOT NULL,
    kind text NOT NULL,
    normalized_value text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_by_principal_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    source_kind text,
    platform text,
    relay_principal_id uuid,
    authority text,
    CONSTRAINT party_identity_documents_authority_shape_ck CHECK ((((kind = 'cedula'::text) AND (authority = 'DO:JCE'::text)) OR ((kind = 'passport'::text) AND ((authority IS NULL) OR (authority ~ '^[A-Z]{2}$'::text))) OR ((kind = 'rnc'::text) AND (authority = 'DO:DGII'::text)))),
    CONSTRAINT party_identity_documents_kind_ck CHECK ((kind = ANY (ARRAY['cedula'::text, 'passport'::text, 'rnc'::text]))),
    CONSTRAINT party_identity_documents_normalized_value_check CHECK ((normalized_value <> ''::text)),
    CONSTRAINT party_identity_documents_platform_check CHECK (((platform IS NULL) OR ((length(platform) <= 64) AND (platform <> ''::text)))),
    CONSTRAINT party_identity_documents_source_kind_check CHECK ((source_kind = ANY (ARRAY['operator'::text, 'subject'::text])))
);

ALTER TABLE ONLY request_engine.party_identity_documents FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.party_identity_documents OWNER TO request_engine_schema_owner;

--
-- Name: party_identity_revisions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.party_identity_revisions (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    party_id uuid NOT NULL,
    revision bigint NOT NULL,
    change_kind text NOT NULL,
    display_name text NOT NULL,
    active boolean NOT NULL,
    state jsonb NOT NULL,
    actor_principal_id uuid,
    attributed_operator_principal_id uuid,
    source_kind text,
    platform text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT party_identity_revisions_change_kind_check CHECK ((change_kind = ANY (ARRAY['registered'::text, 'renamed'::text, 'contact_added'::text, 'contact_deactivated'::text, 'document_added'::text, 'verification_flipped'::text, 'party_deactivated'::text, 'rollback'::text]))),
    CONSTRAINT party_identity_revisions_platform_check CHECK (((platform IS NULL) OR ((length(platform) <= 64) AND (platform <> ''::text)))),
    CONSTRAINT party_identity_revisions_revision_check CHECK ((revision >= 1)),
    CONSTRAINT party_identity_revisions_source_kind_check CHECK (((source_kind IS NULL) OR (source_kind = ANY (ARRAY['operator'::text, 'subject'::text])))),
    CONSTRAINT party_identity_revisions_state_check CHECK ((jsonb_typeof(state) = 'object'::text))
);

ALTER TABLE ONLY request_engine.party_identity_revisions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.party_identity_revisions OWNER TO request_engine_schema_owner;

--
-- Name: portable_party_identifiers; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.portable_party_identifiers (
    id uuid DEFAULT uuidv7() NOT NULL,
    portable_party_id uuid NOT NULL,
    party_kind text NOT NULL,
    kind text NOT NULL,
    authority text NOT NULL,
    fingerprint text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT portable_party_identifier_authority_ck CHECK ((((kind = 'cedula'::text) AND (authority = 'DO:JCE'::text)) OR ((kind = 'passport'::text) AND (authority ~ '^[A-Z]{2}$'::text)) OR ((kind = 'rnc'::text) AND (authority = 'DO:DGII'::text)))),
    CONSTRAINT portable_party_identifier_subject_ck CHECK ((((party_kind = 'person'::text) AND (kind = ANY (ARRAY['cedula'::text, 'passport'::text]))) OR ((party_kind = 'organization'::text) AND (kind = 'rnc'::text)))),
    CONSTRAINT portable_party_identifiers_fingerprint_check CHECK ((fingerprint ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT portable_party_identifiers_kind_check CHECK ((kind = ANY (ARRAY['cedula'::text, 'passport'::text, 'rnc'::text])))
);


ALTER TABLE request_engine.portable_party_identifiers OWNER TO request_engine_schema_owner;

--
-- Name: portable_party_identities; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.portable_party_identities (
    id uuid DEFAULT uuidv7() NOT NULL,
    party_kind text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT portable_party_identities_party_kind_check CHECK ((party_kind = ANY (ARRAY['person'::text, 'organization'::text])))
);


ALTER TABLE request_engine.portable_party_identities OWNER TO request_engine_schema_owner;

--
-- Name: portable_party_profiles; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.portable_party_profiles (
    portable_party_id uuid NOT NULL,
    profile jsonb NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    publisher_organization_id uuid NOT NULL,
    CONSTRAINT portable_party_profiles_profile_check CHECK ((jsonb_typeof(profile) = 'object'::text))
);


ALTER TABLE request_engine.portable_party_profiles OWNER TO request_engine_schema_owner;

--
-- Name: principal_contacts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.principal_contacts (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    principal_id uuid NOT NULL,
    channel text NOT NULL,
    normalized_value text NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    active boolean DEFAULT true NOT NULL,
    verification_code_hash text,
    verification_expires_at timestamp with time zone,
    verification_attempts integer DEFAULT 0 NOT NULL,
    created_by_principal_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT principal_contacts_channel_check CHECK ((channel = ANY (ARRAY['whatsapp'::text, 'phone'::text, 'email'::text]))),
    CONSTRAINT principal_contacts_normalized_value_check CHECK ((normalized_value <> ''::text)),
    CONSTRAINT principal_contacts_verification_attempts_check CHECK ((verification_attempts >= 0))
);

ALTER TABLE ONLY request_engine.principal_contacts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.principal_contacts OWNER TO request_engine_schema_owner;

--
-- Name: principals; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.principals (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    principal_kind text NOT NULL,
    external_subject text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT principals_external_subject_check CHECK ((external_subject <> ''::text)),
    CONSTRAINT principals_principal_kind_check CHECK ((principal_kind = ANY (ARRAY['human'::text, 'service'::text, 'agent'::text, 'integration'::text, 'provider'::text, 'worker'::text])))
);


ALTER TABLE request_engine.principals OWNER TO request_engine_schema_owner;

--
-- Name: queue_entries; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.queue_entries (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    reservation_id uuid,
    offering_id uuid,
    status text DEFAULT 'waiting'::text NOT NULL,
    admitted_at timestamp with time zone NOT NULL,
    called_at timestamp with time zone,
    service_started_at timestamp with time zone,
    completed_at timestamp with time zone,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    arrived_at timestamp with time zone NOT NULL,
    expected_workload_classification_id uuid,
    CONSTRAINT queue_entries_arrival_order_ck CHECK ((arrived_at <= admitted_at)),
    CONSTRAINT queue_entries_revision_check CHECK ((revision > 0)),
    CONSTRAINT queue_entries_status_check CHECK ((status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text, 'completed'::text, 'cancelled'::text, 'no_show'::text])))
);


ALTER TABLE request_engine.queue_entries OWNER TO request_engine_schema_owner;

--
-- Name: queue_entry_operator_selections; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.queue_entry_operator_selections (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    reason text NOT NULL,
    selected_by_principal_id uuid CONSTRAINT queue_entry_operator_selectio_selected_by_principal_id_not_null NOT NULL,
    selected_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT queue_entry_operator_selections_reason_check CHECK ((reason = ANY (ARRAY['urgent'::text, 'scheduled_commitment'::text, 'operator_override'::text])))
);

ALTER TABLE ONLY request_engine.queue_entry_operator_selections FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.queue_entry_operator_selections OWNER TO request_engine_schema_owner;

--
-- Name: queue_entry_recall_holds; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.queue_entry_recall_holds (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    condition_kind text NOT NULL,
    until_at timestamp with time zone,
    event_key text,
    reason text,
    created_by_principal_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    released_at timestamp with time zone,
    release_kind text,
    CONSTRAINT queue_entry_recall_holds_check CHECK (((condition_kind = 'until_time'::text) = (until_at IS NOT NULL))),
    CONSTRAINT queue_entry_recall_holds_check1 CHECK (((condition_kind = 'until_event'::text) = (event_key IS NOT NULL))),
    CONSTRAINT queue_entry_recall_holds_check2 CHECK (((released_at IS NULL) = (release_kind IS NULL))),
    CONSTRAINT queue_entry_recall_holds_condition_kind_check CHECK ((condition_kind = ANY (ARRAY['until_time'::text, 'until_event'::text, 'until_customer_initiates'::text]))),
    CONSTRAINT queue_entry_recall_holds_event_key_check CHECK (((event_key IS NULL) OR (event_key = 'external_step_completed'::text))),
    CONSTRAINT queue_entry_recall_holds_reason_check CHECK (((reason IS NULL) OR ((btrim(reason) <> ''::text) AND (length(reason) <= 250)))),
    CONSTRAINT queue_entry_recall_holds_release_kind_ck CHECK (((release_kind IS NULL) OR (release_kind = ANY (ARRAY['expired'::text, 'operator_select'::text, 'condition_satisfied'::text, 'operator_release'::text]))))
);

ALTER TABLE ONLY request_engine.queue_entry_recall_holds FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.queue_entry_recall_holds OWNER TO request_engine_schema_owner;

--
-- Name: queue_entry_skips; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.queue_entry_skips (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    queue_entry_id uuid NOT NULL,
    reason text NOT NULL,
    created_by_principal_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    consumed_at timestamp with time zone,
    consumed_by_entry_id uuid,
    CONSTRAINT queue_entry_skips_check CHECK (((consumed_at IS NULL) = (consumed_by_entry_id IS NULL))),
    CONSTRAINT queue_entry_skips_reason_check CHECK ((reason = ANY (ARRAY['temporarily_unavailable'::text, 'no_response'::text, 'operator_override'::text])))
);

ALTER TABLE ONLY request_engine.queue_entry_skips FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.queue_entry_skips OWNER TO request_engine_schema_owner;

--
-- Name: recovery_source_revisions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.recovery_source_revisions (
    organization_id uuid NOT NULL,
    service_queue_id uuid NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT recovery_source_revisions_revision_check CHECK ((revision > 0))
);

ALTER TABLE ONLY request_engine.recovery_source_revisions FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.recovery_source_revisions OWNER TO request_engine_schema_owner;

--
-- Name: reminder_acknowledgements; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reminder_acknowledgements (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    reminder_plan_id uuid NOT NULL,
    occurrence_at timestamp with time zone NOT NULL,
    subject_party_id uuid NOT NULL,
    source_key text NOT NULL,
    reported_value text,
    acknowledged_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT reminder_acknowledgements_source_key_check CHECK ((source_key <> ''::text))
);


ALTER TABLE request_engine.reminder_acknowledgements OWNER TO request_engine_schema_owner;

--
-- Name: reminder_plans; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.reminder_plans (
    id uuid DEFAULT uuidv7() NOT NULL,
    organization_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    purpose text NOT NULL,
    timezone text NOT NULL,
    schedule_spec jsonb NOT NULL,
    channel_policy jsonb DEFAULT '{}'::jsonb NOT NULL,
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
    CONSTRAINT request_definitions_display_name_check CHECK ((display_name <> ''::text)),
    CONSTRAINT request_definitions_request_key_check CHECK ((request_key <> ''::text))
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
-- Name: TABLE reservation_commercial_commitment_context_terms; Type: COMMENT; Schema: request_engine; Owner: request_engine_schema_owner
--

COMMENT ON TABLE request_engine.reservation_commercial_commitment_context_terms IS 'Append-only provenance linking one committed Reservation commercial fact to every exact contextual term row that contributed to its resolution.';


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


