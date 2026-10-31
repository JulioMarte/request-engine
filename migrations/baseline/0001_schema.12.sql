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

INSERT INTO request_engine.platform_instance (
    singleton_key,
    built_in_native_authority_id,
    built_in_workload_authority_id
)
SELECT 1, native.id, workload.id
FROM request_engine.identity_authorities AS native
CROSS JOIN request_engine.identity_authorities AS workload
WHERE native.kind = 'native'
  AND native.issuer_or_environment = 'request-engine-native'
  AND workload.kind = 'workload'
  AND workload.issuer_or_environment = 'request-engine-workload';


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
INSERT INTO request_engine.platform_owner_policies VALUES ('platform-owner-v4', 4, '[{"delegable": true, "capability_key": "platform.principal.provision"}, {"delegable": true, "capability_key": "platform.tenant_provisioner.provision"}, {"delegable": false, "capability_key": "platform.recovery_operator.provision"}, {"delegable": true, "capability_key": "organization.provision"}, {"delegable": false, "capability_key": "platform.identity.recover"}, {"delegable": false, "capability_key": "platform.identity.read"}, {"delegable": false, "capability_key": "platform.identity.provision"}, {"delegable": false, "capability_key": "platform.identity.recovery_approve"}, {"delegable": false, "capability_key": "platform.provisioner.read"}, {"delegable": false, "capability_key": "platform.provisioner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.owner.read"}, {"delegable": false, "capability_key": "platform.owner.provision"}, {"delegable": false, "capability_key": "platform.owner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.configuration.read"}, {"delegable": false, "capability_key": "platform.configuration.stage"}, {"delegable": false, "capability_key": "platform.configuration.validate"}, {"delegable": false, "capability_key": "platform.configuration.activate"}, {"delegable": false, "capability_key": "platform.configuration.disable"}, {"delegable": false, "capability_key": "platform.secret.write"}, {"delegable": false, "capability_key": "platform.secret.rotate"}, {"delegable": false, "capability_key": "platform.secret.revoke"}, {"delegable": false, "capability_key": "platform.provider.test"}, {"delegable": false, "capability_key": "platform.readiness.read"}, {"delegable": false, "capability_key": "platform.organization.read"}]');
INSERT INTO request_engine.platform_owner_policies VALUES ('platform-owner-v5', 5, '[{"delegable": true, "capability_key": "platform.principal.provision"}, {"delegable": true, "capability_key": "platform.tenant_provisioner.provision"}, {"delegable": false, "capability_key": "platform.recovery_operator.provision"}, {"delegable": true, "capability_key": "organization.provision"}, {"delegable": false, "capability_key": "platform.identity.recover"}, {"delegable": false, "capability_key": "platform.identity.read"}, {"delegable": false, "capability_key": "platform.identity.provision"}, {"delegable": false, "capability_key": "platform.identity.recovery_approve"}, {"delegable": false, "capability_key": "platform.provisioner.read"}, {"delegable": false, "capability_key": "platform.provisioner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.owner.read"}, {"delegable": false, "capability_key": "platform.owner.provision"}, {"delegable": false, "capability_key": "platform.owner.manage_lifecycle"}, {"delegable": false, "capability_key": "platform.configuration.read"}, {"delegable": false, "capability_key": "platform.configuration.stage"}, {"delegable": false, "capability_key": "platform.configuration.validate"}, {"delegable": false, "capability_key": "platform.configuration.activate"}, {"delegable": false, "capability_key": "platform.configuration.disable"}, {"delegable": false, "capability_key": "platform.secret.write"}, {"delegable": false, "capability_key": "platform.secret.rotate"}, {"delegable": false, "capability_key": "platform.secret.revoke"}, {"delegable": false, "capability_key": "platform.provider.test"}, {"delegable": false, "capability_key": "platform.readiness.read"}, {"delegable": false, "capability_key": "platform.organization.read"}, {"delegable": false, "capability_key": "platform.organization.adopt_initial_controller_policy"}]');


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
-- Data for Name: staff_invitation_deliveries; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: staff_invitation_proposals; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: staff_invitations; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: staff_member_profiles; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: staff_memberships; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: temporary_proof_cleanup_results; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: temporary_proof_cleanup_work; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
--



--
-- Data for Name: temporary_proof_retention_receipts; Type: TABLE DATA; Schema: request_engine; Owner: request_engine_schema_owner
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
-- Name: controller_policy_adoption_facts controller_policy_adoption_facts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.controller_policy_adoption_facts
    ADD CONSTRAINT controller_policy_adoption_facts_pkey PRIMARY KEY (id);


--
-- Name: controller_policy_adoption_facts controller_policy_adoption_facts_request_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.controller_policy_adoption_facts
    ADD CONSTRAINT controller_policy_adoption_facts_request_id_key UNIQUE (request_id);


--
-- Name: controller_policy_adoption_requests controller_policy_adoption_re_controller_principal_id_idemp_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.controller_policy_adoption_requests
    ADD CONSTRAINT controller_policy_adoption_re_controller_principal_id_idemp_key UNIQUE (controller_principal_id, idempotency_key_digest);


--
-- Name: controller_policy_adoption_requests controller_policy_adoption_requests_id_organization_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.controller_policy_adoption_requests
    ADD CONSTRAINT controller_policy_adoption_requests_id_organization_id_key UNIQUE (id, organization_id);


--
-- Name: controller_policy_adoption_requests controller_policy_adoption_requests_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.controller_policy_adoption_requests
    ADD CONSTRAINT controller_policy_adoption_requests_pkey PRIMARY KEY (id);


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
-- Name: http_auth_admission_state http_auth_admission_state_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: postgres
--

ALTER TABLE ONLY request_engine.http_auth_admission_state
    ADD CONSTRAINT http_auth_admission_state_pkey PRIMARY KEY (singleton);


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
-- Name: native_identity_provision_receipts native_identity_provision_receipts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.native_identity_provision_receipts
    ADD CONSTRAINT native_identity_provision_receipts_pkey PRIMARY KEY (actor_principal_id, idempotency_key_digest);


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
-- Name: setup_pending_identity setup_pending_identity_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.setup_pending_identity
    ADD CONSTRAINT setup_pending_identity_pkey PRIMARY KEY (id);


--
-- Name: setup_pending_identity setup_pending_identity_setup_session_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.setup_pending_identity
    ADD CONSTRAINT setup_pending_identity_setup_session_id_key UNIQUE (setup_session_id);


--
-- Name: setup_pending_webauthn_credential setup_pending_webauthn_credential_credential_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.setup_pending_webauthn_credential
    ADD CONSTRAINT setup_pending_webauthn_credential_credential_id_key UNIQUE (credential_id);


--
-- Name: setup_pending_webauthn_credential setup_pending_webauthn_credential_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.setup_pending_webauthn_credential
    ADD CONSTRAINT setup_pending_webauthn_credential_pkey PRIMARY KEY (id);


--
-- Name: setup_sessions setup_sessions_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.setup_sessions
    ADD CONSTRAINT setup_sessions_pkey PRIMARY KEY (id);


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
-- Name: staff_invitation_deliveries staff_invitation_deliveries_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitation_deliveries
    ADD CONSTRAINT staff_invitation_deliveries_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: staff_invitation_deliveries staff_invitation_deliveries_organization_id_invitation_id_g_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitation_deliveries
    ADD CONSTRAINT staff_invitation_deliveries_organization_id_invitation_id_g_key UNIQUE (organization_id, invitation_id, generation);


--
-- Name: staff_invitation_deliveries staff_invitation_deliveries_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitation_deliveries
    ADD CONSTRAINT staff_invitation_deliveries_pkey PRIMARY KEY (id);


--
-- Name: staff_invitation_proposals staff_invitation_proposals_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitation_proposals
    ADD CONSTRAINT staff_invitation_proposals_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: staff_invitation_proposals staff_invitation_proposals_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitation_proposals
    ADD CONSTRAINT staff_invitation_proposals_pkey PRIMARY KEY (id);


--
-- Name: staff_invitations staff_invitations_organization_id_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitations
    ADD CONSTRAINT staff_invitations_organization_id_id_key UNIQUE (organization_id, id);


--
-- Name: staff_invitations staff_invitations_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_invitations
    ADD CONSTRAINT staff_invitations_pkey PRIMARY KEY (id);


--
-- Name: staff_member_profiles staff_member_profiles_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_member_profiles
    ADD CONSTRAINT staff_member_profiles_pkey PRIMARY KEY (organization_id, membership_id);


--
-- Name: staff_memberships staff_memberships_org_id_unique; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_org_id_unique UNIQUE (organization_id, id);


--
-- Name: staff_memberships staff_memberships_org_id_uq; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_org_id_uq UNIQUE (organization_id, id);


--
-- Name: staff_memberships staff_memberships_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_pkey PRIMARY KEY (id);


--
-- Name: temporary_proof_cleanup_results temporary_proof_cleanup_results_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.temporary_proof_cleanup_results
    ADD CONSTRAINT temporary_proof_cleanup_results_pkey PRIMARY KEY (work_id, lease_token);


--
-- Name: temporary_proof_cleanup_results temporary_proof_cleanup_results_work_id_attempt_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.temporary_proof_cleanup_results
    ADD CONSTRAINT temporary_proof_cleanup_results_work_id_attempt_key UNIQUE (work_id, attempt);


--
-- Name: temporary_proof_cleanup_work temporary_proof_cleanup_work_backend_id_mount_reference_ver_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.temporary_proof_cleanup_work
    ADD CONSTRAINT temporary_proof_cleanup_work_backend_id_mount_reference_ver_key UNIQUE (backend_id, mount, reference, version, created_at);


--
-- Name: temporary_proof_cleanup_work temporary_proof_cleanup_work_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.temporary_proof_cleanup_work
    ADD CONSTRAINT temporary_proof_cleanup_work_pkey PRIMARY KEY (id);


--
-- Name: temporary_proof_retention_receipts temporary_proof_retention_receipts_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.temporary_proof_retention_receipts
    ADD CONSTRAINT temporary_proof_retention_receipts_pkey PRIMARY KEY (backend_id, mount, reference, version, created_at);


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
-- Name: webauthn_challenges webauthn_challenges_challenge_digest_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_challenge_digest_key UNIQUE (challenge_digest);


--
-- Name: webauthn_challenges webauthn_challenges_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_pkey PRIMARY KEY (id);


--
-- Name: webauthn_credentials webauthn_credentials_credential_id_key; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_credentials
    ADD CONSTRAINT webauthn_credentials_credential_id_key UNIQUE (credential_id);


--
-- Name: webauthn_credentials webauthn_credentials_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_credentials
    ADD CONSTRAINT webauthn_credentials_pkey PRIMARY KEY (id);


--
-- Name: workload_credentials workload_credentials_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.workload_credentials
    ADD CONSTRAINT workload_credentials_pkey PRIMARY KEY (id);


--
-- Name: workload_identities workload_identities_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.workload_identities
    ADD CONSTRAINT workload_identities_pkey PRIMARY KEY (id);


--
-- Name: agent_budget_windows_agent_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX agent_budget_windows_agent_idx ON request_engine.agent_budget_windows USING btree (agent_principal_id, window_started_at);


--
-- Name: agent_profiles_organization_status_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX agent_profiles_organization_status_idx ON request_engine.agent_profiles USING btree (organization_id, status, principal_id);


--
-- Name: agent_profiles_workload_identity_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX agent_profiles_workload_identity_uq ON request_engine.agent_profiles USING btree (workload_identity_id);


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
-- Name: capacity_claims_reservation_current_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_reservation_current_idx ON request_engine.capacity_claims USING btree (organization_id, reservation_id) WHERE ((reservation_id IS NOT NULL) AND (status <> 'replaced'::text));


--
-- Name: capacity_claims_resource_during_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_resource_during_idx ON request_engine.capacity_claims USING gist (resource_id, during);


--
-- Name: capacity_claims_resource_location_assignment_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX capacity_claims_resource_location_assignment_idx ON request_engine.capacity_claims USING btree (organization_id, resource_location_assignment_id) WHERE (resource_location_assignment_id IS NOT NULL);


--
-- Name: communication_deliveries_metrics_failure_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX communication_deliveries_metrics_failure_idx ON request_engine.communication_deliveries USING btree (updated_at) WHERE (status = ANY (ARRAY['failed'::text, 'ambiguous'::text]));


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
-- Name: controller_policy_adoption_pending_order; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX controller_policy_adoption_pending_order ON request_engine.controller_policy_adoption_requests USING btree (created_at, id) WHERE (status = 'pending'::text);


--
-- Name: delegations_delegate_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX delegations_delegate_active_idx ON request_engine.delegations USING btree (delegate_principal_id, status, expires_at);


--
