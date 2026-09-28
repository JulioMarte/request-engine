    ADD CONSTRAINT slot_opportunities_organization_id_offering_version_id_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: slot_opportunities slot_opportunities_organization_id_source_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_organization_id_source_reservation_id_fkey FOREIGN KEY (organization_id, source_reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: staff_memberships staff_anchor_tenant_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_anchor_tenant_fk FOREIGN KEY (organization_id, authority_anchor_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: staff_memberships staff_binding_tenant_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_binding_tenant_fk FOREIGN KEY (organization_id, principal_id, identity_binding_id) REFERENCES request_engine.identity_bindings(organization_id, principal_id, id);


--
-- Name: staff_memberships staff_memberships_authority_anchor_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_authority_anchor_party_id_fkey FOREIGN KEY (authority_anchor_party_id) REFERENCES request_engine.parties(id);


--
-- Name: staff_memberships staff_memberships_established_by_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_established_by_principal_id_fkey FOREIGN KEY (established_by_principal_id) REFERENCES request_engine.principals(id);


--
-- Name: staff_memberships staff_memberships_identity_binding_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_identity_binding_id_fkey FOREIGN KEY (identity_binding_id) REFERENCES request_engine.identity_bindings(id);


--
-- Name: staff_memberships staff_memberships_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: staff_memberships staff_memberships_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_memberships_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES request_engine.principals(id);


--
-- Name: staff_memberships staff_principal_tenant_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.staff_memberships
    ADD CONSTRAINT staff_principal_tenant_fk FOREIGN KEY (organization_id, principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: waitlist_entries waitlist_entries_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.waitlist_entries
    ADD CONSTRAINT waitlist_entries_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: waitlist_entries waitlist_entries_organization_id_offering_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.waitlist_entries
    ADD CONSTRAINT waitlist_entries_organization_id_offering_id_fkey FOREIGN KEY (organization_id, offering_id) REFERENCES request_engine.offerings(organization_id, id);


--
-- Name: waitlist_entries waitlist_entries_organization_id_preferred_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.waitlist_entries
    ADD CONSTRAINT waitlist_entries_organization_id_preferred_resource_id_fkey FOREIGN KEY (organization_id, preferred_resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: waitlist_entries waitlist_entries_organization_id_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.waitlist_entries
    ADD CONSTRAINT waitlist_entries_organization_id_subject_party_id_fkey FOREIGN KEY (organization_id, subject_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: webauthn_challenges webauthn_challenges_native_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_native_identity_id_fkey FOREIGN KEY (native_identity_id) REFERENCES request_engine.native_identities(id);


--
-- Name: webauthn_challenges webauthn_challenges_setup_session_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_challenges
    ADD CONSTRAINT webauthn_challenges_setup_session_id_fkey FOREIGN KEY (setup_session_id) REFERENCES request_engine.setup_sessions(id);


--
-- Name: webauthn_credentials webauthn_credentials_native_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.webauthn_credentials
    ADD CONSTRAINT webauthn_credentials_native_identity_id_fkey FOREIGN KEY (native_identity_id) REFERENCES request_engine.native_identities(id);


--
-- Name: workload_credentials workload_credentials_workload_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.workload_credentials
    ADD CONSTRAINT workload_credentials_workload_identity_id_fkey FOREIGN KEY (workload_identity_id) REFERENCES request_engine.workload_identities(id);


--
-- Name: workload_identities workload_identities_identity_authority_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.workload_identities
    ADD CONSTRAINT workload_identities_identity_authority_id_fkey FOREIGN KEY (identity_authority_id) REFERENCES request_engine.identity_authorities(id);


--
-- Name: agent_budget_windows; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.agent_budget_windows ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_budget_windows agent_budget_windows_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY agent_budget_windows_tenant_isolation ON request_engine.agent_budget_windows USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: agent_policies; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.agent_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_policies agent_policies_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY agent_policies_tenant_isolation ON request_engine.agent_policies USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: agent_profiles; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.agent_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: agent_profiles agent_profiles_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY agent_profiles_tenant_isolation ON request_engine.agent_profiles USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: attendance_responses; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.attendance_responses ENABLE ROW LEVEL SECURITY;

--
-- Name: attendance_responses attendance_responses_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY attendance_responses_tenant_isolation ON request_engine.attendance_responses USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: audit_records; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.audit_records ENABLE ROW LEVEL SECURITY;

--
-- Name: audit_records audit_records_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY audit_records_tenant_isolation ON request_engine.audit_records USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: booking_context_terms; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.booking_context_terms ENABLE ROW LEVEL SECURITY;

--
-- Name: booking_context_terms booking_context_terms_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY booking_context_terms_tenant_policy ON request_engine.booking_context_terms USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: capacity_claims; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.capacity_claims ENABLE ROW LEVEL SECURITY;

--
-- Name: capacity_claims capacity_claims_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY capacity_claims_tenant_isolation ON request_engine.capacity_claims USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: capacity_holds; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.capacity_holds ENABLE ROW LEVEL SECURITY;

--
-- Name: capacity_holds capacity_holds_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY capacity_holds_tenant_isolation ON request_engine.capacity_holds USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: communication_deliveries; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.communication_deliveries ENABLE ROW LEVEL SECURITY;

--
-- Name: communication_deliveries communication_deliveries_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY communication_deliveries_tenant_isolation ON request_engine.communication_deliveries USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: communication_escalations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.communication_escalations ENABLE ROW LEVEL SECURITY;

--
-- Name: communication_escalations communication_escalations_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY communication_escalations_tenant_policy ON request_engine.communication_escalations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: communication_tasks; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.communication_tasks ENABLE ROW LEVEL SECURITY;

--
-- Name: communication_tasks communication_tasks_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY communication_tasks_tenant_isolation ON request_engine.communication_tasks USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: delegations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.delegations ENABLE ROW LEVEL SECURITY;

--
-- Name: delegations delegations_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY delegations_tenant_isolation ON request_engine.delegations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: discovery_booking_handoffs; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.discovery_booking_handoffs ENABLE ROW LEVEL SECURITY;

--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY discovery_booking_handoffs_tenant_policy ON request_engine.discovery_booking_handoffs USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: discovery_publications; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.discovery_publications ENABLE ROW LEVEL SECURITY;

--
-- Name: discovery_publications discovery_publications_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY discovery_publications_tenant_policy ON request_engine.discovery_publications USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: external_correlations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.external_correlations ENABLE ROW LEVEL SECURITY;

--
-- Name: external_correlations external_correlations_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY external_correlations_tenant_isolation ON request_engine.external_correlations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: idempotency_records; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.idempotency_records ENABLE ROW LEVEL SECURITY;

--
-- Name: idempotency_records idempotency_records_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY idempotency_records_tenant_isolation ON request_engine.idempotency_records USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: identity_bindings; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.identity_bindings ENABLE ROW LEVEL SECURITY;

--
-- Name: identity_bindings identity_bindings_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY identity_bindings_tenant_isolation ON request_engine.identity_bindings USING (((principal_plane = 'tenant'::text) AND (organization_id = request_engine.current_organization_id()))) WITH CHECK (((principal_plane = 'tenant'::text) AND (organization_id = request_engine.current_organization_id())));


--
-- Name: identity_exchange_candidates; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.identity_exchange_candidates ENABLE ROW LEVEL SECURITY;

--
-- Name: identity_exchange_candidates identity_exchange_candidates_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY identity_exchange_candidates_tenant_policy ON request_engine.identity_exchange_candidates USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: identity_link_facts; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.identity_link_facts ENABLE ROW LEVEL SECURITY;

--
-- Name: identity_link_facts identity_link_facts_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY identity_link_facts_tenant_isolation ON request_engine.identity_link_facts USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: identity_link_intents; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.identity_link_intents ENABLE ROW LEVEL SECURITY;

--
-- Name: identity_link_intents identity_link_intents_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY identity_link_intents_tenant_isolation ON request_engine.identity_link_intents USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: integration_governance_facts integration_facts_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY integration_facts_tenant_isolation ON request_engine.integration_governance_facts USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: integration_governance_facts; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.integration_governance_facts ENABLE ROW LEVEL SECURITY;

--
-- Name: live_capacity_projection_policies; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.live_capacity_projection_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_recovery_trigger_read; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY live_capacity_projection_policies_recovery_trigger_read ON request_engine.live_capacity_projection_policies FOR SELECT TO request_engine_schema_owner USING ((pg_trigger_depth() > 0));


--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY live_capacity_projection_policies_tenant_policy ON request_engine.live_capacity_projection_policies USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: live_capacity_workload_estimate_policies; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.live_capacity_workload_estimate_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estimate_policies_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY live_capacity_workload_estimate_policies_tenant_policy ON request_engine.live_capacity_workload_estimate_policies USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: location_hours_exceptions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.location_hours_exceptions ENABLE ROW LEVEL SECURITY;

--
-- Name: location_hours_exceptions location_hours_exceptions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY location_hours_exceptions_tenant_policy ON request_engine.location_hours_exceptions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: location_operational_hours; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.location_operational_hours ENABLE ROW LEVEL SECURITY;

--
-- Name: location_operational_hours location_operational_hours_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY location_operational_hours_tenant_policy ON request_engine.location_operational_hours USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: location_public_contact_endpoints; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.location_public_contact_endpoints ENABLE ROW LEVEL SECURITY;

--
-- Name: location_public_contact_endpoints location_public_contact_endpoints_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY location_public_contact_endpoints_tenant_policy ON request_engine.location_public_contact_endpoints USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: locations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.locations ENABLE ROW LEVEL SECURITY;

--
-- Name: locations locations_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY locations_tenant_isolation ON request_engine.locations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: offering_resource_requirements; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.offering_resource_requirements ENABLE ROW LEVEL SECURITY;

--
-- Name: offering_resource_requirements offering_resource_requirements_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY offering_resource_requirements_tenant_isolation ON request_engine.offering_resource_requirements USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: offering_service_classifications; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.offering_service_classifications ENABLE ROW LEVEL SECURITY;

--
-- Name: offering_service_classifications offering_service_classifications_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY offering_service_classifications_tenant_policy ON request_engine.offering_service_classifications USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: offering_version_booking_policies; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.offering_version_booking_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: offering_version_booking_policies offering_version_booking_policies_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY offering_version_booking_policies_tenant_isolation ON request_engine.offering_version_booking_policies USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: offering_version_booking_terms; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.offering_version_booking_terms ENABLE ROW LEVEL SECURITY;

--
-- Name: offering_version_booking_terms offering_version_booking_terms_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY offering_version_booking_terms_tenant_policy ON request_engine.offering_version_booking_terms USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: offering_versions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.offering_versions ENABLE ROW LEVEL SECURITY;

--
-- Name: offering_versions offering_versions_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY offering_versions_tenant_isolation ON request_engine.offering_versions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: offerings; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.offerings ENABLE ROW LEVEL SECURITY;

--
-- Name: offerings offerings_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY offerings_tenant_isolation ON request_engine.offerings USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_recovery_actions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_recovery_actions ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_recovery_actions operational_recovery_actions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_recovery_actions_tenant_policy ON request_engine.operational_recovery_actions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_recovery_autonomy_policies; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_recovery_autonomy_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_recovery_autonomy_policies operational_recovery_autonomy_policies_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_recovery_autonomy_policies_tenant_policy ON request_engine.operational_recovery_autonomy_policies USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_recovery_escalations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_recovery_escalations ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_recovery_escalations operational_recovery_escalations_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_recovery_escalations_tenant_policy ON request_engine.operational_recovery_escalations USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_recovery_executions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_recovery_executions ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_recovery_executions operational_recovery_executions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_recovery_executions_tenant_policy ON request_engine.operational_recovery_executions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_recovery_incidents; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_recovery_incidents ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_recovery_incidents operational_recovery_incidents_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_recovery_incidents_tenant_policy ON request_engine.operational_recovery_incidents USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_recovery_proposals; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_recovery_proposals ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_recovery_proposals operational_recovery_proposals_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_recovery_proposals_tenant_policy ON request_engine.operational_recovery_proposals USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: operational_workload_classifications; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.operational_workload_classifications ENABLE ROW LEVEL SECURITY;

--
-- Name: operational_workload_classifications operational_workload_classifications_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY operational_workload_classifications_tenant_policy ON request_engine.operational_workload_classifications USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: organization_channel_policies; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organization_channel_policies ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_channel_policies organization_channel_policies_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organization_channel_policies_tenant_isolation ON request_engine.organization_channel_policies USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: organization_party_bindings; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organization_party_bindings ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_party_bindings organization_party_bindings_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organization_party_bindings_tenant_policy ON request_engine.organization_party_bindings USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: organization_provisioning_facts; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organization_provisioning_facts ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_provisioning_facts organization_provisioning_facts_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organization_provisioning_facts_tenant_isolation ON request_engine.organization_provisioning_facts USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: organization_public_contact_endpoints; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organization_public_contact_endpoints ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_public_contact_endpoints organization_public_contact_endpoints_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organization_public_contact_endpoints_tenant_policy ON request_engine.organization_public_contact_endpoints USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: organization_root_provisioning_facts; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organization_root_provisioning_facts ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_root_provisioning_facts organization_root_provisioning_facts_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organization_root_provisioning_facts_tenant_isolation ON request_engine.organization_root_provisioning_facts USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: organizations; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organizations ENABLE ROW LEVEL SECURITY;

--
-- Name: organizations organizations_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organizations_tenant_isolation ON request_engine.organizations USING ((id = request_engine.current_organization_id())) WITH CHECK ((id = request_engine.current_organization_id()));


--
-- Name: outbox_messages; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.outbox_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: outbox_messages outbox_messages_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY outbox_messages_tenant_isolation ON request_engine.outbox_messages USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: parties; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.parties ENABLE ROW LEVEL SECURITY;

--
-- Name: parties parties_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY parties_tenant_isolation ON request_engine.parties USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: party_administrative_identifiers; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.party_administrative_identifiers ENABLE ROW LEVEL SECURITY;

--
-- Name: party_administrative_identifiers party_administrative_identifiers_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY party_administrative_identifiers_tenant_policy ON request_engine.party_administrative_identifiers USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: party_contact_points; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.party_contact_points ENABLE ROW LEVEL SECURITY;

--
-- Name: party_contact_points party_contact_points_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY party_contact_points_tenant_isolation ON request_engine.party_contact_points USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: party_identity_documents; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.party_identity_documents ENABLE ROW LEVEL SECURITY;

--
-- Name: party_identity_documents party_identity_documents_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY party_identity_documents_tenant_policy ON request_engine.party_identity_documents USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: party_identity_revisions; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.party_identity_revisions ENABLE ROW LEVEL SECURITY;

--
-- Name: party_identity_revisions party_identity_revisions_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY party_identity_revisions_tenant_policy ON request_engine.party_identity_revisions USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: principal_authority_grants; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.principal_authority_grants ENABLE ROW LEVEL SECURITY;

--
-- Name: principal_authority_grants principal_authority_grants_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY principal_authority_grants_tenant_isolation ON request_engine.principal_authority_grants USING (((principal_plane = 'tenant'::text) AND (organization_id = request_engine.current_organization_id()))) WITH CHECK (((principal_plane = 'tenant'::text) AND (organization_id = request_engine.current_organization_id())));


--
-- Name: principal_contacts; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.principal_contacts ENABLE ROW LEVEL SECURITY;

--
-- Name: principal_contacts principal_contacts_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY principal_contacts_tenant_policy ON request_engine.principal_contacts USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: principals; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.principals ENABLE ROW LEVEL SECURITY;

--
-- Name: principals principals_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY principals_tenant_isolation ON request_engine.principals USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


--
-- Name: provider_events; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.provider_events ENABLE ROW LEVEL SECURITY;

--
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
-- Name: staff_memberships; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.staff_memberships ENABLE ROW LEVEL SECURITY;

--
-- Name: staff_memberships staff_memberships_tenant_isolation; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY staff_memberships_tenant_isolation ON request_engine.staff_memberships USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


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
-- Name: SCHEMA request_auth; Type: ACL; Schema: -; Owner: request_engine_schema_owner
--

GRANT USAGE ON SCHEMA request_auth TO request_engine_app;
GRANT USAGE ON SCHEMA request_auth TO request_platform_control_definer;
GRANT USAGE ON SCHEMA request_auth TO request_platform_definer;
GRANT USAGE ON SCHEMA request_auth TO request_engine_worker;


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
GRANT USAGE ON SCHEMA request_engine TO request_platform_definer;
GRANT USAGE ON SCHEMA request_engine TO request_bootstrap_definer;
GRANT USAGE ON SCHEMA request_engine TO request_platform_control_definer;


--
-- Name: SCHEMA request_platform; Type: ACL; Schema: -; Owner: request_engine_schema_owner
--

GRANT USAGE ON SCHEMA request_platform TO request_platform_definer;
GRANT USAGE ON SCHEMA request_platform TO request_bootstrap_definer;
GRANT USAGE ON SCHEMA request_platform TO request_platform_control;
GRANT USAGE ON SCHEMA request_platform TO request_platform_control_definer;
GRANT USAGE ON SCHEMA request_platform TO request_engine_worker;
GRANT USAGE ON SCHEMA request_platform TO request_engine_app;


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
-- Name: FUNCTION activate_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_secret_reference text, p_secret_digest text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.activate_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_secret_reference text, p_secret_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.activate_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_secret_reference text, p_secret_digest text) TO request_engine_worker;


--
-- Name: FUNCTION claim_native_recovery_delivery_requests(p_limit integer, p_lease_seconds integer); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.claim_native_recovery_delivery_requests(p_limit integer, p_lease_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.claim_native_recovery_delivery_requests(p_limit integer, p_lease_seconds integer) TO request_engine_worker;


--
-- Name: FUNCTION complete_native_recovery(p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.complete_native_recovery(p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.complete_native_recovery(p_native_identity_id uuid) TO request_engine_app;


--
-- Name: FUNCTION complete_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_outcome text, p_error_class text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.complete_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.complete_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) TO request_engine_worker;


--
-- Name: FUNCTION consume_native_recovery_intent(p_recovery_id uuid, p_token_digest bytea, p_new_credential_id uuid, p_new_verifier text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.consume_native_recovery_intent(p_recovery_id uuid, p_token_digest bytea, p_new_credential_id uuid, p_new_verifier text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.consume_native_recovery_intent(p_recovery_id uuid, p_token_digest bytea, p_new_credential_id uuid, p_new_verifier text) TO request_engine_app;


--
-- Name: FUNCTION consume_recovery_code(p_code_digest bytea); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.consume_recovery_code(p_code_digest bytea) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.consume_recovery_code(p_code_digest bytea) TO request_engine_app;


--
-- Name: FUNCTION consume_recovery_code_and_rotate_password(p_code_digest bytea, p_new_credential_id uuid, p_new_verifier text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.consume_recovery_code_and_rotate_password(p_code_digest bytea, p_new_credential_id uuid, p_new_verifier text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.consume_recovery_code_and_rotate_password(p_code_digest bytea, p_new_credential_id uuid, p_new_verifier text) TO request_engine_app;


--
-- Name: FUNCTION create_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_verifier text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.create_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_verifier text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.create_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_verifier text) TO request_engine_app;


--
-- Name: FUNCTION create_native_recovery_intent(p_native_identity_id uuid, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.create_native_recovery_intent(p_native_identity_id uuid, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.create_native_recovery_intent(p_native_identity_id uuid, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) TO request_engine_app;
GRANT ALL ON FUNCTION request_auth.create_native_recovery_intent(p_native_identity_id uuid, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) TO request_platform_control_definer;


--
-- Name: FUNCTION create_native_recovery_intent_for_verified_address(p_identity_authority_id uuid, p_login_handle text, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.create_native_recovery_intent_for_verified_address(p_identity_authority_id uuid, p_login_handle text, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) FROM PUBLIC;


--
-- Name: FUNCTION create_native_session(p_native_identity_id uuid, p_credential_id uuid, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.create_native_session(p_native_identity_id uuid, p_credential_id uuid, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.create_native_session(p_native_identity_id uuid, p_credential_id uuid, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) TO request_engine_app;


--
-- Name: FUNCTION create_recovery_code_set(p_set_id uuid, p_native_identity_id uuid, p_setup_session_id uuid, p_code_digests bytea[]); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.create_recovery_code_set(p_set_id uuid, p_native_identity_id uuid, p_setup_session_id uuid, p_code_digests bytea[]) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.create_recovery_code_set(p_set_id uuid, p_native_identity_id uuid, p_setup_session_id uuid, p_code_digests bytea[]) TO request_engine_app;


--
-- Name: FUNCTION create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.create_webauthn_challenge(p_challenge_id uuid, p_purpose text, p_native_identity_id uuid, p_session_id uuid, p_setup_session_id uuid, p_challenge_digest bytea, p_expires_at timestamp with time zone) TO request_engine_app;


--
-- Name: FUNCTION disable_native_identity(p_native_identity_id uuid, p_reason text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.disable_native_identity(p_native_identity_id uuid, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.disable_native_identity(p_native_identity_id uuid, p_reason text) TO request_engine_app;


--
-- Name: FUNCTION finalize_setup_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_setup_session_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.finalize_setup_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_setup_session_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.finalize_setup_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_setup_session_id uuid) TO request_engine_app;


--
-- Name: FUNCTION finalize_webauthn_authentication(p_challenge_digest bytea, p_credential_row_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.finalize_webauthn_authentication(p_challenge_digest bytea, p_credential_row_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.finalize_webauthn_authentication(p_challenge_digest bytea, p_credential_row_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean, p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) TO request_engine_app;


--
-- Name: FUNCTION finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.finalize_webauthn_registration(p_challenge_digest bytea, p_credential_row_id uuid, p_credential_id_bytes bytea, p_public_key bytea, p_sign_count bigint, p_aaguid text, p_backup_eligible boolean, p_backup_state boolean, p_user_verified boolean) TO request_engine_app;


--
-- Name: FUNCTION finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.finalize_webauthn_step_up(p_challenge_digest bytea, p_credential_row_id uuid, p_session_id uuid, p_native_identity_id uuid, p_sign_count bigint, p_backup_eligible boolean, p_user_verified boolean) TO request_engine_app;


--
-- Name: FUNCTION is_native_authority_ready(p_authority_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.is_native_authority_ready(p_authority_id uuid) TO request_engine_app;


--
-- Name: FUNCTION lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.lock_credentialed_native_identity(p_identity_authority_id uuid, p_native_identity_id uuid) TO request_platform_control_definer;


--
-- Name: FUNCTION prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.prepare_native_recovery_address(p_address_id uuid, p_native_identity_id uuid, p_kind text, p_normalized_address text, p_verification_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone) TO request_engine_app;


--
-- Name: FUNCTION promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.promote_recovery_code_set(p_set_id uuid, p_native_identity_id uuid) TO request_engine_app;


--
-- Name: FUNCTION queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.queue_native_verified_recovery(p_identity_authority_id uuid, p_login_handle text, p_request_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_active_webauthn_identity(p_identity_authority_id uuid, p_login_handle text) TO request_engine_app;


--
-- Name: FUNCTION read_native_credential_verifier(p_credential_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_native_credential_verifier(p_credential_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_native_credential_verifier(p_credential_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_native_password_credential(p_identity_authority_id uuid, p_login_handle text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_native_password_credential(p_identity_authority_id uuid, p_login_handle text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_native_password_credential(p_identity_authority_id uuid, p_login_handle text) TO request_engine_app;


--
-- Name: FUNCTION read_native_recovery_addresses(p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_native_recovery_addresses(p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_native_recovery_addresses(p_native_identity_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_native_recovery_readiness(p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_native_recovery_readiness(p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_native_recovery_readiness(p_native_identity_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_native_session(p_session_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_native_session(p_session_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_native_session(p_session_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_oidc_authorities(); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_oidc_authorities() FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_oidc_authorities() TO request_engine_app;


--
-- Name: FUNCTION read_platform_identity_bindings(p_identity_authority_id uuid, p_subject_id text); Type: ACL; Schema: request_auth; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_auth.read_platform_identity_bindings(p_identity_authority_id uuid, p_subject_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_platform_identity_bindings(p_identity_authority_id uuid, p_subject_id text) TO request_engine_app;


--
-- Name: FUNCTION read_recovery_code_set_summary(p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_recovery_code_set_summary(p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_recovery_code_set_summary(p_native_identity_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_webauthn_challenge(p_challenge_digest bytea, p_purpose text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_webauthn_challenge(p_challenge_digest bytea, p_purpose text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_webauthn_challenge(p_challenge_digest bytea, p_purpose text) TO request_engine_app;


--
-- Name: FUNCTION read_webauthn_credential(p_credential_id_bytes bytea); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_webauthn_credential(p_credential_id_bytes bytea) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_webauthn_credential(p_credential_id_bytes bytea) TO request_engine_app;


--
-- Name: FUNCTION read_webauthn_credentials(p_native_identity_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_webauthn_credentials(p_native_identity_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_webauthn_credentials(p_native_identity_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_workload_credential(p_credential_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.read_workload_credential(p_credential_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.read_workload_credential(p_credential_id uuid) TO request_engine_app;


--
-- Name: FUNCTION reauthenticate_native_session(p_session_id uuid, p_credential_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.reauthenticate_native_session(p_session_id uuid, p_credential_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.reauthenticate_native_session(p_session_id uuid, p_credential_id uuid) TO request_engine_app;


--
-- Name: FUNCTION rehash_native_password_verifier(p_credential_id uuid, p_native_identity_id uuid, p_new_verifier text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.rehash_native_password_verifier(p_credential_id uuid, p_native_identity_id uuid, p_new_verifier text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.rehash_native_password_verifier(p_credential_id uuid, p_native_identity_id uuid, p_new_verifier text) TO request_engine_app;


--
-- Name: FUNCTION renew_native_recovery_delivery_request_lease(p_request_id uuid, p_claim_token uuid, p_extension_seconds integer); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.renew_native_recovery_delivery_request_lease(p_request_id uuid, p_claim_token uuid, p_extension_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.renew_native_recovery_delivery_request_lease(p_request_id uuid, p_claim_token uuid, p_extension_seconds integer) TO request_engine_worker;


--
-- Name: FUNCTION retry_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.retry_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.retry_native_recovery_delivery_request(p_request_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) TO request_engine_worker;


--
-- Name: FUNCTION revoke_native_recovery_address(p_native_identity_id uuid, p_recovery_address_id uuid); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.revoke_native_recovery_address(p_native_identity_id uuid, p_recovery_address_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.revoke_native_recovery_address(p_native_identity_id uuid, p_recovery_address_id uuid) TO request_engine_app;


--
-- Name: FUNCTION revoke_native_session(p_native_identity_id uuid, p_session_id uuid, p_reason text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.revoke_native_session(p_native_identity_id uuid, p_session_id uuid, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.revoke_native_session(p_native_identity_id uuid, p_session_id uuid, p_reason text) TO request_engine_app;


--
-- Name: FUNCTION revoke_native_sessions(p_native_identity_id uuid, p_reason text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.revoke_native_sessions(p_native_identity_id uuid, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.revoke_native_sessions(p_native_identity_id uuid, p_reason text) TO request_engine_app;


--
-- Name: FUNCTION revoke_recovery_code_set(p_set_id uuid, p_reason text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.revoke_recovery_code_set(p_set_id uuid, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.revoke_recovery_code_set(p_set_id uuid, p_reason text) TO request_engine_app;


--
-- Name: FUNCTION revoke_webauthn_credential(p_credential_id uuid, p_native_identity_id uuid, p_reason text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.revoke_webauthn_credential(p_credential_id uuid, p_native_identity_id uuid, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.revoke_webauthn_credential(p_credential_id uuid, p_native_identity_id uuid, p_reason text) TO request_engine_app;


--
-- Name: FUNCTION rotate_native_password(p_native_identity_id uuid, p_expected_credential_id uuid, p_new_credential_id uuid, p_new_verifier text, p_reason text); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.rotate_native_password(p_native_identity_id uuid, p_expected_credential_id uuid, p_new_credential_id uuid, p_new_verifier text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.rotate_native_password(p_native_identity_id uuid, p_expected_credential_id uuid, p_new_credential_id uuid, p_new_verifier text, p_reason text) TO request_engine_app;


--
-- Name: FUNCTION touch_native_session(p_session_id uuid, p_min_interval_seconds integer); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.touch_native_session(p_session_id uuid, p_min_interval_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.touch_native_session(p_session_id uuid, p_min_interval_seconds integer) TO request_engine_app;


--
-- Name: FUNCTION verify_native_recovery_address(p_verification_id uuid, p_token_digest bytea); Type: ACL; Schema: request_auth; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_auth.verify_native_recovery_address(p_verification_id uuid, p_token_digest bytea) FROM PUBLIC;
GRANT ALL ON FUNCTION request_auth.verify_native_recovery_address(p_verification_id uuid, p_token_digest bytea) TO request_engine_app;


--
-- Name: FUNCTION acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, p_capability text, p_idempotency_key text, p_request_fingerprint text) TO request_engine_app;


--
-- Name: FUNCTION assert_integration_manager(p_capability text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.assert_integration_manager(p_capability text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.assert_integration_manager(p_capability text) TO request_engine_app;


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
-- Name: FUNCTION rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.rotate_integration_credential(p_principal_id uuid, p_expected_revision bigint, p_credential_id uuid, p_digest bytea, p_fingerprint text, p_expires_at timestamp with time zone, p_reference text) TO request_engine_app;


--
-- Name: FUNCTION schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.schedule_recovery_reassessment(p_organization_id uuid, p_service_queue_id uuid, p_revision bigint) TO request_engine_app;


--
-- Name: FUNCTION acquire_identity_topology_exclusive(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.acquire_identity_topology_exclusive() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.acquire_identity_topology_exclusive() TO request_platform_control_definer;
GRANT ALL ON FUNCTION request_engine.acquire_identity_topology_exclusive() TO request_bootstrap_definer;


--
-- Name: FUNCTION acquire_identity_topology_share(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.acquire_identity_topology_share() FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.acquire_identity_topology_share() TO request_platform_control_definer;
GRANT ALL ON FUNCTION request_engine.acquire_identity_topology_share() TO request_bootstrap_definer;


--
-- Name: FUNCTION adopt_platform_owner_v3(); Type: ACL; Schema: request_engine; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_engine.adopt_platform_owner_v3() FROM PUBLIC;


--
-- Name: FUNCTION append_integration_fact(p_principal_id uuid, p_actor_id uuid, p_operation text, p_reference text, p_capability text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.append_integration_fact(p_principal_id uuid, p_actor_id uuid, p_operation text, p_reference text, p_capability text) FROM PUBLIC;


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
-- Name: FUNCTION assert_organization_has_controller(p_organization_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_organization_has_controller(p_organization_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.assert_organization_has_controller(p_organization_id uuid) TO request_platform_control_definer;


--
-- Name: FUNCTION assert_other_tenant_controller(p_excluded_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_other_tenant_controller(p_excluded_principal_id uuid) FROM PUBLIC;


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
-- Name: FUNCTION assert_staff_manager(p_capability text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_staff_manager(p_capability text) FROM PUBLIC;


--
-- Name: FUNCTION assert_tenant_has_controller(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_tenant_has_controller() FROM PUBLIC;


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

