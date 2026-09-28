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
-- Name: staff_memberships staff_memberships_pkey; Type: CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_pkey PRIMARY KEY (id);


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
-- Name: delegations_delegate_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX delegations_delegate_active_idx ON request_engine.delegations USING btree (delegate_principal_id, status, expires_at);


--
-- Name: discovery_booking_handoffs_expiry_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX discovery_booking_handoffs_expiry_idx ON request_engine.discovery_booking_handoffs USING btree (expires_at) WHERE (consumed_reservation_id IS NULL);


--
-- Name: discovery_publications_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX discovery_publications_lookup_idx ON request_engine.discovery_publications USING btree (organization_id, offering_id, location_id, status);


--
-- Name: identity_bindings_platform_subject_live_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX identity_bindings_platform_subject_live_uq ON request_engine.identity_bindings USING btree (identity_authority_id, subject_id) WHERE ((organization_id IS NULL) AND (status <> 'revoked'::text));


--
-- Name: identity_bindings_principal_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX identity_bindings_principal_lookup_idx ON request_engine.identity_bindings USING btree (principal_id, status, identity_authority_id);


--
-- Name: identity_bindings_tenant_subject_live_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX identity_bindings_tenant_subject_live_uq ON request_engine.identity_bindings USING btree (identity_authority_id, subject_id, organization_id) WHERE ((organization_id IS NOT NULL) AND (status <> 'revoked'::text));


--
-- Name: identity_exchange_candidate_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX identity_exchange_candidate_lookup_idx ON request_engine.identity_exchange_candidates USING btree (organization_id, id, expires_at);


--
-- Name: identity_link_intents_actor_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX identity_link_intents_actor_lookup_idx ON request_engine.identity_link_intents USING btree (actor_principal_id, status, created_at);


--
-- Name: identity_link_intents_live_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX identity_link_intents_live_uq ON request_engine.identity_link_intents USING btree (organization_id, actor_principal_id, target_authority_id) WHERE (status = 'pending'::text);


--
-- Name: identity_link_intents_nonce_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX identity_link_intents_nonce_uq ON request_engine.identity_link_intents USING btree (organization_id, nonce_digest);


--
-- Name: integration_facts_history_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX integration_facts_history_idx ON request_engine.integration_governance_facts USING btree (organization_id, integration_principal_id, occurred_at, id);


--
-- Name: location_operational_hours_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX location_operational_hours_lookup_idx ON request_engine.location_operational_hours USING btree (organization_id, location_id, weekday, active);


--
-- Name: native_credentials_one_active_password_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX native_credentials_one_active_password_uq ON request_engine.native_credentials USING btree (native_identity_id, kind) WHERE (status = 'active'::text);


--
-- Name: native_identity_recovery_facts_identity_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_identity_recovery_facts_identity_idx ON request_engine.native_identity_recovery_facts USING btree (native_identity_id, created_at);


--
-- Name: native_recovery_address_verifications_pending_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX native_recovery_address_verifications_pending_uq ON request_engine.native_recovery_address_verifications USING btree (recovery_address_id) WHERE (status = 'pending'::text);


--
-- Name: native_recovery_addresses_identity_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_recovery_addresses_identity_idx ON request_engine.native_recovery_addresses USING btree (native_identity_id, status, verified_at DESC);


--
-- Name: native_recovery_addresses_live_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX native_recovery_addresses_live_uq ON request_engine.native_recovery_addresses USING btree (native_identity_id, kind, normalized_address) WHERE (status <> 'revoked'::text);


--
-- Name: native_recovery_delivery_requests_claim_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_recovery_delivery_requests_claim_idx ON request_engine.native_recovery_delivery_requests USING btree (next_attempt_at, id) WHERE (status = 'pending'::text);


--
-- Name: native_recovery_delivery_requests_identity_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_recovery_delivery_requests_identity_idx ON request_engine.native_recovery_delivery_requests USING btree (native_identity_id, created_at DESC);


--
-- Name: native_recovery_identity_pending_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_recovery_identity_pending_idx ON request_engine.native_recovery_intents USING btree (native_identity_id, expires_at) WHERE (status = 'pending'::text);


--
-- Name: native_recovery_token_digest_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX native_recovery_token_digest_uq ON request_engine.native_recovery_intents USING btree (token_digest);


--
-- Name: native_sessions_identity_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_sessions_identity_active_idx ON request_engine.native_sessions USING btree (native_identity_id, expires_at) WHERE (status = 'active'::text);


--
-- Name: native_sessions_token_digest_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX native_sessions_token_digest_uq ON request_engine.native_sessions USING btree (token_digest);


--
-- Name: native_sessions_webauthn_credential_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX native_sessions_webauthn_credential_active_idx ON request_engine.native_sessions USING btree (webauthn_credential_id) WHERE (status = 'active'::text);


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
-- Name: platform_bootstrap_intents_pending_expiry_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX platform_bootstrap_intents_pending_expiry_idx ON request_engine.platform_bootstrap_intents USING btree (expires_at) WHERE (status = 'pending'::text);


--
-- Name: platform_configuration_fact_idempotency_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX platform_configuration_fact_idempotency_uq ON request_engine.platform_configuration_facts USING btree (actor_principal_id, capability_key, idempotency_key_digest) WHERE (idempotency_key_digest IS NOT NULL);


--
-- Name: platform_configuration_kind_revision_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX platform_configuration_kind_revision_idx ON request_engine.platform_configuration_revisions USING btree (configuration_kind, revision DESC);


--
-- Name: platform_configuration_one_active_kind_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX platform_configuration_one_active_kind_uq ON request_engine.platform_configuration_revisions USING btree (configuration_kind) WHERE (state = 'active'::text);


--
-- Name: platform_identity_disable_facts_idempotency_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX platform_identity_disable_facts_idempotency_uq ON request_engine.platform_identity_disable_facts USING btree (actor_principal_id, capability_key, idempotency_key_digest);


--
-- Name: platform_secret_bindings_active_purpose_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX platform_secret_bindings_active_purpose_uq ON request_engine.platform_secret_bindings USING btree (purpose) WHERE (status = 'active'::text);


--
-- Name: platform_secret_mutations_open_binding_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX platform_secret_mutations_open_binding_uq ON request_engine.platform_secret_mutations USING btree (binding_id) WHERE ((binding_id IS NOT NULL) AND (state = ANY (ARRAY['prepared'::text, 'backend_applied'::text, 'reconcile_required'::text])));


--
-- Name: platform_secret_mutations_open_create_purpose_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX platform_secret_mutations_open_create_purpose_uq ON request_engine.platform_secret_mutations USING btree (purpose) WHERE ((operation_kind = 'create'::text) AND (state = ANY (ARRAY['prepared'::text, 'backend_applied'::text, 'reconcile_required'::text])));


--
-- Name: platform_secret_mutations_state_created_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX platform_secret_mutations_state_created_idx ON request_engine.platform_secret_mutations USING btree (state, created_at);


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
-- Name: principal_authority_grants_active_capability_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX principal_authority_grants_active_capability_uq ON request_engine.principal_authority_grants USING btree (principal_id, capability_key) WHERE (status = 'active'::text);


--
-- Name: principal_authority_grants_tenant_lookup_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX principal_authority_grants_tenant_lookup_idx ON request_engine.principal_authority_grants USING btree (organization_id, principal_id, authority_plane, capability_key) WHERE (status = 'active'::text);


--
-- Name: principal_contacts_one_active_per_principal_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX principal_contacts_one_active_per_principal_uq ON request_engine.principal_contacts USING btree (organization_id, principal_id) WHERE active;


--
-- Name: principals_platform_subject_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX principals_platform_subject_uq ON request_engine.principals USING btree (principal_kind, external_subject) WHERE (principal_plane = 'platform'::text);


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
-- Name: recovery_code_sets_active_identity_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX recovery_code_sets_active_identity_uq ON request_engine.recovery_code_sets USING btree (native_identity_id) WHERE ((status = 'active'::text) AND (native_identity_id IS NOT NULL));


--
-- Name: recovery_code_sets_active_setup_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX recovery_code_sets_active_setup_uq ON request_engine.recovery_code_sets USING btree (setup_session_id) WHERE ((status = 'active'::text) AND (setup_session_id IS NOT NULL));


--
-- Name: recovery_codes_set_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX recovery_codes_set_idx ON request_engine.recovery_codes USING btree (set_id);


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
-- Name: setup_pending_webauthn_session_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX setup_pending_webauthn_session_idx ON request_engine.setup_pending_webauthn_credential USING btree (setup_session_id) WHERE (status = 'pending'::text);


--
-- Name: setup_sessions_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX setup_sessions_active_idx ON request_engine.setup_sessions USING btree (expires_at) WHERE (status = 'pending'::text);


--
-- Name: setup_sessions_token_digest_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX setup_sessions_token_digest_uq ON request_engine.setup_sessions USING btree (token_digest);


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
-- Name: staff_memberships_binding_live_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX staff_memberships_binding_live_uq ON request_engine.staff_memberships USING btree (identity_binding_id) WHERE (status <> 'revoked'::text);


--
-- Name: staff_memberships_principal_live_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX staff_memberships_principal_live_uq ON request_engine.staff_memberships USING btree (principal_id) WHERE (status <> 'revoked'::text);


--
-- Name: staff_memberships_tenant_status_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX staff_memberships_tenant_status_idx ON request_engine.staff_memberships USING btree (organization_id, status, principal_id);


--
-- Name: waitlist_entries_offer_candidate_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX waitlist_entries_offer_candidate_idx ON request_engine.waitlist_entries USING btree (organization_id, offering_id, status, created_at, id) INCLUDE (subject_party_id, location_id, preferred_resource_id, earliest_start, latest_start);


--
-- Name: waitlist_entries_one_active_subject_offering_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX waitlist_entries_one_active_subject_offering_uq ON request_engine.waitlist_entries USING btree (organization_id, offering_id, subject_party_id) WHERE (status = 'active'::text);


--
-- Name: webauthn_challenges_scope_pending_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX webauthn_challenges_scope_pending_idx ON request_engine.webauthn_challenges USING btree (purpose, expires_at) WHERE (status = 'pending'::text);


--
-- Name: webauthn_credentials_identity_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX webauthn_credentials_identity_active_idx ON request_engine.webauthn_credentials USING btree (native_identity_id) WHERE (status = 'active'::text);


--
-- Name: workload_credentials_identity_active_idx; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE INDEX workload_credentials_identity_active_idx ON request_engine.workload_credentials USING btree (workload_identity_id, expires_at) WHERE (status = 'active'::text);


--
-- Name: workload_credentials_token_digest_uq; Type: INDEX; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE UNIQUE INDEX workload_credentials_token_digest_uq ON request_engine.workload_credentials USING btree (token_digest);


--
-- Name: agent_profiles agent_profiles_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER agent_profiles_guard BEFORE INSERT OR DELETE OR UPDATE ON request_engine.agent_profiles FOR EACH ROW EXECUTE FUNCTION request_engine.guard_agent_profile();


--
-- Name: attendance_responses attendance_responses_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER attendance_responses_append_only BEFORE DELETE OR UPDATE ON request_engine.attendance_responses FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: audit_records audit_records_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER audit_records_append_only BEFORE DELETE OR UPDATE ON request_engine.audit_records FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: organization_provisioning_facts authority_reference_tenant_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER authority_reference_tenant_guard BEFORE INSERT OR UPDATE ON request_engine.organization_provisioning_facts FOR EACH ROW EXECUTE FUNCTION request_engine.guard_authority_reference_tenant();


--
-- Name: organization_root_provisioning_facts authority_reference_tenant_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER authority_reference_tenant_guard BEFORE INSERT OR UPDATE ON request_engine.organization_root_provisioning_facts FOR EACH ROW EXECUTE FUNCTION request_engine.guard_authority_reference_tenant();


--
-- Name: principal_authority_grants authority_reference_tenant_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER authority_reference_tenant_guard BEFORE INSERT OR UPDATE ON request_engine.principal_authority_grants FOR EACH ROW EXECUTE FUNCTION request_engine.guard_authority_reference_tenant();


--
-- Name: staff_memberships authority_reference_tenant_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER authority_reference_tenant_guard BEFORE INSERT OR UPDATE ON request_engine.staff_memberships FOR EACH ROW EXECUTE FUNCTION request_engine.guard_authority_reference_tenant();


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
-- Name: delegations delegations_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER delegations_guard BEFORE INSERT OR DELETE OR UPDATE ON request_engine.delegations FOR EACH ROW EXECUTE FUNCTION request_engine.guard_delegation();


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
-- Name: identity_bindings identity_bindings_bump_principal_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER identity_bindings_bump_principal_revision AFTER INSERT OR UPDATE ON request_engine.identity_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.bump_principal_authority_from_identity_binding();


--
-- Name: identity_bindings identity_bindings_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER identity_bindings_guard BEFORE INSERT OR DELETE OR UPDATE ON request_engine.identity_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.guard_identity_binding();


--
-- Name: identity_link_intents identity_link_intents_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER identity_link_intents_guard BEFORE DELETE OR UPDATE ON request_engine.identity_link_intents FOR EACH ROW EXECUTE FUNCTION request_engine.guard_identity_link_intent();


--
-- Name: initial_controller_policies initial_controller_policy_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER initial_controller_policy_immutable BEFORE DELETE OR UPDATE ON request_engine.initial_controller_policies FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: integration_governance_facts integration_facts_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER integration_facts_immutable BEFORE DELETE OR UPDATE ON request_engine.integration_governance_facts FOR EACH ROW EXECUTE FUNCTION request_engine.guard_integration_fact();


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
-- Name: native_credentials native_credentials_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_credentials_guard BEFORE INSERT OR UPDATE ON request_engine.native_credentials FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_credential();


--
-- Name: native_identities native_identities_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_identities_guard BEFORE INSERT OR UPDATE ON request_engine.native_identities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_identity();


--
-- Name: native_identities native_identities_revoke_webauthn_credentials; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_identities_revoke_webauthn_credentials AFTER UPDATE ON request_engine.native_identities FOR EACH ROW EXECUTE FUNCTION request_engine.revoke_webauthn_credentials_on_disable();


--
-- Name: native_identity_recovery_facts native_identity_recovery_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_identity_recovery_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.native_identity_recovery_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: native_recovery_address_facts native_recovery_address_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_recovery_address_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.native_recovery_address_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: native_recovery_delivery_facts native_recovery_delivery_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_recovery_delivery_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.native_recovery_delivery_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: native_recovery_intents native_recovery_intents_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_recovery_intents_guard BEFORE INSERT OR UPDATE ON request_engine.native_recovery_intents FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_recovery_intent();


--
-- Name: native_sessions native_sessions_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER native_sessions_guard BEFORE INSERT OR UPDATE ON request_engine.native_sessions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_native_session();


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
-- Name: organization_root_provisioning_facts organization_root_seed_initial_policy; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER organization_root_seed_initial_policy AFTER INSERT ON request_engine.organization_root_provisioning_facts FOR EACH ROW EXECUTE FUNCTION request_engine.seed_initial_controller_policy();


--
-- Name: organization_root_provisioning_facts organization_root_seed_staff_membership; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER organization_root_seed_staff_membership AFTER INSERT ON request_engine.organization_root_provisioning_facts FOR EACH ROW EXECUTE FUNCTION request_engine.seed_root_staff_membership();


--
-- Name: organization_root_provisioning_facts organization_root_seed_staff_read_authority; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER organization_root_seed_staff_read_authority AFTER INSERT ON request_engine.organization_root_provisioning_facts FOR EACH ROW EXECUTE FUNCTION request_engine.seed_root_staff_read_authority();


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
-- Name: platform_authority_lifecycle_facts platform_authority_lifecycle_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_authority_lifecycle_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_authority_lifecycle_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_bootstrap_intents platform_bootstrap_intents_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_bootstrap_intents_guard BEFORE INSERT OR DELETE OR UPDATE ON request_engine.platform_bootstrap_intents FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_bootstrap_intent();


--
-- Name: platform_configuration_facts platform_configuration_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_configuration_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_configuration_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_configuration_revisions platform_configuration_managed_oidc_projection; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_configuration_managed_oidc_projection AFTER UPDATE OF state ON request_engine.platform_configuration_revisions FOR EACH ROW EXECUTE FUNCTION request_engine.project_managed_oidc_authority();


--
-- Name: platform_configuration_revisions platform_configuration_revision_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_configuration_revision_guard BEFORE UPDATE ON request_engine.platform_configuration_revisions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_configuration_revision();


--
-- Name: platform_identity_recovery_facts platform_identity_recovery_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_identity_recovery_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_identity_recovery_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_installation_claim_facts platform_installation_claim_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_installation_claim_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_installation_claim_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_instance platform_instance_grant_owner_v2_capabilities; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_instance_grant_owner_v2_capabilities AFTER UPDATE OF state ON request_engine.platform_instance FOR EACH ROW WHEN ((old.state IS DISTINCT FROM new.state)) EXECUTE FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim();


--
-- Name: platform_instance platform_instance_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_instance_guard BEFORE INSERT OR DELETE OR UPDATE ON request_engine.platform_instance FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_instance();


--
-- Name: platform_owner_invitation_facts platform_owner_invitation_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_owner_invitation_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_owner_invitation_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_owner_policies platform_owner_policy_immutable; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_owner_policy_immutable BEFORE DELETE OR UPDATE ON request_engine.platform_owner_policies FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_owner_provisioning_facts platform_owner_provisioning_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_owner_provisioning_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_owner_provisioning_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_recovery_code_facts platform_recovery_code_facts_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_recovery_code_facts_append_only BEFORE DELETE OR UPDATE ON request_engine.platform_recovery_code_facts FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: platform_secret_bindings platform_secret_binding_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_secret_binding_guard BEFORE UPDATE ON request_engine.platform_secret_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.guard_platform_secret_binding();


--
-- Name: platform_secret_bindings platform_secret_binding_runtime_notify; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER platform_secret_binding_runtime_notify AFTER UPDATE ON request_engine.platform_secret_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.notify_platform_secret_runtime_change();


--
-- Name: principal_authority_grants principal_authority_adopt_platform_owner_v3; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_authority_adopt_platform_owner_v3 AFTER INSERT ON request_engine.principal_authority_grants FOR EACH ROW EXECUTE FUNCTION request_engine.adopt_platform_owner_v3();


--
-- Name: principal_authority_grants principal_authority_grants_bump_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_authority_grants_bump_revision AFTER INSERT OR UPDATE ON request_engine.principal_authority_grants FOR EACH ROW EXECUTE FUNCTION request_engine.bump_principal_authority_from_grant();


--
-- Name: principal_authority_grants principal_authority_grants_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_authority_grants_guard BEFORE INSERT OR DELETE OR UPDATE ON request_engine.principal_authority_grants FOR EACH ROW EXECUTE FUNCTION request_engine.guard_principal_authority_grant();


--
-- Name: principal_contacts principal_contacts_guard_facts; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_contacts_guard_facts BEFORE UPDATE ON request_engine.principal_contacts FOR EACH ROW EXECUTE FUNCTION request_engine.guard_principal_contacts();


--
-- Name: principal_contacts principal_contacts_touch_updated_at; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principal_contacts_touch_updated_at BEFORE UPDATE ON request_engine.principal_contacts FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: principals principals_guard_security_identity; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER principals_guard_security_identity BEFORE UPDATE ON request_engine.principals FOR EACH ROW EXECUTE FUNCTION request_engine.guard_principal_security_identity();


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
-- Name: representations representations_bump_principal_authority; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER representations_bump_principal_authority AFTER INSERT OR DELETE OR UPDATE ON request_engine.representations FOR EACH ROW EXECUTE FUNCTION request_engine.bump_principal_authority_from_representation();


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

CREATE TRIGGER resource_location_exceptions_bump_resource BEFORE INSERT OR DELETE OR UPDATE ON request_engine.resource_location_schedule_exceptions FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_from_assignment_child();


--
-- Name: resource_location_schedule_exceptions resource_location_exceptions_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_location_exceptions_touch BEFORE UPDATE ON request_engine.resource_location_schedule_exceptions FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: resource_public_profiles resource_public_profiles_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_public_profiles_revision_step BEFORE UPDATE ON request_engine.resource_public_profiles FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: resource_public_profiles resource_public_profiles_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resource_public_profiles_touch BEFORE UPDATE ON request_engine.resource_public_profiles FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: resources resources_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resources_bump_recovery_source_revision AFTER UPDATE OF availability_revision ON request_engine.resources FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_revision_recovery_sources();


--
-- Name: resources resources_guard_commitment_sensitive_change; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resources_guard_commitment_sensitive_change BEFORE UPDATE ON request_engine.resources FOR EACH ROW EXECUTE FUNCTION request_engine.guard_resource_commitment_sensitive_change();


--
-- Name: resources resources_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER resources_touch BEFORE UPDATE ON request_engine.resources FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: schedule_exceptions schedule_exceptions_bump_resource; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER schedule_exceptions_bump_resource BEFORE INSERT OR DELETE OR UPDATE ON request_engine.schedule_exceptions FOR EACH ROW EXECUTE FUNCTION request_engine.bump_resource_availability_revision();


--
-- Name: scheduled_actions scheduled_actions_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER scheduled_actions_touch BEFORE UPDATE ON request_engine.scheduled_actions FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: service_classification_authority_events service_classification_authority_events_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_classification_authority_events_append_only BEFORE DELETE OR UPDATE ON request_engine.service_classification_authority_events FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: service_classifications service_classifications_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_classifications_revision_step BEFORE UPDATE ON request_engine.service_classifications FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: service_classifications service_classifications_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_classifications_touch BEFORE UPDATE ON request_engine.service_classifications FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: service_queue_intake_controls service_queue_intake_controls_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_queue_intake_controls_bump_recovery_source_revision AFTER UPDATE OF accepting, reason, effective_until ON request_engine.service_queue_intake_controls FOR EACH ROW EXECUTE FUNCTION request_engine.bump_intake_control_recovery_source_revision();


--
-- Name: service_queues service_queues_initialize_intake_control; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_queues_initialize_intake_control AFTER INSERT ON request_engine.service_queues FOR EACH ROW EXECUTE FUNCTION request_engine.initialize_service_queue_intake_control();


--
-- Name: service_queues service_queues_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_queues_revision_step BEFORE UPDATE ON request_engine.service_queues FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: service_queues service_queues_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_queues_touch BEFORE UPDATE ON request_engine.service_queues FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: service_session_interruptions service_session_interruptions_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_session_interruptions_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.service_session_interruptions FOR EACH ROW EXECUTE FUNCTION request_engine.bump_interruption_recovery_source_revision();


--
-- Name: service_session_interruptions service_session_interruptions_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_session_interruptions_guard_transition BEFORE DELETE OR UPDATE ON request_engine.service_session_interruptions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_service_session_interruption_transition();


--
-- Name: service_sessions service_sessions_bump_recovery_source_revision; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_sessions_bump_recovery_source_revision AFTER INSERT OR DELETE OR UPDATE ON request_engine.service_sessions FOR EACH ROW EXECUTE FUNCTION request_engine.bump_service_session_recovery_source_revision();


--
-- Name: service_sessions service_sessions_guard_resource_occupation; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER service_sessions_guard_resource_occupation BEFORE INSERT OR UPDATE OF resource_id, status ON request_engine.service_sessions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_live_resource_occupation();


--
-- Name: service_sessions service_sessions_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

