    CONSTRAINT native_sessions_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text]))),
    CONSTRAINT native_sessions_user_verified_check CHECK (((NOT user_verified) OR ('webauthn'::text = ANY (authentication_methods))))
);


ALTER TABLE request_engine.native_sessions OWNER TO request_engine_schema_owner;

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
-- Name: organization_provisioning_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.organization_provisioning_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid NOT NULL,
    provisioned_by_principal_id uuid CONSTRAINT organization_provisioning_f_provisioned_by_principal_i_not_null NOT NULL,
    provenance_reference text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT organization_provisioning_facts_provenance_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500)))
);

ALTER TABLE ONLY request_engine.organization_provisioning_facts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.organization_provisioning_facts OWNER TO request_engine_schema_owner;

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
-- Name: organization_root_provisioning_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.organization_root_provisioning_facts (
    organization_id uuid NOT NULL,
    organization_party_id uuid CONSTRAINT organization_root_provisioning_f_organization_party_id_not_null NOT NULL,
    controller_principal_id uuid CONSTRAINT organization_root_provisioning_controller_principal_id_not_null NOT NULL,
    controller_binding_id uuid CONSTRAINT organization_root_provisioning_f_controller_binding_id_not_null NOT NULL,
    provisioned_by_principal_id uuid CONSTRAINT organization_root_provision_provisioned_by_principal_i_not_null NOT NULL,
    provenance_reference text CONSTRAINT organization_root_provisioning_fa_provenance_reference_not_null NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    initial_controller_policy_key text DEFAULT NULLIF(current_setting('request_engine.initial_controller_policy'::text, true), ''::text),
    CONSTRAINT organization_root_provisioning_facts_provenance_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500)))
);

ALTER TABLE ONLY request_engine.organization_root_provisioning_facts FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.organization_root_provisioning_facts OWNER TO request_engine_schema_owner;

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
-- Name: platform_authority_lifecycle_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_authority_lifecycle_facts (
    id uuid NOT NULL,
    principal_id uuid NOT NULL,
    action text NOT NULL,
    actor_principal_id uuid NOT NULL,
    actor_authentication_method text CONSTRAINT platform_authority_lifecycl_actor_authentication_metho_not_null NOT NULL,
    reason_code text NOT NULL,
    external_case_reference text,
    revision_before bigint NOT NULL,
    revision_after bigint NOT NULL,
    correlation_id uuid,
    capability_key text NOT NULL,
    idempotency_key_digest text CONSTRAINT platform_authority_lifecycle_fa_idempotency_key_digest_not_null NOT NULL,
    intent_digest text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_authority_lifecycle_facts_action_check CHECK ((action = ANY (ARRAY['suspend'::text, 'reactivate'::text, 'revoke'::text]))),
    CONSTRAINT platform_authority_lifecycle_facts_capability_check CHECK ((length(btrim(capability_key)) > 0)),
    CONSTRAINT platform_authority_lifecycle_facts_case_check CHECK (((external_case_reference IS NULL) OR ((length(btrim(external_case_reference)) >= 1) AND (length(btrim(external_case_reference)) <= 200)))),
    CONSTRAINT platform_authority_lifecycle_facts_intent_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_authority_lifecycle_facts_key_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_authority_lifecycle_facts_method_check CHECK ((length(btrim(actor_authentication_method)) > 0)),
    CONSTRAINT platform_authority_lifecycle_facts_reason_check CHECK (((length(btrim(reason_code)) >= 1) AND (length(btrim(reason_code)) <= 80))),
    CONSTRAINT platform_authority_lifecycle_facts_revision_check CHECK (((revision_before > 0) AND (revision_after >= revision_before)))
);


ALTER TABLE request_engine.platform_authority_lifecycle_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_bootstrap_intents; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_bootstrap_intents (
    id uuid NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    permitted_action text DEFAULT 'platform.root.establish'::text NOT NULL,
    provenance_reference text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT platform_bootstrap_intents_action_check CHECK ((permitted_action = 'platform.root.establish'::text)),
    CONSTRAINT platform_bootstrap_intents_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT platform_bootstrap_intents_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT platform_bootstrap_intents_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text)),
    CONSTRAINT platform_bootstrap_intents_provenance_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT platform_bootstrap_intents_revision_check CHECK ((revision > 0)),
    CONSTRAINT platform_bootstrap_intents_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'consumed'::text, 'revoked'::text]))),
    CONSTRAINT platform_bootstrap_intents_terminal_check CHECK ((((status = 'pending'::text) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'consumed'::text) AND (consumed_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (consumed_at IS NULL) AND (revoked_at IS NOT NULL))))
);


ALTER TABLE request_engine.platform_bootstrap_intents OWNER TO request_engine_schema_owner;

--
-- Name: platform_configuration_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_configuration_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_kind text NOT NULL,
    configuration_revision_id uuid,
    configuration_kind text,
    revision bigint,
    secret_binding_id uuid,
    actor_principal_id uuid,
    actor_authentication_method text,
    correlation_id uuid,
    detail jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    capability_key text,
    idempotency_key_digest text,
    intent_digest text,
    CONSTRAINT platform_configuration_facts_capability_check CHECK (((capability_key IS NULL) OR (capability_key ~ '^[a-z][a-z0-9_.-]{1,127}$'::text))),
    CONSTRAINT platform_configuration_facts_detail_check CHECK ((jsonb_typeof(detail) = 'object'::text)),
    CONSTRAINT platform_configuration_facts_idempotency_check CHECK ((((idempotency_key_digest IS NULL) AND (intent_digest IS NULL)) OR ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text) AND (intent_digest ~ '^[0-9a-f]{64}$'::text)))),
    CONSTRAINT platform_configuration_facts_kind_check CHECK ((event_kind = ANY (ARRAY['staged'::text, 'validated'::text, 'activated'::text, 'superseded'::text, 'disabled'::text, 'secret_bound'::text, 'secret_rotated'::text, 'secret_revoked'::text, 'provider_tested'::text])))
);


ALTER TABLE request_engine.platform_configuration_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_configuration_revisions; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_configuration_revisions (
    id uuid NOT NULL,
    configuration_kind text NOT NULL,
    provider_kind text NOT NULL,
    revision bigint NOT NULL,
    configuration jsonb NOT NULL,
    secret_binding_id uuid,
    state text DEFAULT 'draft'::text NOT NULL,
    created_by_principal_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    validated_at timestamp with time zone,
    activated_at timestamp with time zone,
    disabled_at timestamp with time zone,
    CONSTRAINT platform_configuration_kind_check CHECK ((configuration_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'::text)),
    CONSTRAINT platform_configuration_lifecycle_time_check CHECK ((((state = 'draft'::text) AND (validated_at IS NULL) AND (activated_at IS NULL) AND (disabled_at IS NULL)) OR ((state = 'validated'::text) AND (validated_at IS NOT NULL) AND (activated_at IS NULL) AND (disabled_at IS NULL)) OR ((state = 'active'::text) AND (validated_at IS NOT NULL) AND (activated_at IS NOT NULL) AND (disabled_at IS NULL)) OR ((state = 'superseded'::text) AND (validated_at IS NOT NULL) AND (activated_at IS NOT NULL) AND (disabled_at IS NULL)) OR ((state = 'disabled'::text) AND (disabled_at IS NOT NULL)))),
    CONSTRAINT platform_configuration_object_check CHECK ((jsonb_typeof(configuration) = 'object'::text)),
    CONSTRAINT platform_configuration_provider_check CHECK ((provider_kind ~ '^[a-z][a-z0-9_.-]{1,79}$'::text)),
    CONSTRAINT platform_configuration_revision_check CHECK ((revision > 0)),
    CONSTRAINT platform_configuration_state_check CHECK ((state = ANY (ARRAY['draft'::text, 'validated'::text, 'active'::text, 'superseded'::text, 'disabled'::text])))
);


ALTER TABLE request_engine.platform_configuration_revisions OWNER TO request_engine_schema_owner;

--
-- Name: platform_identity_disable_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_identity_disable_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    actor_principal_id uuid NOT NULL,
    capability_key text NOT NULL,
    native_identity_id uuid NOT NULL,
    native_authority_id uuid NOT NULL,
    revision_before bigint NOT NULL,
    revision_after bigint NOT NULL,
    reason_code text NOT NULL,
    external_case_reference text,
    affected_tenant_count integer NOT NULL,
    affected_platform boolean NOT NULL,
    idempotency_key_digest text NOT NULL,
    intent_digest text NOT NULL,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_identity_disable_facts_capability_check CHECK ((capability_key = 'platform.identity.disable'::text)),
    CONSTRAINT platform_identity_disable_facts_intent_digest_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_identity_disable_facts_key_digest_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_identity_disable_facts_reason_check CHECK (((length(btrim(reason_code)) >= 1) AND (length(btrim(reason_code)) <= 80))),
    CONSTRAINT platform_identity_disable_facts_revision_check CHECK ((revision_after = (revision_before + 1))),
    CONSTRAINT platform_identity_disable_facts_tenant_count_check CHECK ((affected_tenant_count >= 0))
);


ALTER TABLE request_engine.platform_identity_disable_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_identity_recovery_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_identity_recovery_facts (
    id uuid NOT NULL,
    case_id uuid NOT NULL,
    action text NOT NULL,
    actor_principal_id uuid,
    actor_authentication_method text,
    reason_code text,
    external_case_reference text,
    revision_before bigint NOT NULL,
    revision_after bigint NOT NULL,
    correlation_id uuid,
    capability_key text NOT NULL,
    idempotency_key_digest text,
    intent_digest text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_identity_recovery_facts_action_check CHECK ((action = ANY (ARRAY['request'::text, 'approve'::text, 'issue'::text, 'revoke'::text, 'consume'::text, 'deliver'::text, 'delivery_unknown'::text, 'delivery_failed'::text]))),
    CONSTRAINT platform_identity_recovery_facts_capability_check CHECK ((length(btrim(capability_key)) > 0)),
    CONSTRAINT platform_identity_recovery_facts_case_check CHECK (((external_case_reference IS NULL) OR ((length(btrim(external_case_reference)) >= 1) AND (length(btrim(external_case_reference)) <= 400)))),
    CONSTRAINT platform_identity_recovery_facts_intent_check CHECK (((intent_digest IS NULL) OR (intent_digest ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT platform_identity_recovery_facts_key_check CHECK (((idempotency_key_digest IS NULL) OR (idempotency_key_digest ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT platform_identity_recovery_facts_method_check CHECK (((actor_authentication_method IS NULL) OR (length(btrim(actor_authentication_method)) > 0))),
    CONSTRAINT platform_identity_recovery_facts_reason_check CHECK (((reason_code IS NULL) OR ((length(btrim(reason_code)) >= 1) AND (length(btrim(reason_code)) <= 80)))),
    CONSTRAINT platform_identity_recovery_facts_revision_check CHECK (((revision_before >= 1) AND (revision_after >= revision_before)))
);


ALTER TABLE request_engine.platform_identity_recovery_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_installation_claim_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_installation_claim_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    instance_id uuid NOT NULL,
    setup_session_id uuid NOT NULL,
    owner_principal_id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    policy_key text NOT NULL,
    claim_provenance text NOT NULL,
    idempotency_key_digest text CONSTRAINT platform_installation_claim_fac_idempotency_key_digest_not_null NOT NULL,
    intent_digest text NOT NULL,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_installation_claim_intent_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_installation_claim_key_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_installation_claim_provenance_check CHECK (((length(btrim(claim_provenance)) >= 1) AND (length(btrim(claim_provenance)) <= 500)))
);


ALTER TABLE request_engine.platform_installation_claim_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_instance; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_instance (
    singleton_key smallint DEFAULT 1 NOT NULL,
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    state text DEFAULT 'unclaimed'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    built_in_native_authority_id uuid NOT NULL,
    built_in_workload_authority_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    claimed_at timestamp with time zone,
    initial_owner_principal_id uuid,
    claim_provenance text,
    CONSTRAINT platform_instance_claim_shape_check CHECK ((((state = 'unclaimed'::text) AND (claimed_at IS NULL) AND (initial_owner_principal_id IS NULL) AND (claim_provenance IS NULL)) OR ((state = 'claimed'::text) AND (claimed_at IS NOT NULL) AND (initial_owner_principal_id IS NOT NULL) AND (claim_provenance IS NOT NULL) AND (length(btrim(claim_provenance)) > 0)))),
    CONSTRAINT platform_instance_revision_check CHECK ((revision > 0)),
    CONSTRAINT platform_instance_singleton_check CHECK ((singleton_key = 1)),
    CONSTRAINT platform_instance_state_check CHECK ((state = ANY (ARRAY['unclaimed'::text, 'claimed'::text])))
);


ALTER TABLE request_engine.platform_instance OWNER TO request_engine_schema_owner;

--
-- Name: platform_owner_invitation_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_owner_invitation_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    invitation_id uuid NOT NULL,
    action text NOT NULL,
    actor_principal_id uuid,
    native_identity_id uuid,
    revision_before bigint NOT NULL,
    revision_after bigint NOT NULL,
    correlation_id uuid,
    reason_code text,
    idempotency_key_digest text,
    intent_digest text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_owner_invitation_facts_action_check CHECK ((action = ANY (ARRAY['create'::text, 'enroll'::text, 'activate'::text, 'revoke'::text]))),
    CONSTRAINT platform_owner_invitation_facts_check CHECK ((revision_after >= revision_before)),
    CONSTRAINT platform_owner_invitation_facts_idempotency_key_digest_check CHECK (((idempotency_key_digest IS NULL) OR (idempotency_key_digest ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT platform_owner_invitation_facts_intent_digest_check CHECK (((intent_digest IS NULL) OR (intent_digest ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT platform_owner_invitation_facts_revision_before_check CHECK ((revision_before >= 0))
);


ALTER TABLE request_engine.platform_owner_invitation_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_owner_invitations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_owner_invitations (
    id uuid NOT NULL,
    token_digest bytea NOT NULL,
    token_fingerprint text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    invited_by_principal_id uuid NOT NULL,
    native_identity_id uuid,
    provenance_reference text NOT NULL,
    idempotency_key_digest text NOT NULL,
    intent_digest text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    enrolled_at timestamp with time zone,
    consumed_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT platform_owner_invitation_expiry_check CHECK ((expires_at > created_at)),
    CONSTRAINT platform_owner_invitation_state_check CHECK ((((status = 'pending'::text) AND (native_identity_id IS NULL) AND (enrolled_at IS NULL) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'enrolled'::text) AND (native_identity_id IS NOT NULL) AND (enrolled_at IS NOT NULL) AND (consumed_at IS NULL) AND (revoked_at IS NULL)) OR ((status = 'consumed'::text) AND (native_identity_id IS NOT NULL) AND (enrolled_at IS NOT NULL) AND (consumed_at IS NOT NULL) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (consumed_at IS NULL) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT platform_owner_invitations_idempotency_key_digest_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_owner_invitations_intent_digest_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_owner_invitations_provenance_reference_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500))),
    CONSTRAINT platform_owner_invitations_revision_check CHECK ((revision > 0)),
    CONSTRAINT platform_owner_invitations_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'enrolled'::text, 'consumed'::text, 'revoked'::text]))),
    CONSTRAINT platform_owner_invitations_token_digest_check CHECK ((octet_length(token_digest) = 32)),
    CONSTRAINT platform_owner_invitations_token_fingerprint_check CHECK ((token_fingerprint ~ '^[0-9a-f]{16}$'::text))
);


ALTER TABLE request_engine.platform_owner_invitations OWNER TO request_engine_schema_owner;

--
-- Name: platform_owner_policies; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_owner_policies (
    policy_key text NOT NULL,
    revision integer NOT NULL,
    grants jsonb NOT NULL,
    CONSTRAINT platform_owner_policies_grants_check CHECK (((jsonb_typeof(grants) = 'array'::text) AND (jsonb_array_length(grants) > 0))),
    CONSTRAINT platform_owner_policies_revision_check CHECK ((revision > 0))
);


ALTER TABLE request_engine.platform_owner_policies OWNER TO request_engine_schema_owner;

--
-- Name: platform_owner_provisioning_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_owner_provisioning_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    principal_id uuid NOT NULL,
    native_identity_id uuid NOT NULL,
    actor_principal_id uuid NOT NULL,
    policy_key text NOT NULL,
    provenance_reference text NOT NULL,
    idempotency_key_digest text CONSTRAINT platform_owner_provisioning_fac_idempotency_key_digest_not_null NOT NULL,
    intent_digest text NOT NULL,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_owner_provisioning_intent_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_owner_provisioning_key_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_owner_provisioning_policy_check CHECK ((policy_key = 'platform-owner-v2'::text)),
    CONSTRAINT platform_owner_provisioning_provenance_check CHECK (((length(btrim(provenance_reference)) >= 1) AND (length(btrim(provenance_reference)) <= 500)))
);


ALTER TABLE request_engine.platform_owner_provisioning_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_recovery_code_facts; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_recovery_code_facts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_kind text NOT NULL,
    set_id uuid NOT NULL,
    native_identity_id uuid,
    setup_session_id uuid,
    code_id uuid,
    actor_principal_id uuid,
    actor_authentication_method text,
    capability_key text,
    correlation_id uuid,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT platform_recovery_code_facts_kind_check CHECK ((event_kind = ANY (ARRAY['set_created'::text, 'set_revoked'::text, 'set_promoted'::text, 'code_consumed'::text])))
);


ALTER TABLE request_engine.platform_recovery_code_facts OWNER TO request_engine_schema_owner;

--
-- Name: platform_secret_bindings; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_secret_bindings (
    id uuid NOT NULL,
    purpose text NOT NULL,
    backend text NOT NULL,
    secret_id uuid NOT NULL,
    backend_version integer NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    rotated_at timestamp with time zone,
    revoked_at timestamp with time zone,
    CONSTRAINT platform_secret_bindings_backend_check CHECK ((backend = ANY (ARRAY['openbao'::text, 'vault'::text]))),
    CONSTRAINT platform_secret_bindings_purpose_check CHECK ((purpose ~ '^[a-z][a-z0-9_.-]{1,127}$'::text)),
    CONSTRAINT platform_secret_bindings_revision_check CHECK ((revision > 0)),
    CONSTRAINT platform_secret_bindings_revocation_check CHECK ((((status = 'active'::text) AND (revoked_at IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL)))),
    CONSTRAINT platform_secret_bindings_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text]))),
    CONSTRAINT platform_secret_bindings_version_check CHECK ((backend_version > 0))
);


ALTER TABLE request_engine.platform_secret_bindings OWNER TO request_engine_schema_owner;

--
-- Name: platform_secret_mutations; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.platform_secret_mutations (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    operation_kind text NOT NULL,
    capability_key text NOT NULL,
    actor_principal_id uuid NOT NULL,
    actor_authentication_method text NOT NULL,
    correlation_id uuid NOT NULL,
    binding_id uuid,
    secret_id uuid NOT NULL,
    purpose text NOT NULL,
    backend text NOT NULL,
    expected_binding_revision bigint,
    expected_backend_version integer,
    applied_backend_version integer,
    state text DEFAULT 'prepared'::text NOT NULL,
    idempotency_key_digest text NOT NULL,
    intent_digest text NOT NULL,
    result_binding_id uuid,
    result_binding_revision bigint,
    result_binding_status text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    backend_applied_at timestamp with time zone,
    committed_at timestamp with time zone,
    reconcile_required_at timestamp with time zone,
    CONSTRAINT platform_secret_mutations_applied_backend_version_check CHECK (((applied_backend_version IS NULL) OR (applied_backend_version > 0))),
    CONSTRAINT platform_secret_mutations_backend_check CHECK ((backend = ANY (ARRAY['openbao'::text, 'vault'::text]))),
    CONSTRAINT platform_secret_mutations_capability_key_check CHECK ((capability_key = ANY (ARRAY['platform.secret.write'::text, 'platform.secret.rotate'::text, 'platform.secret.revoke'::text]))),
    CONSTRAINT platform_secret_mutations_check CHECK ((((operation_kind = 'create'::text) AND (binding_id IS NULL) AND (expected_binding_revision IS NULL) AND (expected_backend_version IS NULL)) OR ((operation_kind = ANY (ARRAY['rotate'::text, 'revoke'::text])) AND (binding_id IS NOT NULL) AND (expected_binding_revision IS NOT NULL) AND (expected_backend_version IS NOT NULL)))),
    CONSTRAINT platform_secret_mutations_check1 CHECK ((((state = 'prepared'::text) AND (applied_backend_version IS NULL) AND (backend_applied_at IS NULL) AND (committed_at IS NULL) AND (reconcile_required_at IS NULL)) OR ((state = 'backend_applied'::text) AND (applied_backend_version IS NOT NULL) AND (backend_applied_at IS NOT NULL) AND (committed_at IS NULL) AND (reconcile_required_at IS NULL)) OR ((state = 'committed'::text) AND (applied_backend_version IS NOT NULL) AND (backend_applied_at IS NOT NULL) AND (committed_at IS NOT NULL) AND (reconcile_required_at IS NULL) AND (result_binding_id IS NOT NULL) AND (result_binding_revision IS NOT NULL) AND (result_binding_status IS NOT NULL)) OR ((state = 'reconcile_required'::text) AND (applied_backend_version IS NOT NULL) AND (backend_applied_at IS NOT NULL) AND (committed_at IS NULL) AND (reconcile_required_at IS NOT NULL)))),
    CONSTRAINT platform_secret_mutations_expected_backend_version_check CHECK (((expected_backend_version IS NULL) OR (expected_backend_version > 0))),
    CONSTRAINT platform_secret_mutations_expected_binding_revision_check CHECK (((expected_binding_revision IS NULL) OR (expected_binding_revision > 0))),
    CONSTRAINT platform_secret_mutations_idempotency_key_digest_check CHECK ((idempotency_key_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_secret_mutations_intent_digest_check CHECK ((intent_digest ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT platform_secret_mutations_operation_kind_check CHECK ((operation_kind = ANY (ARRAY['create'::text, 'rotate'::text, 'revoke'::text]))),
    CONSTRAINT platform_secret_mutations_purpose_check CHECK ((purpose ~ '^[a-z][a-z0-9_.-]{1,127}$'::text)),
    CONSTRAINT platform_secret_mutations_state_check CHECK ((state = ANY (ARRAY['prepared'::text, 'backend_applied'::text, 'committed'::text, 'reconcile_required'::text])))
);


ALTER TABLE request_engine.platform_secret_mutations OWNER TO request_engine_schema_owner;

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
-- Name: principal_authority_grants; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.principal_authority_grants (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    organization_id uuid,
    principal_id uuid NOT NULL,
    principal_plane text NOT NULL,
    authority_plane text NOT NULL,
    capability_key text NOT NULL,
    delegable boolean DEFAULT false NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    granted_by_principal_id uuid,
    provenance_kind text NOT NULL,
    provenance_reference text NOT NULL,
    granted_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    revoked_at timestamp with time zone,
    revoked_by_principal_id uuid,
    CONSTRAINT principal_authority_grants_authority_plane_check CHECK ((authority_plane = ANY (ARRAY['platform'::text, 'tenant_control'::text, 'operational'::text]))),
    CONSTRAINT principal_authority_grants_capability_key_check CHECK ((length(btrim(capability_key)) > 0)),
    CONSTRAINT principal_authority_grants_principal_plane_check CHECK ((principal_plane = ANY (ARRAY['tenant'::text, 'platform'::text]))),
    CONSTRAINT principal_authority_grants_provenance_check CHECK ((((provenance_kind = 'trust_bootstrap'::text) AND (granted_by_principal_id IS NULL)) OR ((provenance_kind <> 'trust_bootstrap'::text) AND (granted_by_principal_id IS NOT NULL)))),
    CONSTRAINT principal_authority_grants_provenance_reference_check CHECK ((length(btrim(provenance_reference)) > 0)),
    CONSTRAINT principal_authority_grants_revision_check CHECK ((revision > 0)),
    CONSTRAINT principal_authority_grants_revocation_check CHECK ((((status = 'active'::text) AND (revoked_at IS NULL) AND (revoked_by_principal_id IS NULL)) OR ((status = 'revoked'::text) AND (revoked_at IS NOT NULL) AND (revoked_by_principal_id IS NOT NULL) AND (revoked_at >= granted_at)))),
    CONSTRAINT principal_authority_grants_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text]))),
    CONSTRAINT principal_authority_grants_trust_bootstrap_scope_check CHECK (((provenance_kind <> 'trust_bootstrap'::text) OR ((principal_plane = 'platform'::text) AND (authority_plane = 'platform'::text) AND (organization_id IS NULL) AND (granted_by_principal_id IS NULL))))
);

ALTER TABLE ONLY request_engine.principal_authority_grants FORCE ROW LEVEL SECURITY;


ALTER TABLE request_engine.principal_authority_grants OWNER TO request_engine_schema_owner;

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
    organization_id uuid,
    principal_kind text NOT NULL,
    external_subject text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    principal_plane text DEFAULT 'tenant'::text NOT NULL,
    authority_revision bigint DEFAULT 1 NOT NULL,
    CONSTRAINT principals_authority_revision_check CHECK ((authority_revision > 0)),
    CONSTRAINT principals_external_subject_check CHECK ((external_subject <> ''::text)),
    CONSTRAINT principals_plane_organization_check CHECK ((((principal_plane = 'tenant'::text) AND (organization_id IS NOT NULL)) OR ((principal_plane = 'platform'::text) AND (organization_id IS NULL)))),
    CONSTRAINT principals_principal_kind_check CHECK ((principal_kind = ANY (ARRAY['human'::text, 'service'::text, 'agent'::text, 'integration'::text, 'provider'::text, 'worker'::text]))),
    CONSTRAINT principals_principal_plane_check CHECK ((principal_plane = ANY (ARRAY['tenant'::text, 'platform'::text])))
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
-- Name: recovery_code_sets; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.recovery_code_sets (
    id uuid NOT NULL,
    native_identity_id uuid,
    setup_session_id uuid,
    version integer DEFAULT 1 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    revision bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    revoked_at timestamp with time zone,
    CONSTRAINT recovery_code_sets_revision_check CHECK ((revision > 0)),
    CONSTRAINT recovery_code_sets_revocation_check CHECK ((((status = 'revoked'::text) AND (revoked_at IS NOT NULL)) OR ((status = 'active'::text) AND (revoked_at IS NULL)))),
    CONSTRAINT recovery_code_sets_scope_check CHECK (((native_identity_id IS NOT NULL) <> (setup_session_id IS NOT NULL))),
    CONSTRAINT recovery_code_sets_status_check CHECK ((status = ANY (ARRAY['active'::text, 'revoked'::text]))),
    CONSTRAINT recovery_code_sets_version_check CHECK ((version > 0))
);


ALTER TABLE request_engine.recovery_code_sets OWNER TO request_engine_schema_owner;

--
-- Name: recovery_codes; Type: TABLE; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TABLE request_engine.recovery_codes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    set_id uuid NOT NULL,
    code_digest bytea NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    used_at timestamp with time zone,
    CONSTRAINT recovery_codes_digest_check CHECK ((octet_length(code_digest) = 32))
);


ALTER TABLE request_engine.recovery_codes OWNER TO request_engine_schema_owner;

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
    CONSTRAINT setup_pending_webauthn_aaguid_check CHECK ((aaguid ~ '^[0-9a-f]{32}$'::text)),
    CONSTRAINT setup_pending_webauthn_credential_check CHECK (((octet_length(credential_id) >= 16) AND (octet_length(credential_id) <= 1023))),
    CONSTRAINT setup_pending_webauthn_key_check CHECK ((octet_length(public_key) > 0)),
    CONSTRAINT setup_pending_webauthn_sign_check CHECK ((sign_count >= 0)),
    CONSTRAINT setup_pending_webauthn_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'promoted'::text]))),
    CONSTRAINT setup_pending_webauthn_terminal_check CHECK ((((status = 'pending'::text) AND (promoted_at IS NULL)) OR ((status = 'promoted'::text) AND (promoted_at IS NOT NULL))))
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
