ALTER VIEW request_read.service_session_status_v1 OWNER TO request_engine_schema_owner;

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
-- Name: identity_exchange_candidates identity_exchange_candidates_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_exchange_candidates
    ADD CONSTRAINT identity_exchange_candidates_pkey PRIMARY KEY (id);


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
-- Name: reservation_access reservation_access_organization_id_materialization_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_access
    ADD CONSTRAINT reservation_access_organization_id_materialization_key_key UNIQUE (organization_id, materialization_key);


--
-- Name: reservation_access reservation_access_organization_id_reservation_id_reservati_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_access
    ADD CONSTRAINT reservation_access_organization_id_reservation_id_reservati_key UNIQUE (organization_id, reservation_id, reservation_revision, access_key);


--
-- Name: reservation_access reservation_access_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_access
    ADD CONSTRAINT reservation_access_pkey PRIMARY KEY (id);


--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_arrival_estimates
    ADD CONSTRAINT reservation_arrival_estimates_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_arrival_estimates
    ADD CONSTRAINT reservation_arrival_estimates_pkey PRIMARY KEY (id);


--
-- Name: reservation_attendance reservation_attendance_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_attendance
    ADD CONSTRAINT reservation_attendance_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: reservation_attendance reservation_attendance_organization_id_reservation_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_attendance
    ADD CONSTRAINT reservation_attendance_organization_id_reservation_id_key UNIQUE (organization_id, reservation_id);


--
-- Name: reservation_attendance reservation_attendance_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_attendance
    ADD CONSTRAINT reservation_attendance_pkey PRIMARY KEY (id);


--
-- Name: reservation_commercial_commitments reservation_commercial_commit_organization_id_reservation_i_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitments
    ADD CONSTRAINT reservation_commercial_commit_organization_id_reservation_i_key UNIQUE (organization_id, reservation_id);


--
-- Name: reservation_commercial_commitment_context_terms reservation_commercial_commitment_context_terms_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitment_context_terms
    ADD CONSTRAINT reservation_commercial_commitment_context_terms_pkey PRIMARY KEY (organization_id, reservation_id, booking_context_terms_id);


--
-- Name: reservation_commercial_commitments reservation_commercial_commitments_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitments
    ADD CONSTRAINT reservation_commercial_commitments_pkey PRIMARY KEY (reservation_id);


--
-- Name: reservations reservations_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservations
    ADD CONSTRAINT reservations_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: reservations reservations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservations
    ADD CONSTRAINT reservations_pkey PRIMARY KEY (id);


--
-- Name: resource_activities resource_activities_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_activities
    ADD CONSTRAINT resource_activities_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: resource_activities resource_activities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_activities
    ADD CONSTRAINT resource_activities_pkey PRIMARY KEY (id);


--
-- Name: resource_capabilities resource_capabilities_organization_id_capability_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capabilities
    ADD CONSTRAINT resource_capabilities_organization_id_capability_key_key UNIQUE (organization_id, capability_key);


--
-- Name: resource_capabilities resource_capabilities_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capabilities
    ADD CONSTRAINT resource_capabilities_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: resource_capabilities resource_capabilities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capabilities
    ADD CONSTRAINT resource_capabilities_pkey PRIMARY KEY (id);


--
-- Name: resource_capability_assignments resource_capability_assignments_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capability_assignments
    ADD CONSTRAINT resource_capability_assignments_pkey PRIMARY KEY (organization_id, resource_id, capability_id);


--
-- Name: resource_location_assignments resource_location_assignments_no_overlap; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_assignments
    ADD CONSTRAINT resource_location_assignments_no_overlap EXCLUDE USING gist (organization_id WITH =, resource_id WITH =, location_id WITH =, effective_during WITH &&);


--
-- Name: resource_location_assignments resource_location_assignments_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_assignments
    ADD CONSTRAINT resource_location_assignments_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: resource_location_assignments resource_location_assignments_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_assignments
    ADD CONSTRAINT resource_location_assignments_pkey PRIMARY KEY (id);


--
-- Name: resource_location_availability resource_location_availability_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_availability
    ADD CONSTRAINT resource_location_availability_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: resource_location_availability resource_location_availability_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_availability
    ADD CONSTRAINT resource_location_availability_pkey PRIMARY KEY (id);


--
-- Name: resource_location_schedule_exceptions resource_location_exceptions_no_active_overlap; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_schedule_exceptions
    ADD CONSTRAINT resource_location_exceptions_no_active_overlap EXCLUDE USING gist (organization_id WITH =, resource_location_assignment_id WITH =, during WITH &&) WHERE (active);


--
-- Name: resource_location_schedule_exceptions resource_location_schedule_exceptions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_schedule_exceptions
    ADD CONSTRAINT resource_location_schedule_exceptions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: resource_location_schedule_exceptions resource_location_schedule_exceptions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_schedule_exceptions
    ADD CONSTRAINT resource_location_schedule_exceptions_pkey PRIMARY KEY (id);


--
-- Name: resource_public_profiles resource_public_profiles_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_public_profiles
    ADD CONSTRAINT resource_public_profiles_pkey PRIMARY KEY (organization_id, resource_id);


--
-- Name: resources resources_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resources
    ADD CONSTRAINT resources_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: resources resources_organization_id_resource_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resources
    ADD CONSTRAINT resources_organization_id_resource_key_key UNIQUE (organization_id, resource_key);


--
-- Name: resources resources_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resources
    ADD CONSTRAINT resources_pkey PRIMARY KEY (id);


--
-- Name: schedule_exceptions schedule_exceptions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.schedule_exceptions
    ADD CONSTRAINT schedule_exceptions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: schedule_exceptions schedule_exceptions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.schedule_exceptions
    ADD CONSTRAINT schedule_exceptions_pkey PRIMARY KEY (id);


--
-- Name: scheduled_actions scheduled_actions_organization_id_dedupe_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.scheduled_actions
    ADD CONSTRAINT scheduled_actions_organization_id_dedupe_key_key UNIQUE (organization_id, dedupe_key);


--
-- Name: scheduled_actions scheduled_actions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.scheduled_actions
    ADD CONSTRAINT scheduled_actions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: scheduled_actions scheduled_actions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.scheduled_actions
    ADD CONSTRAINT scheduled_actions_pkey PRIMARY KEY (id);


--
-- Name: service_classification_authority_events service_classification_authority_events_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_classification_authority_events
    ADD CONSTRAINT service_classification_authority_events_pkey PRIMARY KEY (id);


--
-- Name: service_classifications service_classifications_classification_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_classifications
    ADD CONSTRAINT service_classifications_classification_key_key UNIQUE (classification_key);


--
-- Name: service_classifications service_classifications_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_classifications
    ADD CONSTRAINT service_classifications_pkey PRIMARY KEY (id);


--
-- Name: service_queue_intake_controls service_queue_intake_controls_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queue_intake_controls
    ADD CONSTRAINT service_queue_intake_controls_pkey PRIMARY KEY (organization_id, service_queue_id);


--
-- Name: service_queues service_queues_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queues
    ADD CONSTRAINT service_queues_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: service_queues service_queues_organization_id_queue_key_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queues
    ADD CONSTRAINT service_queues_organization_id_queue_key_key UNIQUE (organization_id, queue_key);


--
-- Name: service_queues service_queues_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queues
    ADD CONSTRAINT service_queues_pkey PRIMARY KEY (id);


--
-- Name: service_session_interruptions service_session_interruptions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_session_interruptions
    ADD CONSTRAINT service_session_interruptions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: service_session_interruptions service_session_interruptions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_session_interruptions
    ADD CONSTRAINT service_session_interruptions_pkey PRIMARY KEY (id);


--
-- Name: service_sessions service_sessions_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: service_sessions service_sessions_organization_id_queue_entry_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_organization_id_queue_entry_id_key UNIQUE (organization_id, queue_entry_id);


--
-- Name: service_sessions service_sessions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_pkey PRIMARY KEY (id);


--
-- Name: shared_capacity_authority_events shared_capacity_authority_events_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_authority_events
    ADD CONSTRAINT shared_capacity_authority_events_pkey PRIMARY KEY (id);


--
-- Name: shared_capacity_bindings shared_capacity_bindings_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_bindings
    ADD CONSTRAINT shared_capacity_bindings_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: shared_capacity_bindings shared_capacity_bindings_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_bindings
    ADD CONSTRAINT shared_capacity_bindings_pkey PRIMARY KEY (id);


--
-- Name: shared_capacity_claim_links shared_capacity_claim_links_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_claim_links
    ADD CONSTRAINT shared_capacity_claim_links_pkey PRIMARY KEY (capacity_claim_id);


--
-- Name: shared_capacity_identities shared_capacity_identities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_identities
    ADD CONSTRAINT shared_capacity_identities_pkey PRIMARY KEY (id);


--
-- Name: slot_offers slot_offers_organization_id_capacity_hold_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_offers
    ADD CONSTRAINT slot_offers_organization_id_capacity_hold_id_key UNIQUE (organization_id, capacity_hold_id);


--
-- Name: slot_offers slot_offers_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_offers
    ADD CONSTRAINT slot_offers_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: slot_offers slot_offers_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_offers
    ADD CONSTRAINT slot_offers_pkey PRIMARY KEY (id);


--
-- Name: slot_opportunities slot_opportunities_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: slot_opportunities slot_opportunities_organization_id_source_event_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_organization_id_source_event_id_key UNIQUE (organization_id, source_event_id);


--
-- Name: slot_opportunities slot_opportunities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_pkey PRIMARY KEY (id);


--
-- Name: waitlist_entries waitlist_entries_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.waitlist_entries
    ADD CONSTRAINT waitlist_entries_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: waitlist_entries waitlist_entries_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.waitlist_entries
    ADD CONSTRAINT waitlist_entries_pkey PRIMARY KEY (id);


--
-- Name: attendance_responses_current_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX attendance_responses_current_idx ON request_engine.attendance_responses USING btree (organization_id, reservation_id, responded_at DESC, id DESC);


--
-- Name: booking_context_terms_offering_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX booking_context_terms_offering_idx ON request_engine.booking_context_terms USING btree (organization_id, offering_version_id, active);


--
-- Name: capacity_claims_active_hold_requirement_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX capacity_claims_active_hold_requirement_uq ON request_engine.capacity_claims USING btree (organization_id, hold_id, requirement_id) WHERE ((status = 'active'::text) AND (reservation_id IS NULL) AND (hold_id IS NOT NULL));


--
-- Name: capacity_claims_active_id_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_active_id_idx ON request_engine.capacity_claims USING btree (id) WHERE (status = 'active'::text);


--
-- Name: capacity_claims_active_reservation_requirement_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX capacity_claims_active_reservation_requirement_uq ON request_engine.capacity_claims USING btree (organization_id, reservation_id, requirement_id) WHERE ((status = 'active'::text) AND (reservation_id IS NOT NULL));


--
-- Name: capacity_claims_active_resource_during_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_active_resource_during_idx ON request_engine.capacity_claims USING gist (resource_id, during) WHERE (status = 'active'::text);


--
-- Name: capacity_claims_resource_during_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_resource_during_idx ON request_engine.capacity_claims USING gist (resource_id, during);


--
-- Name: capacity_claims_resource_location_assignment_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_resource_location_assignment_idx ON request_engine.capacity_claims USING btree (organization_id, resource_location_assignment_id) WHERE (resource_location_assignment_id IS NOT NULL);


--
-- Name: communication_deliveries_provider_message_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX communication_deliveries_provider_message_uq ON request_engine.communication_deliveries USING btree (organization_id, provider_key, provider_message_id) WHERE (provider_message_id IS NOT NULL);


--
-- Name: communication_tasks_dedupe_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX communication_tasks_dedupe_uq ON request_engine.communication_tasks USING btree (organization_id, dedupe_key) WHERE (dedupe_key IS NOT NULL);


--
-- Name: communication_tasks_live_lineage_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX communication_tasks_live_lineage_uq ON request_engine.communication_tasks USING btree (organization_id, lineage_id) WHERE ((lineage_id IS NOT NULL) AND (status = ANY (ARRAY['pending'::text, 'delivering'::text])));


--
-- Name: discovery_booking_handoffs_expiry_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX discovery_booking_handoffs_expiry_idx ON request_engine.discovery_booking_handoffs USING btree (expires_at) WHERE (consumed_reservation_id IS NULL);


--
-- Name: discovery_publications_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX discovery_publications_lookup_idx ON request_engine.discovery_publications USING btree (organization_id, offering_id, location_id, status);


--
-- Name: identity_exchange_candidate_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX identity_exchange_candidate_lookup_idx ON request_engine.identity_exchange_candidates USING btree (organization_id, id, expires_at);


--
-- Name: location_operational_hours_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX location_operational_hours_lookup_idx ON request_engine.location_operational_hours USING btree (organization_id, location_id, weekday, active);


--
-- Name: offering_service_classifications_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX offering_service_classifications_lookup_idx ON request_engine.offering_service_classifications USING btree (service_classification_id, status, organization_id, offering_id);


--
-- Name: offering_service_classifications_one_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX offering_service_classifications_one_active_idx ON request_engine.offering_service_classifications USING btree (organization_id, offering_id) WHERE (status = 'active'::text);


--
-- Name: offering_version_booking_policies_effective_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX offering_version_booking_policies_effective_idx ON request_engine.offering_version_booking_policies USING btree (organization_id, offering_version_id, revision DESC);


--
-- Name: operational_recovery_actions_incident_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX operational_recovery_actions_incident_idx ON request_engine.operational_recovery_actions USING btree (organization_id, incident_id, created_at, id);


--
-- Name: operational_recovery_auto_proposal_revision_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX operational_recovery_auto_proposal_revision_uq ON request_engine.operational_recovery_proposals USING btree (organization_id, service_queue_id, source_revision) WHERE (creation_kind = 'automatic'::text);


--
-- Name: operational_recovery_escalations_incident_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX operational_recovery_escalations_incident_idx ON request_engine.operational_recovery_escalations USING btree (organization_id, incident_id, source_revision DESC);


--
-- Name: operational_recovery_incidents_scope_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX operational_recovery_incidents_scope_idx ON request_engine.operational_recovery_incidents USING btree (organization_id, service_queue_id, last_assessed_at DESC);


--
-- Name: operational_recovery_one_unresolved_scope_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX operational_recovery_one_unresolved_scope_uq ON request_engine.operational_recovery_incidents USING btree (organization_id, service_queue_id) WHERE (status <> 'resolved'::text);


--
-- Name: operational_recovery_proposals_queue_created_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX operational_recovery_proposals_queue_created_idx ON request_engine.operational_recovery_proposals USING btree (organization_id, service_queue_id, created_at DESC);


--
-- Name: organization_party_binding_identity_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX organization_party_binding_identity_uq ON request_engine.organization_party_bindings USING btree (organization_id, portable_party_id) WHERE active;


--
-- Name: organization_party_binding_party_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX organization_party_binding_party_uq ON request_engine.organization_party_bindings USING btree (organization_id, party_id) WHERE active;


--
-- Name: outbox_messages_due_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX outbox_messages_due_idx ON request_engine.outbox_messages USING btree (next_attempt_at, id) WHERE (status = 'pending'::text);


--
-- Name: outbox_messages_reclaim_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX outbox_messages_reclaim_idx ON request_engine.outbox_messages USING btree (lease_until, id) WHERE (status = 'leased'::text);


--
-- Name: party_admin_ids_active_value_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX party_admin_ids_active_value_uq ON request_engine.party_administrative_identifiers USING btree (organization_id, kind, normalized_issuer, normalized_value) WHERE active;


--
-- Name: party_admin_ids_one_active_per_issuer_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX party_admin_ids_one_active_per_issuer_uq ON request_engine.party_administrative_identifiers USING btree (organization_id, party_id, kind, normalized_issuer) WHERE active;


--
-- Name: party_contact_points_value_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX party_contact_points_value_lookup_idx ON request_engine.party_contact_points USING btree (organization_id, normalized_value, channel) WHERE active;


--
-- Name: party_contact_points_verified_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX party_contact_points_verified_lookup_idx ON request_engine.party_contact_points USING btree (organization_id, party_id, created_at, id) WHERE (active AND verified);


--
-- Name: party_identity_documents_active_value_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX party_identity_documents_active_value_uq ON request_engine.party_identity_documents USING btree (organization_id, kind, COALESCE(authority, ''::text), normalized_value) WHERE active;


--
-- Name: party_identity_documents_one_active_per_kind_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX party_identity_documents_one_active_per_kind_uq ON request_engine.party_identity_documents USING btree (organization_id, party_id, kind, COALESCE(authority, ''::text)) WHERE active;


--
-- Name: portable_party_identifier_active_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX portable_party_identifier_active_uq ON request_engine.portable_party_identifiers USING btree (party_kind, kind, authority, fingerprint) WHERE active;


--
-- Name: portable_party_identifier_party_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX portable_party_identifier_party_idx ON request_engine.portable_party_identifiers USING btree (portable_party_id) WHERE active;


--
-- Name: portable_party_profiles_party_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX portable_party_profiles_party_idx ON request_engine.portable_party_profiles USING btree (portable_party_id) WHERE active;


--
-- Name: principal_contacts_one_active_per_principal_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX principal_contacts_one_active_per_principal_uq ON request_engine.principal_contacts USING btree (organization_id, principal_id) WHERE active;


--
-- Name: provider_events_due_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX provider_events_due_idx ON request_engine.provider_events USING btree (next_attempt_at, id) WHERE (status = 'received'::text);


--
-- Name: provider_events_reclaim_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX provider_events_reclaim_idx ON request_engine.provider_events USING btree (lease_until, id) WHERE (status = 'leased'::text);


--
-- Name: queue_entries_fifo_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX queue_entries_fifo_idx ON request_engine.queue_entries USING btree (organization_id, service_queue_id, status, admitted_at, id);


--
-- Name: queue_entries_one_active_subject_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX queue_entries_one_active_subject_uq ON request_engine.queue_entries USING btree (organization_id, service_queue_id, subject_party_id) WHERE (status = ANY (ARRAY['waiting'::text, 'called'::text, 'serving'::text]));


--
-- Name: queue_entry_recall_holds_one_active_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX queue_entry_recall_holds_one_active_uq ON request_engine.queue_entry_recall_holds USING btree (organization_id, queue_entry_id) WHERE (released_at IS NULL);


--
-- Name: queue_entry_skips_one_active_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX queue_entry_skips_one_active_uq ON request_engine.queue_entry_skips USING btree (organization_id, queue_entry_id) WHERE (consumed_at IS NULL);


--
-- Name: representations_authority_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX representations_authority_lookup_idx ON request_engine.representations USING btree (organization_id, principal_id, represented_party_id, scope_key, valid_from, id) WHERE (status = 'active'::text);


--
-- Name: reservation_access_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX reservation_access_active_idx ON request_engine.reservation_access USING btree (organization_id, reservation_id, reservation_revision, access_key) WHERE (status <> 'revoked'::text);


--
-- Name: reservation_arrival_estimates_history_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX reservation_arrival_estimates_history_idx ON request_engine.reservation_arrival_estimates USING btree (organization_id, reservation_id, asserted_at);


--
-- Name: reservation_arrival_estimates_one_active_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX reservation_arrival_estimates_one_active_uq ON request_engine.reservation_arrival_estimates USING btree (organization_id, reservation_id) WHERE (superseded_at IS NULL);


--
-- Name: reservation_attendance_status_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX reservation_attendance_status_idx ON request_engine.reservation_attendance USING btree (organization_id, status, reservation_id);


--
-- Name: reservations_org_during_gist; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX reservations_org_during_gist ON request_engine.reservations USING gist (organization_id, during);


--
-- Name: resource_activities_one_open_resource_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX resource_activities_one_open_resource_uq ON request_engine.resource_activities USING btree (organization_id, resource_id) WHERE (ended_at IS NULL);


--
-- Name: resource_location_assignments_location_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX resource_location_assignments_location_idx ON request_engine.resource_location_assignments USING btree (organization_id, location_id, status);


--
-- Name: resource_location_assignments_resource_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX resource_location_assignments_resource_idx ON request_engine.resource_location_assignments USING btree (organization_id, resource_id, status);


--
-- Name: resource_location_availability_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX resource_location_availability_lookup_idx ON request_engine.resource_location_availability USING btree (organization_id, resource_location_assignment_id, weekday, active);


--
-- Name: schedule_exceptions_resource_during_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX schedule_exceptions_resource_during_idx ON request_engine.schedule_exceptions USING gist (resource_id, during);


--
-- Name: scheduled_actions_active_subject_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX scheduled_actions_active_subject_idx ON request_engine.scheduled_actions USING btree (organization_id, owner_module, subject_kind, subject_id, action_type, action_version, execute_at) WHERE (status = ANY (ARRAY['pending'::text, 'leased'::text]));


--
-- Name: scheduled_actions_due_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX scheduled_actions_due_idx ON request_engine.scheduled_actions USING btree (next_attempt_at, id) WHERE (status = 'pending'::text);


--
-- Name: scheduled_actions_reclaim_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX scheduled_actions_reclaim_idx ON request_engine.scheduled_actions USING btree (lease_until, id) WHERE (status = 'leased'::text);


--
-- Name: scheduled_actions_recovery_scope_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX scheduled_actions_recovery_scope_idx ON request_engine.scheduled_actions USING btree (organization_id, action_type, subject_id) WHERE (owner_module = 'operational_recovery'::text);


--
-- Name: service_session_interruptions_one_open_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX service_session_interruptions_one_open_uq ON request_engine.service_session_interruptions USING btree (organization_id, service_session_id) WHERE (ended_at IS NULL);


--
-- Name: service_sessions_one_live_resource_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX service_sessions_one_live_resource_uq ON request_engine.service_sessions USING btree (organization_id, resource_id) WHERE (status = ANY (ARRAY['active'::text, 'paused'::text]));


--
-- Name: shared_capacity_authority_events_global_identity_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX shared_capacity_authority_events_global_identity_idx ON request_engine.shared_capacity_authority_events USING btree (global_identity_id);


--
-- Name: shared_capacity_authority_events_shared_capacity_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX shared_capacity_authority_events_shared_capacity_idx ON request_engine.shared_capacity_authority_events USING btree (shared_capacity_identity_id);


--
-- Name: shared_capacity_bindings_active_root_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX shared_capacity_bindings_active_root_idx ON request_engine.shared_capacity_bindings USING btree (shared_capacity_identity_id, organization_id, resource_id) WHERE (status = 'active'::text);


--
-- Name: shared_capacity_bindings_one_active_resource_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX shared_capacity_bindings_one_active_resource_idx ON request_engine.shared_capacity_bindings USING btree (organization_id, resource_id) WHERE (status = 'active'::text);


--
-- Name: shared_capacity_claim_links_root_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX shared_capacity_claim_links_root_idx ON request_engine.shared_capacity_claim_links USING btree (shared_capacity_identity_id, capacity_claim_id);


--
-- Name: shared_capacity_identities_global_identity_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX shared_capacity_identities_global_identity_idx ON request_engine.shared_capacity_identities USING btree (global_identity_id);


--
-- Name: slot_offers_active_waitlist_source_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX slot_offers_active_waitlist_source_idx ON request_engine.slot_offers USING btree (organization_id, waitlist_entry_id) WHERE (status = 'offered'::text);


--
-- Name: slot_offers_one_accepted_per_opportunity_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX slot_offers_one_accepted_per_opportunity_uq ON request_engine.slot_offers USING btree (organization_id, slot_opportunity_id) WHERE (status = 'accepted'::text);


--
-- Name: slot_offers_one_active_per_opportunity_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX slot_offers_one_active_per_opportunity_uq ON request_engine.slot_offers USING btree (organization_id, slot_opportunity_id) WHERE (status = 'offered'::text);


--
-- Name: slot_offers_opportunity_waitlist_history_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX slot_offers_opportunity_waitlist_history_idx ON request_engine.slot_offers USING btree (organization_id, slot_opportunity_id, waitlist_entry_id);


--
-- Name: slot_offers_waitlist_history_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX slot_offers_waitlist_history_idx ON request_engine.slot_offers USING btree (organization_id, waitlist_entry_id);


--
-- Name: waitlist_entries_offer_candidate_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX waitlist_entries_offer_candidate_idx ON request_engine.waitlist_entries USING btree (organization_id, offering_id, status, created_at, id) INCLUDE (subject_party_id, location_id, preferred_resource_id, earliest_start, latest_start);


--
-- Name: waitlist_entries_one_active_subject_offering_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX waitlist_entries_one_active_subject_offering_uq ON request_engine.waitlist_entries USING btree (organization_id, offering_id, subject_party_id) WHERE (status = 'active'::text);


--
-- Name: attendance_responses attendance_responses_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER attendance_responses_append_only BEFORE DELETE OR UPDATE ON request_engine.attendance_responses FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: audit_records audit_records_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER audit_records_append_only BEFORE DELETE OR UPDATE ON request_engine.audit_records FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: booking_context_terms booking_context_terms_guard_scope; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER booking_context_terms_guard_scope BEFORE UPDATE ON request_engine.booking_context_terms FOR EACH ROW EXECUTE FUNCTION request_engine.guard_booking_context_terms_scope();


--
-- Name: booking_context_terms booking_context_terms_lock_resource; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER booking_context_terms_lock_resource BEFORE INSERT OR DELETE OR UPDATE ON request_engine.booking_context_terms FOR EACH ROW EXECUTE FUNCTION request_engine.lock_booking_context_terms_resource();


--
-- Name: booking_context_terms booking_context_terms_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER booking_context_terms_revision_step BEFORE UPDATE ON request_engine.booking_context_terms FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: booking_context_terms booking_context_terms_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER booking_context_terms_touch BEFORE UPDATE ON request_engine.booking_context_terms FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: capacity_claims capacity_claims_00_guard_tenant_context; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_00_guard_tenant_context BEFORE INSERT OR UPDATE ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_tenant_context();


--
-- Name: capacity_claims capacity_claims_10_guard_contextual_assignment; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_10_guard_contextual_assignment BEFORE INSERT OR UPDATE OF organization_id, resource_id, hold_id, reservation_id, resource_location_assignment_id, during, status ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_contextual_assignment();


--
-- Name: capacity_claims capacity_claims_attach_shared_capacity; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_attach_shared_capacity AFTER INSERT OR UPDATE OF resource_id, hold_id, reservation_id, status ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.attach_shared_capacity_claim_link();


--
-- Name: capacity_claims capacity_claims_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.bump_capacity_claim_recovery_source_revision();


--
-- Name: capacity_claims capacity_claims_guard_capacity; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_guard_capacity BEFORE INSERT OR UPDATE OF resource_id, requirement_id, hold_id, reservation_id, during, quantity, status ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim();


--
-- Name: capacity_claims capacity_claims_guard_linked_provenance; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_guard_linked_provenance BEFORE UPDATE ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_linked_capacity_claim_provenance();


--
-- Name: capacity_claims capacity_claims_guard_promoted_owner; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_guard_promoted_owner BEFORE INSERT OR UPDATE OF hold_id, reservation_id, status ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_promoted_capacity_claim_owner();


--
-- Name: capacity_claims capacity_claims_guard_replacement_provenance; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_guard_replacement_provenance BEFORE INSERT OR UPDATE OF status, replaced_by_claim_id ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_replacement_provenance();


--
-- Name: capacity_claims capacity_claims_guard_terminal_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_guard_terminal_transition BEFORE UPDATE OF status, released_at, replaced_by_claim_id ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_claim_terminal_transition();


--
-- Name: capacity_claims capacity_claims_owner_completeness; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER capacity_claims_owner_completeness AFTER INSERT OR DELETE OR UPDATE ON request_engine.capacity_claims DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_capacity_owner_completeness();


--
-- Name: capacity_claims capacity_claims_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_claims_touch BEFORE UPDATE ON request_engine.capacity_claims FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: capacity_holds capacity_holds_claim_completeness; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER capacity_holds_claim_completeness AFTER INSERT OR UPDATE ON request_engine.capacity_holds DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_capacity_owner_completeness();


--
-- Name: capacity_holds capacity_holds_guard_provenance; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_holds_guard_provenance BEFORE UPDATE ON request_engine.capacity_holds FOR EACH ROW EXECUTE FUNCTION request_engine.guard_capacity_hold_provenance_update();


--
-- Name: capacity_holds capacity_holds_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_holds_guard_transition BEFORE UPDATE ON request_engine.capacity_holds FOR EACH ROW EXECUTE FUNCTION request_engine.guard_hold_transition();


--
-- Name: capacity_holds capacity_holds_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_holds_revision_step BEFORE UPDATE ON request_engine.capacity_holds FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: capacity_holds capacity_holds_slot_offer_consistency_deferred; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER capacity_holds_slot_offer_consistency_deferred AFTER UPDATE ON request_engine.capacity_holds DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_offered_slot_offer_source_consistency();


--
-- Name: capacity_holds capacity_holds_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER capacity_holds_touch BEFORE UPDATE ON request_engine.capacity_holds FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: communication_deliveries communication_deliveries_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER communication_deliveries_touch BEFORE UPDATE ON request_engine.communication_deliveries FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: communication_escalations communication_escalations_guard_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER communication_escalations_guard_append_only BEFORE DELETE OR UPDATE ON request_engine.communication_escalations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_communication_escalations();


--
-- Name: communication_tasks communication_tasks_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER communication_tasks_revision_step BEFORE UPDATE ON request_engine.communication_tasks FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: communication_tasks communication_tasks_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER communication_tasks_touch BEFORE UPDATE ON request_engine.communication_tasks FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: discovery_publications discovery_publications_broad_specific_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER discovery_publications_broad_specific_guard BEFORE INSERT OR UPDATE ON request_engine.discovery_publications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f2_publication_broad_specific_overlap();


--
-- Name: discovery_publications discovery_publications_lifecycle; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER discovery_publications_lifecycle BEFORE UPDATE ON request_engine.discovery_publications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f2_publication_lifecycle();


--
-- Name: discovery_publications discovery_publications_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER discovery_publications_revision_step BEFORE UPDATE ON request_engine.discovery_publications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: discovery_publications discovery_publications_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER discovery_publications_touch BEFORE UPDATE ON request_engine.discovery_publications FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: service_session_interruptions interruptions_session_coherence; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER interruptions_session_coherence AFTER INSERT OR UPDATE ON request_engine.service_session_interruptions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.assert_session_interruption_coherence();


--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER live_capacity_projection_policies_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.live_capacity_projection_policies FOR EACH ROW EXECUTE FUNCTION request_engine.bump_direct_queue_recovery_source_revision();


--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER live_capacity_projection_policies_guard_transition BEFORE DELETE OR UPDATE ON request_engine.live_capacity_projection_policies FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_capacity_projection_policy();


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estimate_policies_bump_recovery_source_r; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER live_capacity_workload_estimate_policies_bump_recovery_source_r AFTER INSERT OR DELETE OR UPDATE ON request_engine.live_capacity_workload_estimate_policies FOR EACH ROW EXECUTE FUNCTION request_engine.bump_estimate_policy_recovery_source_revision();


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estimate_policies_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER live_capacity_workload_estimate_policies_guard_transition BEFORE DELETE OR UPDATE ON request_engine.live_capacity_workload_estimate_policies FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_capacity_workload_estimate_policy();


--
-- Name: location_hours_exceptions location_hours_exceptions_bump_location; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER location_hours_exceptions_bump_location BEFORE INSERT OR DELETE OR UPDATE ON request_engine.location_hours_exceptions FOR EACH ROW EXECUTE FUNCTION request_engine.bump_location_operational_revision_from_child();


--
-- Name: location_hours_exceptions location_hours_exceptions_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER location_hours_exceptions_touch BEFORE UPDATE ON request_engine.location_hours_exceptions FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: location_operational_hours location_operational_hours_bump_location; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER location_operational_hours_bump_location BEFORE INSERT OR DELETE OR UPDATE ON request_engine.location_operational_hours FOR EACH ROW EXECUTE FUNCTION request_engine.bump_location_operational_revision_from_child();


--
-- Name: location_public_contact_endpoints location_public_contact_endpoints_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER location_public_contact_endpoints_touch BEFORE UPDATE ON request_engine.location_public_contact_endpoints FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: locations locations_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER locations_bump_recovery_source_revision AFTER UPDATE OF operational_revision ON request_engine.locations FOR EACH ROW EXECUTE FUNCTION request_engine.bump_location_revision_recovery_sources();


--
-- Name: locations locations_guard_operational_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER locations_guard_operational_revision BEFORE UPDATE ON request_engine.locations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_location_operational_revision();


--
-- Name: locations locations_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER locations_touch BEFORE UPDATE ON request_engine.locations FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: offering_resource_requirements offering_resource_requirements_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_resource_requirements_immutable BEFORE DELETE OR UPDATE ON request_engine.offering_resource_requirements FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: offering_service_classifications offering_service_classifications_lifecycle; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_service_classifications_lifecycle BEFORE UPDATE ON request_engine.offering_service_classifications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_f2_mapping_lifecycle();


--
-- Name: offering_service_classifications offering_service_classifications_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_service_classifications_revision_step BEFORE UPDATE ON request_engine.offering_service_classifications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: offering_service_classifications offering_service_classifications_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_service_classifications_touch BEFORE UPDATE ON request_engine.offering_service_classifications FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: offering_version_booking_policies offering_version_booking_policies_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_version_booking_policies_immutable BEFORE DELETE OR UPDATE ON request_engine.offering_version_booking_policies FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: offering_version_booking_terms offering_version_booking_terms_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_version_booking_terms_immutable BEFORE DELETE OR UPDATE ON request_engine.offering_version_booking_terms FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: offering_version_booking_terms offering_version_booking_terms_lock_root; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_version_booking_terms_lock_root BEFORE INSERT OR DELETE ON request_engine.offering_version_booking_terms FOR EACH ROW EXECUTE FUNCTION request_engine.lock_offering_version_booking_terms_root();


--
-- Name: offering_versions offering_versions_delivery_policy_validate; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_versions_delivery_policy_validate BEFORE INSERT OR UPDATE ON request_engine.offering_versions FOR EACH ROW EXECUTE FUNCTION request_engine.validate_offering_version_delivery_policy();


--
-- Name: offering_versions offering_versions_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offering_versions_immutable BEFORE DELETE OR UPDATE ON request_engine.offering_versions FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: offerings offerings_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER offerings_touch BEFORE UPDATE ON request_engine.offerings FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: operational_recovery_escalations operational_recovery_escalations_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER operational_recovery_escalations_immutable BEFORE DELETE OR UPDATE ON request_engine.operational_recovery_escalations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_recovery_escalation();


--
-- Name: operational_recovery_executions operational_recovery_executions_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER operational_recovery_executions_guard BEFORE DELETE OR UPDATE ON request_engine.operational_recovery_executions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_recovery_execution();


--
-- Name: operational_recovery_proposals operational_recovery_proposals_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER operational_recovery_proposals_immutable BEFORE DELETE OR UPDATE ON request_engine.operational_recovery_proposals FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_recovery_proposal();


--
-- Name: operational_workload_classifications operational_workload_classifications_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER operational_workload_classifications_guard_transition BEFORE DELETE OR UPDATE ON request_engine.operational_workload_classifications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_operational_workload_classification();


--
-- Name: organization_public_contact_endpoints organization_public_contact_endpoints_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER organization_public_contact_endpoints_touch BEFORE UPDATE ON request_engine.organization_public_contact_endpoints FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: organizations organizations_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER organizations_touch BEFORE UPDATE ON request_engine.organizations FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: outbox_messages outbox_messages_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER outbox_messages_touch BEFORE UPDATE ON request_engine.outbox_messages FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: parties parties_guard_kind; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER parties_guard_kind BEFORE UPDATE OF party_kind ON request_engine.parties FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_kind_immutable();


--
-- Name: parties parties_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER parties_touch BEFORE UPDATE ON request_engine.parties FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: party_administrative_identifiers party_administrative_identifiers_guard_facts; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_administrative_identifiers_guard_facts BEFORE UPDATE ON request_engine.party_administrative_identifiers FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_administrative_identifier_facts();


--
-- Name: party_administrative_identifiers party_administrative_identifiers_touch_updated_at; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_administrative_identifiers_touch_updated_at BEFORE UPDATE ON request_engine.party_administrative_identifiers FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: party_contact_points party_contact_points_guard_verification; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_contact_points_guard_verification BEFORE UPDATE ON request_engine.party_contact_points FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_contact_point_verification();


--
-- Name: party_contact_points party_contact_points_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_contact_points_touch BEFORE UPDATE ON request_engine.party_contact_points FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: party_identity_documents party_identity_documents_guard_facts; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_identity_documents_guard_facts BEFORE INSERT OR UPDATE ON request_engine.party_identity_documents FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_identity_documents();


--
-- Name: party_identity_documents party_identity_documents_touch_updated_at; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_identity_documents_touch_updated_at BEFORE UPDATE ON request_engine.party_identity_documents FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: party_identity_revisions party_identity_revisions_guard_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER party_identity_revisions_guard_append_only BEFORE DELETE OR UPDATE ON request_engine.party_identity_revisions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_party_identity_revisions();


--
-- Name: principal_contacts principal_contacts_guard_facts; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_contacts_guard_facts BEFORE UPDATE ON request_engine.principal_contacts FOR EACH ROW EXECUTE FUNCTION request_engine.guard_principal_contacts();


--
-- Name: principal_contacts principal_contacts_touch_updated_at; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_contacts_touch_updated_at BEFORE UPDATE ON request_engine.principal_contacts FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: principals principals_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principals_touch BEFORE UPDATE ON request_engine.principals FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: provider_events provider_events_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER provider_events_touch BEFORE UPDATE ON request_engine.provider_events FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: queue_entries queue_entries_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entries_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.queue_entries FOR EACH ROW EXECUTE FUNCTION request_engine.bump_direct_queue_recovery_source_revision();


--
-- Name: queue_entries queue_entries_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entries_guard_transition BEFORE UPDATE ON request_engine.queue_entries FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_entry_transition();


--
-- Name: queue_entries queue_entries_initialize_times; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entries_initialize_times BEFORE INSERT ON request_engine.queue_entries FOR EACH ROW EXECUTE FUNCTION request_engine.initialize_queue_entry_times();


--
-- Name: queue_entries queue_entries_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entries_revision_step BEFORE UPDATE ON request_engine.queue_entries FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: queue_entries queue_entries_service_session_coherence; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER queue_entries_service_session_coherence AFTER INSERT OR UPDATE ON request_engine.queue_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.assert_service_queue_coherence();


--
-- Name: queue_entries queue_entries_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entries_touch BEFORE UPDATE ON request_engine.queue_entries FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: queue_entry_operator_selections queue_entry_operator_selections_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entry_operator_selections_immutable BEFORE DELETE OR UPDATE ON request_engine.queue_entry_operator_selections FOR EACH ROW EXECUTE FUNCTION request_engine.reject_queue_entry_operator_selection_mutation();


--
-- Name: queue_entry_recall_holds queue_entry_recall_holds_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entry_recall_holds_guard BEFORE DELETE OR UPDATE ON request_engine.queue_entry_recall_holds FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_entry_recall_hold();


--
-- Name: queue_entry_skips queue_entry_skips_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER queue_entry_skips_guard BEFORE DELETE OR UPDATE ON request_engine.queue_entry_skips FOR EACH ROW EXECUTE FUNCTION request_engine.guard_queue_entry_skip();


--
-- Name: reminder_acknowledgements reminder_acknowledgements_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reminder_acknowledgements_append_only BEFORE DELETE OR UPDATE ON request_engine.reminder_acknowledgements FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: reminder_plans reminder_plans_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reminder_plans_guard_transition BEFORE UPDATE ON request_engine.reminder_plans FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reminder_plan_transition();


--
-- Name: reminder_plans reminder_plans_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reminder_plans_revision_step BEFORE UPDATE ON request_engine.reminder_plans FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: reminder_plans reminder_plans_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reminder_plans_touch BEFORE UPDATE ON request_engine.reminder_plans FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: representations representations_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER representations_revision_step BEFORE UPDATE ON request_engine.representations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: representations representations_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER representations_touch BEFORE UPDATE ON request_engine.representations FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: request_definition_versions request_definition_versions_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER request_definition_versions_immutable BEFORE DELETE OR UPDATE ON request_engine.request_definition_versions FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: request_definitions request_definitions_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER request_definitions_touch BEFORE UPDATE ON request_engine.request_definitions FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: requests requests_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER requests_guard_transition BEFORE UPDATE ON request_engine.requests FOR EACH ROW EXECUTE FUNCTION request_engine.guard_request_transition();


--
-- Name: requests requests_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER requests_revision_step BEFORE UPDATE ON request_engine.requests FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: requests requests_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER requests_touch BEFORE UPDATE ON request_engine.requests FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: reservation_access reservation_access_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_access_touch BEFORE UPDATE ON request_engine.reservation_access FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_assert_reservation_confirmed; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_arrival_estimates_assert_reservation_confirmed BEFORE INSERT ON request_engine.reservation_arrival_estimates FOR EACH ROW EXECUTE FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed();


--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_arrival_estimates_guard_transition BEFORE DELETE OR UPDATE ON request_engine.reservation_arrival_estimates FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_arrival_estimate();


--
-- Name: reservation_attendance reservation_attendance_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_attendance_revision_step BEFORE UPDATE ON request_engine.reservation_attendance FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: reservation_attendance reservation_attendance_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_attendance_touch BEFORE UPDATE ON request_engine.reservation_attendance FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: reservation_commercial_commitment_context_terms reservation_commercial_commitment_context_terms_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_commercial_commitment_context_terms_append_only BEFORE DELETE OR UPDATE ON request_engine.reservation_commercial_commitment_context_terms FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: reservation_commercial_commitments reservation_commercial_commitments_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservation_commercial_commitments_append_only BEFORE DELETE OR UPDATE ON request_engine.reservation_commercial_commitments FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: reservations reservations_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservations_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.reservations FOR EACH ROW EXECUTE FUNCTION request_engine.bump_reservation_recovery_source_revision();


--
-- Name: reservations reservations_claim_completeness; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER reservations_claim_completeness AFTER INSERT OR UPDATE ON request_engine.reservations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_capacity_owner_completeness();


--
-- Name: reservations reservations_guard_discovery_handoff; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservations_guard_discovery_handoff BEFORE INSERT ON request_engine.reservations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_discovery_handoff_reservation();


--
-- Name: reservations reservations_guard_discovery_latest_version; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservations_guard_discovery_latest_version BEFORE INSERT ON request_engine.reservations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_discovery_handoff_latest_version();


--
-- Name: reservations reservations_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservations_guard_transition BEFORE UPDATE ON request_engine.reservations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_reservation_transition();


--
-- Name: reservations reservations_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservations_revision_step BEFORE UPDATE ON request_engine.reservations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: reservations reservations_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER reservations_touch BEFORE UPDATE ON request_engine.reservations FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: resource_activities resource_activities_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_activities_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.resource_activities FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_activity_recovery_source_revision();


--
-- Name: resource_activities resource_activities_guard_resource_occupation; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_activities_guard_resource_occupation BEFORE INSERT OR UPDATE OF resource_id, ended_at ON request_engine.resource_activities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_resource_occupation();


--
-- Name: resource_activities resource_activities_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_activities_guard_transition BEFORE UPDATE ON request_engine.resource_activities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_resource_activity_transition();


--
-- Name: resource_location_assignments resource_location_assignments_bump_resource; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_location_assignments_bump_resource BEFORE INSERT OR DELETE OR UPDATE ON request_engine.resource_location_assignments FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_from_assignment();


--
-- Name: resource_location_assignments resource_location_assignments_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_location_assignments_guard BEFORE UPDATE ON request_engine.resource_location_assignments FOR EACH ROW EXECUTE FUNCTION request_engine.guard_resource_location_assignment();


--
-- Name: resource_location_assignments resource_location_assignments_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_location_assignments_revision_step BEFORE UPDATE ON request_engine.resource_location_assignments FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: resource_location_assignments resource_location_assignments_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_location_assignments_touch BEFORE UPDATE ON request_engine.resource_location_assignments FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: resource_location_availability resource_location_availability_bump_resource; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_location_availability_bump_resource BEFORE INSERT OR DELETE OR UPDATE ON request_engine.resource_location_availability FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_from_assignment_child();


--
-- Name: resource_location_schedule_exceptions resource_location_exceptions_bump_resource; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

