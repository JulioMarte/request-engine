-- Name: provider_events provider_events_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY provider_events_tenant_isolation ON request_engine.provider_events USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: queue_entries; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.queue_entries ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_entries queue_entries_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY queue_entries_tenant_isolation ON request_engine.queue_entries USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: queue_entry_operator_selections; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.queue_entry_operator_selections ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_entry_operator_selections queue_entry_operator_selections_tenant; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY queue_entry_operator_selections_tenant ON request_engine.queue_entry_operator_selections USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: queue_entry_recall_holds; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.queue_entry_recall_holds ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_entry_recall_holds queue_entry_recall_holds_tenant; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY queue_entry_recall_holds_tenant ON request_engine.queue_entry_recall_holds USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: queue_entry_skips; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.queue_entry_skips ENABLE ROW LEVEL SECURITY;

--
-- Name: queue_entry_skips queue_entry_skips_tenant; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY queue_entry_skips_tenant ON request_engine.queue_entry_skips USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: recovery_source_revisions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.recovery_source_revisions ENABLE ROW LEVEL SECURITY;

--
-- Name: recovery_source_revisions recovery_source_revisions_internal_writer_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY recovery_source_revisions_internal_writer_policy ON request_engine.recovery_source_revisions TO request_engine_schema_owner USING ((pg_trigger_depth() > 0)) WITH CHECK ((pg_trigger_depth() > 0));


--
-- Name: recovery_source_revisions recovery_source_revisions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY recovery_source_revisions_tenant_policy ON request_engine.recovery_source_revisions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reminder_acknowledgements; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reminder_acknowledgements ENABLE ROW LEVEL SECURITY;

--
-- Name: reminder_acknowledgements reminder_acknowledgements_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reminder_acknowledgements_tenant_isolation ON request_engine.reminder_acknowledgements USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reminder_plans; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reminder_plans ENABLE ROW LEVEL SECURITY;

--
-- Name: reminder_plans reminder_plans_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reminder_plans_tenant_isolation ON request_engine.reminder_plans USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: representations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.representations ENABLE ROW LEVEL SECURITY;

--
-- Name: representations representations_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY representations_tenant_isolation ON request_engine.representations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: request_definition_versions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.request_definition_versions ENABLE ROW LEVEL SECURITY;

--
-- Name: request_definition_versions request_definition_versions_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY request_definition_versions_tenant_isolation ON request_engine.request_definition_versions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: request_definitions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.request_definitions ENABLE ROW LEVEL SECURITY;

--
-- Name: request_definitions request_definitions_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY request_definitions_tenant_isolation ON request_engine.request_definitions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: request_participants; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.request_participants ENABLE ROW LEVEL SECURITY;

--
-- Name: request_participants request_participants_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY request_participants_tenant_isolation ON request_engine.request_participants USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: requests; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.requests ENABLE ROW LEVEL SECURITY;

--
-- Name: requests requests_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY requests_tenant_isolation ON request_engine.requests USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reservation_access; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reservation_access ENABLE ROW LEVEL SECURITY;

--
-- Name: reservation_access reservation_access_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reservation_access_tenant_isolation ON request_engine.reservation_access USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reservation_arrival_estimates; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reservation_arrival_estimates ENABLE ROW LEVEL SECURITY;

--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reservation_arrival_estimates_tenant_policy ON request_engine.reservation_arrival_estimates USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reservation_attendance; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reservation_attendance ENABLE ROW LEVEL SECURITY;

--
-- Name: reservation_attendance reservation_attendance_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reservation_attendance_tenant_isolation ON request_engine.reservation_attendance USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reservation_commercial_commitment_context_terms; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reservation_commercial_commitment_context_terms ENABLE ROW LEVEL SECURITY;

--
-- Name: reservation_commercial_commitment_context_terms reservation_commercial_commitment_context_terms_tenant_isolatio; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reservation_commercial_commitment_context_terms_tenant_isolatio ON request_engine.reservation_commercial_commitment_context_terms USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reservation_commercial_commitments; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reservation_commercial_commitments ENABLE ROW LEVEL SECURITY;

--
-- Name: reservation_commercial_commitments reservation_commercial_commitments_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reservation_commercial_commitments_tenant_policy ON request_engine.reservation_commercial_commitments USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: reservations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.reservations ENABLE ROW LEVEL SECURITY;

--
-- Name: reservations reservations_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY reservations_tenant_isolation ON request_engine.reservations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_activities; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_activities ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_activities resource_activities_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_activities_tenant_policy ON request_engine.resource_activities USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_capabilities; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_capabilities ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_capabilities resource_capabilities_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_capabilities_tenant_isolation ON request_engine.resource_capabilities USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_capability_assignments; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_capability_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_capability_assignments resource_capability_assignments_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_capability_assignments_tenant_isolation ON request_engine.resource_capability_assignments USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_location_assignments; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_location_assignments ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_location_assignments resource_location_assignments_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_location_assignments_tenant_policy ON request_engine.resource_location_assignments USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_location_availability; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_location_availability ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_location_availability resource_location_availability_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_location_availability_tenant_policy ON request_engine.resource_location_availability USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_location_schedule_exceptions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_location_schedule_exceptions ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_location_schedule_exceptions resource_location_schedule_exceptions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_location_schedule_exceptions_tenant_policy ON request_engine.resource_location_schedule_exceptions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resource_public_profiles; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resource_public_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: resource_public_profiles resource_public_profiles_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resource_public_profiles_tenant_policy ON request_engine.resource_public_profiles USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: resources; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.resources ENABLE ROW LEVEL SECURITY;

--
-- Name: resources resources_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY resources_tenant_isolation ON request_engine.resources USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: schedule_exceptions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.schedule_exceptions ENABLE ROW LEVEL SECURITY;

--
-- Name: schedule_exceptions schedule_exceptions_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY schedule_exceptions_tenant_isolation ON request_engine.schedule_exceptions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: scheduled_actions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.scheduled_actions ENABLE ROW LEVEL SECURITY;

--
-- Name: scheduled_actions scheduled_actions_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY scheduled_actions_tenant_isolation ON request_engine.scheduled_actions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: service_queue_intake_controls; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.service_queue_intake_controls ENABLE ROW LEVEL SECURITY;

--
-- Name: service_queue_intake_controls service_queue_intake_controls_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY service_queue_intake_controls_tenant_policy ON request_engine.service_queue_intake_controls USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: service_queue_intake_controls service_queue_intake_controls_trigger_writer_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY service_queue_intake_controls_trigger_writer_policy ON request_engine.service_queue_intake_controls FOR INSERT TO request_engine_schema_owner WITH CHECK ((pg_trigger_depth() > 0));


--
-- Name: service_queues; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.service_queues ENABLE ROW LEVEL SECURITY;

--
-- Name: service_queues service_queues_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY service_queues_tenant_isolation ON request_engine.service_queues USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: service_session_interruptions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.service_session_interruptions ENABLE ROW LEVEL SECURITY;

--
-- Name: service_session_interruptions service_session_interruptions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY service_session_interruptions_tenant_policy ON request_engine.service_session_interruptions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: service_sessions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.service_sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: service_sessions service_sessions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY service_sessions_tenant_policy ON request_engine.service_sessions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: shared_capacity_bindings; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.shared_capacity_bindings ENABLE ROW LEVEL SECURITY;

--
-- Name: shared_capacity_bindings shared_capacity_bindings_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY shared_capacity_bindings_tenant_isolation ON request_engine.shared_capacity_bindings USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: slot_offers; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.slot_offers ENABLE ROW LEVEL SECURITY;

--
-- Name: slot_offers slot_offers_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY slot_offers_tenant_isolation ON request_engine.slot_offers USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: slot_opportunities; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.slot_opportunities ENABLE ROW LEVEL SECURITY;

--
-- Name: slot_opportunities slot_opportunities_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY slot_opportunities_tenant_isolation ON request_engine.slot_opportunities USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: waitlist_entries; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.waitlist_entries ENABLE ROW LEVEL SECURITY;

--
-- Name: waitlist_entries waitlist_entries_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY waitlist_entries_tenant_isolation ON request_engine.waitlist_entries USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: SCHEMA request_admin; Type: ACL; Schema: -; Owner: request_engine_schema_owner
--

GRANT USAGE ON SCHEMA request_admin TO request_engine_admin;


--
-- Name: SCHEMA request_cmd; Type: ACL; Schema: -; Owner: request_engine_schema_owner
--

GRANT USAGE ON SCHEMA request_cmd TO request_engine_app;
GRANT USAGE ON SCHEMA request_cmd TO request_engine_worker;
GRANT USAGE ON SCHEMA request_cmd TO request_engine_admin;


--
-- Name: SCHEMA request_engine; Type: ACL; Schema: -; Owner: request_engine_schema_owner
--

GRANT USAGE ON SCHEMA request_engine TO request_engine_app;
GRANT USAGE ON SCHEMA request_engine TO request_engine_worker;
GRANT USAGE ON SCHEMA request_engine TO request_engine_admin;
GRANT USAGE ON SCHEMA request_engine TO request_engine_discovery;
GRANT USAGE ON SCHEMA request_engine TO request_engine_discovery_definer;


--
-- Name: SCHEMA request_read; Type: ACL; Schema: -; Owner: request_engine_schema_owner
--

GRANT USAGE ON SCHEMA request_read TO request_engine_app;
GRANT USAGE ON SCHEMA request_read TO request_engine_admin;


--
-- Name: FUNCTION activate_shared_capacity_binding(p_organization_id uuid, p_resource_id uuid, p_shared_capacity_identity_id uuid, p_authority_ref text, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.activate_shared_capacity_binding(p_organization_id uuid, p_resource_id uuid, p_shared_capacity_identity_id uuid, p_authority_ref text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.activate_shared_capacity_binding(p_organization_id uuid, p_resource_id uuid, p_shared_capacity_identity_id uuid, p_authority_ref text, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION create_global_identity(p_identity_kind text, p_evidence_ref text, p_authority_ref text, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.create_global_identity(p_identity_kind text, p_evidence_ref text, p_authority_ref text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.create_global_identity(p_identity_kind text, p_evidence_ref text, p_authority_ref text, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION create_service_classification(p_classification_key text, p_canonical_name text, p_authority_ref text, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.create_service_classification(p_classification_key text, p_canonical_name text, p_authority_ref text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.create_service_classification(p_classification_key text, p_canonical_name text, p_authority_ref text, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION create_shared_capacity_identity(p_global_identity_id uuid, p_authority_ref text, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.create_shared_capacity_identity(p_global_identity_id uuid, p_authority_ref text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.create_shared_capacity_identity(p_global_identity_id uuid, p_authority_ref text, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION replay_dead_outbox_message(p_organization_id uuid, p_message_id uuid, p_additional_attempts integer, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.replay_dead_outbox_message(p_organization_id uuid, p_message_id uuid, p_additional_attempts integer, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.replay_dead_outbox_message(p_organization_id uuid, p_message_id uuid, p_additional_attempts integer, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION replay_dead_scheduled_action(p_organization_id uuid, p_action_id uuid, p_additional_attempts integer, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.replay_dead_scheduled_action(p_organization_id uuid, p_action_id uuid, p_additional_attempts integer, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.replay_dead_scheduled_action(p_organization_id uuid, p_action_id uuid, p_additional_attempts integer, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION replay_provider_event(p_organization_id uuid, p_provider_event_row_id uuid, p_additional_attempts integer, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.replay_provider_event(p_organization_id uuid, p_provider_event_row_id uuid, p_additional_attempts integer, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.replay_provider_event(p_organization_id uuid, p_provider_event_row_id uuid, p_additional_attempts integer, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION retire_service_classification(p_service_classification_id uuid, p_expected_revision bigint, p_authority_ref text, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.retire_service_classification(p_service_classification_id uuid, p_expected_revision bigint, p_authority_ref text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.retire_service_classification(p_service_classification_id uuid, p_expected_revision bigint, p_authority_ref text, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION revoke_shared_capacity_binding(p_binding_id uuid, p_authority_ref text, p_reason text); Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_admin.revoke_shared_capacity_binding(p_binding_id uuid, p_authority_ref text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_admin.revoke_shared_capacity_binding(p_binding_id uuid, p_authority_ref text, p_reason text) TO request_engine_admin;


--
-- Name: FUNCTION acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) TO request_engine_app;


--
-- Name: FUNCTION cancel_scheduled_action(p_organization_id uuid, p_action_id uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) TO request_engine_app;
GRANT ALL ON FUNCTION request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid) TO request_engine_admin;


--
-- Name: FUNCTION claim_outbox_messages(p_limit integer, p_lease interval); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.claim_outbox_messages(p_limit integer, p_lease interval) TO request_engine_admin;


--
-- Name: FUNCTION claim_provider_events(p_limit integer, p_lease interval); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.claim_provider_events(p_limit integer, p_lease interval) TO request_engine_admin;


--
-- Name: FUNCTION claim_scheduled_actions(p_limit integer, p_lease interval); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.claim_scheduled_actions(p_limit integer, p_lease interval) TO request_engine_admin;


--
-- Name: FUNCTION complete_idempotency(p_idempotency_id uuid, p_result_data jsonb); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb) TO request_engine_app;


--
-- Name: FUNCTION complete_outbox_message(p_message_id uuid, p_claim_token uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.complete_outbox_message(p_message_id uuid, p_claim_token uuid) TO request_engine_admin;


--
-- Name: FUNCTION complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.complete_provider_event(p_provider_event_row_id uuid, p_claim_token uuid) TO request_engine_admin;


--
-- Name: FUNCTION complete_scheduled_action(p_action_id uuid, p_claim_token uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.complete_scheduled_action(p_action_id uuid, p_claim_token uuid) TO request_engine_admin;


--
-- Name: FUNCTION dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.dead_letter_outbox_message(p_message_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.dead_letter_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.dead_letter_scheduled_action(p_action_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION find_recovery_sweep_scopes(p_limit integer); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.find_recovery_sweep_scopes(p_limit integer) TO request_engine_admin;


--
-- Name: FUNCTION lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) TO request_engine_app;
GRANT ALL ON FUNCTION request_cmd.lock_outbox_message_claim(p_organization_id uuid, p_message_id uuid, p_claim_token uuid) TO request_engine_admin;


--
-- Name: FUNCTION lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) TO request_engine_app;
GRANT ALL ON FUNCTION request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) TO request_engine_admin;


--
-- Name: FUNCTION lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) TO request_engine_app;
GRANT ALL ON FUNCTION request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid) TO request_engine_worker;


--
-- Name: FUNCTION lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) TO request_engine_app;
GRANT ALL ON FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) TO request_engine_admin;


--
-- Name: FUNCTION mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, p_queue_entry_id uuid, p_completed_at timestamp with time zone) TO request_engine_app;


--
-- Name: FUNCTION mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.mark_queue_entry_service_started(p_organization_id uuid, p_queue_entry_id uuid, p_started_at timestamp with time zone) TO request_engine_app;


--
-- Name: FUNCTION reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.reject_provider_event(p_provider_event_row_id uuid, p_claim_token uuid, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.renew_outbox_message_lease(p_message_id uuid, p_claim_token uuid, p_extension interval) TO request_engine_admin;


--
-- Name: FUNCTION renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.renew_provider_event_lease(p_provider_event_row_id uuid, p_claim_token uuid, p_extension interval) TO request_engine_admin;


--
-- Name: FUNCTION renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.renew_scheduled_action_lease(p_action_id uuid, p_claim_token uuid, p_extension interval) TO request_engine_admin;


--
-- Name: FUNCTION retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.retry_outbox_message(p_message_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.retry_outbox_message_after(p_message_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.retry_provider_event_after(p_provider_event_row_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.retry_scheduled_action(p_action_id uuid, p_claim_token uuid, p_next_attempt_at timestamp with time zone, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_cmd.retry_scheduled_action_after(p_action_id uuid, p_claim_token uuid, p_delay interval, p_error_class text) TO request_engine_admin;


--
-- Name: FUNCTION schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) TO request_engine_app;


--
-- Name: FUNCTION assert_arrival_estimate_reservation_confirmed(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_arrival_estimate_reservation_confirmed() FROM PUBLIC;


--
-- Name: FUNCTION assert_hold_claim_completeness(p_org uuid, p_hold uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_hold_claim_completeness(p_org uuid, p_hold uuid) FROM PUBLIC;


--
-- Name: FUNCTION assert_offered_slot_offer_source_consistency(p_organization_id uuid, p_slot_offer_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_offered_slot_offer_source_consistency(p_organization_id uuid, p_slot_offer_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION assert_reservation_claim_completeness(p_org uuid, p_reservation uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_reservation_claim_completeness(p_org uuid, p_reservation uuid) FROM PUBLIC;


--
-- Name: FUNCTION assert_service_queue_coherence(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_service_queue_coherence() FROM PUBLIC;


--
-- Name: FUNCTION assert_session_interruption_coherence(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_session_interruption_coherence() FROM PUBLIC;


--
-- Name: FUNCTION assert_slot_offer_consistency(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_slot_offer_consistency() FROM PUBLIC;


--
-- Name: FUNCTION attach_shared_capacity_claim_link(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.attach_shared_capacity_claim_link() FROM PUBLIC;


--
-- Name: FUNCTION bind_consumed_identity_candidate_v1(p_candidate_id uuid, p_party_id uuid, p_consent_fields text[], p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bind_consumed_identity_candidate_v1(p_candidate_id uuid, p_party_id uuid, p_consent_fields text[], p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.bind_consumed_identity_candidate_v1(p_candidate_id uuid, p_party_id uuid, p_consent_fields text[], p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION bump_capacity_claim_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_capacity_claim_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_direct_queue_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_direct_queue_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_estimate_policy_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_estimate_policy_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_intake_control_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_intake_control_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_interruption_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_interruption_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_location_operational_revision_from_child(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_location_operational_revision_from_child() FROM PUBLIC;


--
-- Name: FUNCTION bump_location_revision_recovery_sources(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_location_revision_recovery_sources() FROM PUBLIC;


--
-- Name: FUNCTION bump_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION bump_reservation_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_reservation_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_resource_activity_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_resource_activity_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_resource_availability_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_resource_availability_revision() FROM PUBLIC;


--
-- Name: FUNCTION bump_resource_from_assignment(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_resource_from_assignment() FROM PUBLIC;


--
-- Name: FUNCTION bump_resource_from_assignment_child(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_resource_from_assignment_child() FROM PUBLIC;


--
-- Name: FUNCTION bump_resource_revision_recovery_sources(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_resource_revision_recovery_sources() FROM PUBLIC;


--
-- Name: FUNCTION bump_service_session_recovery_source_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_service_session_recovery_source_revision() FROM PUBLIC;


--
-- Name: FUNCTION check_capacity_owner_completeness(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.check_capacity_owner_completeness() FROM PUBLIC;


--
-- Name: FUNCTION check_offered_slot_offer_source_consistency(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.check_offered_slot_offer_source_consistency() FROM PUBLIC;


--
-- Name: FUNCTION consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION current_authenticated_principal_id(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.current_authenticated_principal_id() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.current_authenticated_principal_id() TO request_engine_app;
GRANT ALL ON FUNCTION request_engine.current_authenticated_principal_id() TO request_engine_worker;
GRANT ALL ON FUNCTION request_engine.current_authenticated_principal_id() TO request_engine_admin;


--
-- Name: FUNCTION current_correlation_id(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.current_correlation_id() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.current_correlation_id() TO request_engine_app;
GRANT ALL ON FUNCTION request_engine.current_correlation_id() TO request_engine_worker;
GRANT ALL ON FUNCTION request_engine.current_correlation_id() TO request_engine_admin;


--
-- Name: FUNCTION current_organization_id(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.current_organization_id() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.current_organization_id() TO request_engine_app;
GRANT ALL ON FUNCTION request_engine.current_organization_id() TO request_engine_worker;
GRANT ALL ON FUNCTION request_engine.current_organization_id() TO request_engine_admin;
GRANT ALL ON FUNCTION request_engine.current_organization_id() TO request_engine_discovery_definer;


--
-- Name: FUNCTION guard_booking_context_terms_scope(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_booking_context_terms_scope() FROM PUBLIC;


--
-- Name: FUNCTION guard_capacity_claim(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim() FROM PUBLIC;


--
-- Name: FUNCTION guard_capacity_claim_contextual_assignment(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_contextual_assignment() FROM PUBLIC;


--
-- Name: FUNCTION guard_capacity_claim_replacement_provenance(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_replacement_provenance() FROM PUBLIC;


--
-- Name: FUNCTION guard_capacity_claim_tenant_context(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_tenant_context() FROM PUBLIC;


--
-- Name: FUNCTION guard_capacity_claim_terminal_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_capacity_claim_terminal_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_capacity_hold_provenance_update(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_capacity_hold_provenance_update() FROM PUBLIC;


--
-- Name: FUNCTION guard_communication_escalations(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_communication_escalations() FROM PUBLIC;


--
-- Name: FUNCTION guard_discovery_handoff_latest_version(); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.guard_discovery_handoff_latest_version() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.guard_discovery_handoff_latest_version() TO request_engine_schema_owner;
GRANT ALL ON FUNCTION request_engine.guard_discovery_handoff_latest_version() TO request_engine_admin;


--
-- Name: FUNCTION guard_discovery_handoff_reservation(); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.guard_discovery_handoff_reservation() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.guard_discovery_handoff_reservation() TO request_engine_schema_owner;
GRANT ALL ON FUNCTION request_engine.guard_discovery_handoff_reservation() TO request_engine_admin;


--
-- Name: FUNCTION guard_exact_revision_step(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_exact_revision_step() FROM PUBLIC;


--
-- Name: FUNCTION guard_f2_mapping_lifecycle(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_f2_mapping_lifecycle() FROM PUBLIC;


--
-- Name: FUNCTION guard_f2_publication_broad_specific_overlap(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_f2_publication_broad_specific_overlap() FROM PUBLIC;


--
-- Name: FUNCTION guard_f2_publication_lifecycle(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_f2_publication_lifecycle() FROM PUBLIC;


--
-- Name: FUNCTION guard_hold_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_hold_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_linked_capacity_claim_provenance(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_linked_capacity_claim_provenance() FROM PUBLIC;


--
-- Name: FUNCTION guard_live_capacity_projection_policy(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_live_capacity_projection_policy() FROM PUBLIC;


--
-- Name: FUNCTION guard_live_capacity_workload_estimate_policy(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_live_capacity_workload_estimate_policy() FROM PUBLIC;


--
-- Name: FUNCTION guard_live_resource_occupation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_live_resource_occupation() FROM PUBLIC;


--
-- Name: FUNCTION guard_location_operational_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_location_operational_revision() FROM PUBLIC;


--
-- Name: FUNCTION guard_operational_recovery_escalation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_operational_recovery_escalation() FROM PUBLIC;


--
-- Name: FUNCTION guard_operational_recovery_execution(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_operational_recovery_execution() FROM PUBLIC;


--
-- Name: FUNCTION guard_operational_recovery_proposal(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_operational_recovery_proposal() FROM PUBLIC;


--
-- Name: FUNCTION guard_operational_workload_classification(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_operational_workload_classification() FROM PUBLIC;


--
-- Name: FUNCTION guard_party_administrative_identifier_facts(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_party_administrative_identifier_facts() FROM PUBLIC;


--
-- Name: FUNCTION guard_party_contact_point_verification(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_party_contact_point_verification() FROM PUBLIC;


--
-- Name: FUNCTION guard_party_identity_documents(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_party_identity_documents() FROM PUBLIC;


--
-- Name: FUNCTION guard_party_identity_revisions(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_party_identity_revisions() FROM PUBLIC;


--
-- Name: FUNCTION guard_party_kind_immutable(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_party_kind_immutable() FROM PUBLIC;


--
-- Name: FUNCTION guard_person_shared_capacity_cardinality(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_person_shared_capacity_cardinality() FROM PUBLIC;


--
-- Name: FUNCTION guard_principal_contacts(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_principal_contacts() FROM PUBLIC;


--
-- Name: FUNCTION guard_promoted_capacity_claim_owner(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_promoted_capacity_claim_owner() FROM PUBLIC;


--
-- Name: FUNCTION guard_queue_entry_recall_hold(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_queue_entry_recall_hold() FROM PUBLIC;


--
-- Name: FUNCTION guard_queue_entry_skip(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_queue_entry_skip() FROM PUBLIC;


--
-- Name: FUNCTION guard_queue_entry_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_queue_entry_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_reminder_plan_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_reminder_plan_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_request_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_request_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_reservation_arrival_estimate(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_reservation_arrival_estimate() FROM PUBLIC;


--
-- Name: FUNCTION guard_reservation_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_reservation_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_resource_activity_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_resource_activity_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_resource_commitment_sensitive_change(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_resource_commitment_sensitive_change() FROM PUBLIC;


--
-- Name: FUNCTION guard_resource_location_assignment(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_resource_location_assignment() FROM PUBLIC;


--
-- Name: FUNCTION guard_service_session_interruption_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_service_session_interruption_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_service_session_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_service_session_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_shared_capacity_binding(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_shared_capacity_binding() FROM PUBLIC;


--
-- Name: FUNCTION guard_shared_capacity_rebinding(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_shared_capacity_rebinding() FROM PUBLIC;


--
-- Name: FUNCTION guard_slot_offer_live_hold(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_slot_offer_live_hold() FROM PUBLIC;


--
-- Name: FUNCTION guard_slot_offer_provenance_update(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_slot_offer_provenance_update() FROM PUBLIC;


--
-- Name: FUNCTION guard_slot_offer_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_slot_offer_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_slot_opportunity_provenance_update(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_slot_opportunity_provenance_update() FROM PUBLIC;


--
-- Name: FUNCTION guard_slot_opportunity_transition(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_slot_opportunity_transition() FROM PUBLIC;


--
-- Name: FUNCTION guard_waitlist_entry_provenance_update(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_waitlist_entry_provenance_update() FROM PUBLIC;


--
-- Name: FUNCTION has_active_discovery_mapping(p_classification_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.has_active_discovery_mapping(p_classification_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.has_active_discovery_mapping(p_classification_id uuid) TO request_engine_schema_owner;
GRANT ALL ON FUNCTION request_engine.has_active_discovery_mapping(p_classification_id uuid) TO request_engine_admin;


--
-- Name: FUNCTION identity_exchange_country_code_v1(p_code text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.identity_exchange_country_code_v1(p_code text) FROM PUBLIC;


--
-- Name: FUNCTION identity_exchange_existing_party_v1(p_candidate_id uuid, p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.identity_exchange_existing_party_v1(p_candidate_id uuid, p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.identity_exchange_existing_party_v1(p_candidate_id uuid, p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION identity_exchange_identifier_valid_v1(p_kind text, p_authority text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.identity_exchange_identifier_valid_v1(p_kind text, p_authority text) FROM PUBLIC;


--
-- Name: FUNCTION identity_exchange_subject_kind_v1(p_kind text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.identity_exchange_subject_kind_v1(p_kind text) FROM PUBLIC;


--
-- Name: FUNCTION initialize_queue_entry_times(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.initialize_queue_entry_times() FROM PUBLIC;


--
-- Name: FUNCTION initialize_service_queue_intake_control(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.initialize_service_queue_intake_control() FROM PUBLIC;


--
-- Name: FUNCTION issue_discovery_booking_handoff(p_token_hash text, p_publication_id uuid, p_expected_publication_revision bigint, p_mapping_id uuid, p_expected_mapping_revision bigint, p_offering_version_id uuid, p_location_id uuid, p_selection jsonb, p_expires_at timestamp with time zone); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.issue_discovery_booking_handoff(p_token_hash text, p_publication_id uuid, p_expected_publication_revision bigint, p_mapping_id uuid, p_expected_mapping_revision bigint, p_offering_version_id uuid, p_location_id uuid, p_selection jsonb, p_expires_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.issue_discovery_booking_handoff(p_token_hash text, p_publication_id uuid, p_expected_publication_revision bigint, p_mapping_id uuid, p_expected_mapping_revision bigint, p_offering_version_id uuid, p_location_id uuid, p_selection jsonb, p_expires_at timestamp with time zone) TO request_engine_discovery;
GRANT ALL ON FUNCTION request_engine.issue_discovery_booking_handoff(p_token_hash text, p_publication_id uuid, p_expected_publication_revision bigint, p_mapping_id uuid, p_expected_mapping_revision bigint, p_offering_version_id uuid, p_location_id uuid, p_selection jsonb, p_expires_at timestamp with time zone) TO request_engine_admin;


--
-- Name: FUNCTION lock_booking_context_terms_resource(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.lock_booking_context_terms_resource() FROM PUBLIC;


--
-- Name: FUNCTION lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) TO request_engine_app;
GRANT ALL ON FUNCTION request_engine.lock_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) TO request_engine_admin;


--
-- Name: FUNCTION lock_offering_version_booking_terms_root(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.lock_offering_version_booking_terms_root() FROM PUBLIC;


--
-- Name: FUNCTION lookup_active_service_classification(p_key text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.lookup_active_service_classification(p_key text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.lookup_active_service_classification(p_key text) TO request_engine_app;


--
-- Name: FUNCTION lookup_service_classification(p_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.lookup_service_classification(p_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.lookup_service_classification(p_id uuid) TO request_engine_app;


--
-- Name: FUNCTION publish_portable_party_v1(p_party_id uuid, p_kind text, p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.publish_portable_party_v1(p_party_id uuid, p_kind text, p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.publish_portable_party_v1(p_party_id uuid, p_kind text, p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_discovery_booking_handoff(p_token_hash text); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text) TO request_engine_app;
GRANT ALL ON FUNCTION request_engine.read_discovery_booking_handoff(p_token_hash text) TO request_engine_admin;


--
-- Name: FUNCTION reject_immutable_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_immutable_mutation() FROM PUBLIC;


--
-- Name: FUNCTION reject_queue_entry_operator_selection_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_queue_entry_operator_selection_mutation() FROM PUBLIC;


--
-- Name: FUNCTION require_trusted_actor_context(p_organization_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.require_trusted_actor_context(p_organization_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) TO request_engine_app;
GRANT ALL ON FUNCTION request_engine.resolve_current_party_authority(p_organization_id uuid, p_principal_id uuid, p_represented_party_id uuid, p_scope_key text) TO request_engine_admin;


--
-- Name: FUNCTION search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) TO request_engine_discovery;
GRANT ALL ON FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) TO request_engine_admin;


--
-- Name: FUNCTION stamp_shared_capacity_authority_event_context(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.stamp_shared_capacity_authority_event_context() FROM PUBLIC;


--
-- Name: FUNCTION touch_updated_at(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.touch_updated_at() FROM PUBLIC;


--
-- Name: FUNCTION validate_offering_version_delivery_policy(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.validate_offering_version_delivery_policy() FROM PUBLIC;


--
-- Name: FUNCTION recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid); Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) TO request_engine_app;
GRANT ALL ON FUNCTION request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid) TO request_engine_admin;


--
-- Name: TABLE outbox_messages; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.outbox_messages TO request_engine_app;
GRANT ALL ON TABLE request_engine.outbox_messages TO request_engine_admin;


--
-- Name: TABLE provider_events; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.provider_events TO request_engine_app;
GRANT ALL ON TABLE request_engine.provider_events TO request_engine_admin;


--
-- Name: TABLE scheduled_actions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.scheduled_actions TO request_engine_app;
GRANT ALL ON TABLE request_engine.scheduled_actions TO request_engine_admin;


--
-- Name: TABLE worker_dead_letters_v1; Type: ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_admin.worker_dead_letters_v1 TO request_engine_admin;


--
-- Name: TABLE attendance_responses; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.attendance_responses TO request_engine_app;
GRANT ALL ON TABLE request_engine.attendance_responses TO request_engine_admin;


--
-- Name: TABLE audit_records; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.audit_records TO request_engine_app;
GRANT ALL ON TABLE request_engine.audit_records TO request_engine_admin;


--
-- Name: TABLE booking_context_terms; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.booking_context_terms TO request_engine_app;
GRANT ALL ON TABLE request_engine.booking_context_terms TO request_engine_admin;


--
-- Name: TABLE capacity_claims; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.capacity_claims TO request_engine_app;
GRANT ALL ON TABLE request_engine.capacity_claims TO request_engine_admin;


--
-- Name: TABLE capacity_holds; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.capacity_holds TO request_engine_app;
GRANT ALL ON TABLE request_engine.capacity_holds TO request_engine_admin;


--
-- Name: TABLE communication_deliveries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.communication_deliveries TO request_engine_app;
GRANT ALL ON TABLE request_engine.communication_deliveries TO request_engine_admin;


--
-- Name: TABLE communication_escalations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.communication_escalations TO request_engine_app;
GRANT ALL ON TABLE request_engine.communication_escalations TO request_engine_admin;


--
-- Name: TABLE communication_tasks; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.communication_tasks TO request_engine_app;
GRANT ALL ON TABLE request_engine.communication_tasks TO request_engine_admin;


--
-- Name: TABLE discovery_booking_handoffs; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.discovery_booking_handoffs TO request_engine_admin;
GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.discovery_booking_handoffs TO request_engine_discovery_definer;


--
-- Name: TABLE discovery_publications; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.discovery_publications TO request_engine_app;
GRANT ALL ON TABLE request_engine.discovery_publications TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.discovery_publications TO request_engine_discovery_definer;


--
-- Name: COLUMN discovery_publications.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(id) ON TABLE request_engine.discovery_publications TO request_engine_discovery_definer;


--
-- Name: TABLE external_correlations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.external_correlations TO request_engine_app;
GRANT ALL ON TABLE request_engine.external_correlations TO request_engine_admin;


--
-- Name: TABLE global_identities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.global_identities TO request_engine_admin;


--
-- Name: TABLE idempotency_records; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.idempotency_records TO request_engine_app;
GRANT ALL ON TABLE request_engine.idempotency_records TO request_engine_admin;


--
-- Name: TABLE identity_exchange_candidates; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.identity_exchange_candidates TO request_engine_admin;


--
-- Name: TABLE live_capacity_projection_policies; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.live_capacity_projection_policies TO request_engine_app;
GRANT ALL ON TABLE request_engine.live_capacity_projection_policies TO request_engine_admin;


--
-- Name: TABLE live_capacity_workload_estimate_policies; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.live_capacity_workload_estimate_policies TO request_engine_app;
GRANT ALL ON TABLE request_engine.live_capacity_workload_estimate_policies TO request_engine_admin;


--
-- Name: TABLE location_hours_exceptions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.location_hours_exceptions TO request_engine_app;
GRANT ALL ON TABLE request_engine.location_hours_exceptions TO request_engine_admin;


--
-- Name: TABLE location_operational_hours; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.location_operational_hours TO request_engine_app;
GRANT ALL ON TABLE request_engine.location_operational_hours TO request_engine_admin;


--
-- Name: TABLE location_public_contact_endpoints; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.location_public_contact_endpoints TO request_engine_app;
GRANT ALL ON TABLE request_engine.location_public_contact_endpoints TO request_engine_admin;


--
-- Name: TABLE locations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.locations TO request_engine_app;
GRANT ALL ON TABLE request_engine.locations TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.locations TO request_engine_discovery_definer;


--
-- Name: TABLE offering_resource_requirements; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.offering_resource_requirements TO request_engine_app;
GRANT ALL ON TABLE request_engine.offering_resource_requirements TO request_engine_admin;


--
-- Name: TABLE offering_service_classifications; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.offering_service_classifications TO request_engine_app;
GRANT ALL ON TABLE request_engine.offering_service_classifications TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.offering_service_classifications TO request_engine_discovery_definer;


--
-- Name: COLUMN offering_service_classifications.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(id) ON TABLE request_engine.offering_service_classifications TO request_engine_discovery_definer;


--
-- Name: TABLE offering_version_booking_policies; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.offering_version_booking_policies TO request_engine_app;
GRANT ALL ON TABLE request_engine.offering_version_booking_policies TO request_engine_admin;


--
-- Name: TABLE offering_version_booking_terms; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.offering_version_booking_terms TO request_engine_app;
GRANT ALL ON TABLE request_engine.offering_version_booking_terms TO request_engine_admin;


--
-- Name: TABLE offering_versions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.offering_versions TO request_engine_app;
GRANT ALL ON TABLE request_engine.offering_versions TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.offering_versions TO request_engine_discovery_definer;


--
-- Name: TABLE offerings; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.offerings TO request_engine_app;
GRANT ALL ON TABLE request_engine.offerings TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.offerings TO request_engine_discovery_definer;


--
-- Name: COLUMN offerings.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(id) ON TABLE request_engine.offerings TO request_engine_discovery_definer;


--
-- Name: TABLE operational_recovery_actions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.operational_recovery_actions TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_recovery_actions TO request_engine_admin;


--
-- Name: TABLE operational_recovery_autonomy_policies; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.operational_recovery_autonomy_policies TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_recovery_autonomy_policies TO request_engine_admin;


--
-- Name: TABLE operational_recovery_escalations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.operational_recovery_escalations TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_recovery_escalations TO request_engine_admin;


--
-- Name: TABLE operational_recovery_executions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.operational_recovery_executions TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_recovery_executions TO request_engine_admin;


--
-- Name: COLUMN operational_recovery_executions.resulting_reservation_revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(resulting_reservation_revision) ON TABLE request_engine.operational_recovery_executions TO request_engine_app;


--
-- Name: COLUMN operational_recovery_executions.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(status) ON TABLE request_engine.operational_recovery_executions TO request_engine_app;


--
-- Name: COLUMN operational_recovery_executions.failure_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(failure_code) ON TABLE request_engine.operational_recovery_executions TO request_engine_app;


--
-- Name: COLUMN operational_recovery_executions.communication_task_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(communication_task_id) ON TABLE request_engine.operational_recovery_executions TO request_engine_app;


--
-- Name: COLUMN operational_recovery_executions.completed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(completed_at) ON TABLE request_engine.operational_recovery_executions TO request_engine_app;


--
-- Name: TABLE operational_recovery_incidents; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.operational_recovery_incidents TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_recovery_incidents TO request_engine_admin;


--
-- Name: TABLE operational_recovery_proposals; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.operational_recovery_proposals TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_recovery_proposals TO request_engine_admin;


--
-- Name: TABLE operational_workload_classifications; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.operational_workload_classifications TO request_engine_app;
GRANT ALL ON TABLE request_engine.operational_workload_classifications TO request_engine_admin;


--
-- Name: TABLE organization_channel_policies; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.organization_channel_policies TO request_engine_app;
GRANT ALL ON TABLE request_engine.organization_channel_policies TO request_engine_admin;


--
-- Name: TABLE organization_party_bindings; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.organization_party_bindings TO request_engine_admin;


--
-- Name: TABLE organization_public_contact_endpoints; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.organization_public_contact_endpoints TO request_engine_app;
GRANT ALL ON TABLE request_engine.organization_public_contact_endpoints TO request_engine_admin;


--
-- Name: TABLE organizations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.organizations TO request_engine_app;
GRANT ALL ON TABLE request_engine.organizations TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.organizations TO request_engine_discovery_definer;


--
-- Name: TABLE parties; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.parties TO request_engine_app;
GRANT ALL ON TABLE request_engine.parties TO request_engine_admin;


--
-- Name: TABLE party_administrative_identifiers; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.party_administrative_identifiers TO request_engine_app;
GRANT ALL ON TABLE request_engine.party_administrative_identifiers TO request_engine_admin;


--
-- Name: TABLE party_contact_points; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.party_contact_points TO request_engine_app;
GRANT ALL ON TABLE request_engine.party_contact_points TO request_engine_admin;


--
-- Name: TABLE party_identity_documents; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.party_identity_documents TO request_engine_app;
GRANT ALL ON TABLE request_engine.party_identity_documents TO request_engine_admin;


--
-- Name: TABLE party_identity_revisions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.party_identity_revisions TO request_engine_app;
GRANT ALL ON TABLE request_engine.party_identity_revisions TO request_engine_admin;


--
-- Name: TABLE portable_party_identifiers; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.portable_party_identifiers TO request_engine_admin;


--
-- Name: TABLE portable_party_identities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.portable_party_identities TO request_engine_admin;


--
-- Name: TABLE portable_party_profiles; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.portable_party_profiles TO request_engine_admin;


--
-- Name: TABLE principal_contacts; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.principal_contacts TO request_engine_app;
GRANT ALL ON TABLE request_engine.principal_contacts TO request_engine_admin;


--
-- Name: TABLE principals; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.principals TO request_engine_app;
GRANT ALL ON TABLE request_engine.principals TO request_engine_admin;


--
-- Name: TABLE queue_entries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.queue_entries TO request_engine_app;
GRANT ALL ON TABLE request_engine.queue_entries TO request_engine_admin;


--
-- Name: TABLE queue_entry_operator_selections; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.queue_entry_operator_selections TO request_engine_app;
GRANT ALL ON TABLE request_engine.queue_entry_operator_selections TO request_engine_admin;


--
-- Name: TABLE queue_entry_recall_holds; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.queue_entry_recall_holds TO request_engine_app;
GRANT ALL ON TABLE request_engine.queue_entry_recall_holds TO request_engine_admin;


--
-- Name: COLUMN queue_entry_recall_holds.released_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(released_at) ON TABLE request_engine.queue_entry_recall_holds TO request_engine_app;


--
-- Name: COLUMN queue_entry_recall_holds.release_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(release_kind) ON TABLE request_engine.queue_entry_recall_holds TO request_engine_app;


--
-- Name: TABLE queue_entry_skips; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.queue_entry_skips TO request_engine_app;
GRANT ALL ON TABLE request_engine.queue_entry_skips TO request_engine_admin;


--
-- Name: COLUMN queue_entry_skips.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(consumed_at) ON TABLE request_engine.queue_entry_skips TO request_engine_app;


--
-- Name: COLUMN queue_entry_skips.consumed_by_entry_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(consumed_by_entry_id) ON TABLE request_engine.queue_entry_skips TO request_engine_app;


--
-- Name: TABLE recovery_source_revisions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.recovery_source_revisions TO request_engine_admin;


--
-- Name: TABLE reminder_acknowledgements; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.reminder_acknowledgements TO request_engine_app;
GRANT ALL ON TABLE request_engine.reminder_acknowledgements TO request_engine_admin;


--
-- Name: TABLE reminder_plans; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.reminder_plans TO request_engine_app;
GRANT ALL ON TABLE request_engine.reminder_plans TO request_engine_admin;


--
-- Name: TABLE representations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.representations TO request_engine_app;
GRANT ALL ON TABLE request_engine.representations TO request_engine_admin;


--
-- Name: TABLE request_definition_versions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.request_definition_versions TO request_engine_app;
GRANT ALL ON TABLE request_engine.request_definition_versions TO request_engine_admin;


--
-- Name: TABLE request_definitions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.request_definitions TO request_engine_app;
GRANT ALL ON TABLE request_engine.request_definitions TO request_engine_admin;


--
-- Name: TABLE request_participants; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.request_participants TO request_engine_app;
GRANT ALL ON TABLE request_engine.request_participants TO request_engine_admin;


--
-- Name: TABLE requests; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.requests TO request_engine_app;
GRANT ALL ON TABLE request_engine.requests TO request_engine_admin;


--
-- Name: TABLE reservation_access; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.reservation_access TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservation_access TO request_engine_admin;


--
-- Name: TABLE reservation_arrival_estimates; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.reservation_arrival_estimates TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservation_arrival_estimates TO request_engine_admin;


--
-- Name: TABLE reservation_attendance; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.reservation_attendance TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservation_attendance TO request_engine_admin;


--
-- Name: TABLE reservation_commercial_commitment_context_terms; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.reservation_commercial_commitment_context_terms TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservation_commercial_commitment_context_terms TO request_engine_admin;


--
-- Name: TABLE reservation_commercial_commitments; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.reservation_commercial_commitments TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservation_commercial_commitments TO request_engine_admin;


--
-- Name: TABLE reservations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.reservations TO request_engine_app;
GRANT ALL ON TABLE request_engine.reservations TO request_engine_admin;


--
-- Name: TABLE resource_activities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resource_activities TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_activities TO request_engine_admin;


--
-- Name: TABLE resource_capabilities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resource_capabilities TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_capabilities TO request_engine_admin;


--
-- Name: TABLE resource_capability_assignments; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resource_capability_assignments TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_capability_assignments TO request_engine_admin;


--
-- Name: TABLE resource_location_assignments; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resource_location_assignments TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_location_assignments TO request_engine_admin;


--
-- Name: TABLE resource_location_availability; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE request_engine.resource_location_availability TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_location_availability TO request_engine_admin;


--
-- Name: TABLE resource_location_schedule_exceptions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resource_location_schedule_exceptions TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_location_schedule_exceptions TO request_engine_admin;


--
-- Name: TABLE resource_public_profiles; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resource_public_profiles TO request_engine_app;
GRANT ALL ON TABLE request_engine.resource_public_profiles TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.resource_public_profiles TO request_engine_discovery_definer;


--
-- Name: TABLE resources; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.resources TO request_engine_app;
GRANT ALL ON TABLE request_engine.resources TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.resources TO request_engine_discovery_definer;


--
-- Name: TABLE schedule_exceptions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.schedule_exceptions TO request_engine_app;
GRANT ALL ON TABLE request_engine.schedule_exceptions TO request_engine_admin;


--
-- Name: TABLE service_classification_authority_events; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.service_classification_authority_events TO request_engine_admin;


--
-- Name: TABLE service_classifications; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,REFERENCES,TRIGGER,MAINTAIN ON TABLE request_engine.service_classifications TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.service_classifications TO request_engine_discovery_definer;


--
-- Name: TABLE service_queue_intake_controls; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.service_queue_intake_controls TO request_engine_app;
GRANT ALL ON TABLE request_engine.service_queue_intake_controls TO request_engine_admin;


--
-- Name: TABLE service_queues; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.service_queues TO request_engine_app;
GRANT ALL ON TABLE request_engine.service_queues TO request_engine_admin;


--
-- Name: TABLE service_session_interruptions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.service_session_interruptions TO request_engine_app;
GRANT ALL ON TABLE request_engine.service_session_interruptions TO request_engine_admin;


--
-- Name: TABLE service_sessions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.service_sessions TO request_engine_app;
GRANT ALL ON TABLE request_engine.service_sessions TO request_engine_admin;


--
-- Name: TABLE shared_capacity_authority_events; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.shared_capacity_authority_events TO request_engine_admin;


--
-- Name: TABLE shared_capacity_bindings; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.shared_capacity_bindings TO request_engine_admin;


--
-- Name: TABLE shared_capacity_claim_links; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.shared_capacity_claim_links TO request_engine_admin;


--
-- Name: TABLE shared_capacity_identities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.shared_capacity_identities TO request_engine_admin;


--
-- Name: TABLE slot_offers; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.slot_offers TO request_engine_app;
GRANT ALL ON TABLE request_engine.slot_offers TO request_engine_admin;


--
-- Name: TABLE slot_opportunities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.slot_opportunities TO request_engine_app;
GRANT ALL ON TABLE request_engine.slot_opportunities TO request_engine_admin;


--
-- Name: TABLE waitlist_entries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.waitlist_entries TO request_engine_app;
GRANT ALL ON TABLE request_engine.waitlist_entries TO request_engine_admin;


--
-- Name: TABLE business_info_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.business_info_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.business_info_v1 TO request_engine_admin;


--
-- Name: TABLE service_queue_status_v2; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.service_queue_status_v2 TO request_engine_app;
GRANT SELECT ON TABLE request_read.service_queue_status_v2 TO request_engine_admin;


--
-- Name: TABLE live_service_staff_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.live_service_staff_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.live_service_staff_v1 TO request_engine_admin;


--
-- Name: TABLE locations_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.locations_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.locations_v1 TO request_engine_admin;


--
-- Name: TABLE reservation_access_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.reservation_access_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.reservation_access_v1 TO request_engine_admin;


--
-- Name: TABLE reservation_day_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.reservation_day_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.reservation_day_v1 TO request_engine_admin;


--
-- Name: TABLE reservation_status_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.reservation_status_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.reservation_status_v1 TO request_engine_admin;


--
-- Name: TABLE service_session_status_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.service_session_status_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.service_session_status_v1 TO request_engine_admin;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: request_admin; Owner: request_engine_schema_owner
--

ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner IN SCHEMA request_admin GRANT SELECT ON TABLES TO request_engine_admin;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner IN SCHEMA request_engine GRANT ALL ON TABLES TO request_engine_admin;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: request_read; Owner: request_engine_schema_owner
--

ALTER DEFAULT PRIVILEGES FOR ROLE request_engine_schema_owner IN SCHEMA request_read GRANT SELECT ON TABLES TO request_engine_admin;


--
-- PostgreSQL database dump complete
--


