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

CREATE TRIGGER service_sessions_guard_transition BEFORE UPDATE ON request_engine.service_sessions FOR EACH ROW EXECUTE FUNCTION request_engine.guard_service_session_transition();


--
-- Name: service_sessions service_sessions_interruption_coherence; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER service_sessions_interruption_coherence AFTER INSERT OR UPDATE ON request_engine.service_sessions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.assert_session_interruption_coherence();


--
-- Name: service_sessions service_sessions_queue_entry_coherence; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER service_sessions_queue_entry_coherence AFTER INSERT OR UPDATE ON request_engine.service_sessions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.assert_service_queue_coherence();


--
-- Name: shared_capacity_authority_events shared_capacity_authority_events_00_stamp_context; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_authority_events_00_stamp_context BEFORE INSERT ON request_engine.shared_capacity_authority_events FOR EACH ROW EXECUTE FUNCTION request_engine.stamp_shared_capacity_authority_event_context();


--
-- Name: shared_capacity_authority_events shared_capacity_authority_events_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_authority_events_append_only BEFORE DELETE OR UPDATE ON request_engine.shared_capacity_authority_events FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: shared_capacity_bindings shared_capacity_bindings_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_bindings_guard BEFORE UPDATE ON request_engine.shared_capacity_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.guard_shared_capacity_binding();


--
-- Name: shared_capacity_bindings shared_capacity_bindings_guard_rebinding; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_bindings_guard_rebinding BEFORE INSERT ON request_engine.shared_capacity_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.guard_shared_capacity_rebinding();


--
-- Name: shared_capacity_bindings shared_capacity_bindings_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_bindings_touch BEFORE UPDATE ON request_engine.shared_capacity_bindings FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: shared_capacity_claim_links shared_capacity_claim_links_append_only; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_claim_links_append_only BEFORE DELETE OR UPDATE ON request_engine.shared_capacity_claim_links FOR EACH ROW EXECUTE FUNCTION request_engine.reject_immutable_mutation();


--
-- Name: shared_capacity_identities shared_capacity_identities_guard_person_cardinality; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER shared_capacity_identities_guard_person_cardinality BEFORE INSERT OR UPDATE OF global_identity_id, status ON request_engine.shared_capacity_identities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_person_shared_capacity_cardinality();


--
-- Name: capacity_holds slot_offer_holds_consistency_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER slot_offer_holds_consistency_guard AFTER UPDATE OF status, expires_at, during, offering_version_id, subject_party_id, location_id ON request_engine.capacity_holds DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.assert_slot_offer_consistency();


--
-- Name: slot_offers slot_offers_consistency_guard; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER slot_offers_consistency_guard AFTER INSERT OR UPDATE ON request_engine.slot_offers DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.assert_slot_offer_consistency();


--
-- Name: slot_offers slot_offers_guard_live_hold; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_offers_guard_live_hold BEFORE INSERT OR UPDATE OF status, capacity_hold_id, slot_opportunity_id, expires_at ON request_engine.slot_offers FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_live_hold();


--
-- Name: slot_offers slot_offers_guard_provenance; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_offers_guard_provenance BEFORE UPDATE ON request_engine.slot_offers FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_provenance_update();


--
-- Name: slot_offers slot_offers_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_offers_guard_transition BEFORE UPDATE ON request_engine.slot_offers FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_offer_transition();


--
-- Name: slot_offers slot_offers_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_offers_revision_step BEFORE UPDATE ON request_engine.slot_offers FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: slot_offers slot_offers_source_consistency_deferred; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER slot_offers_source_consistency_deferred AFTER INSERT OR UPDATE ON request_engine.slot_offers DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_offered_slot_offer_source_consistency();


--
-- Name: slot_offers slot_offers_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_offers_touch BEFORE UPDATE ON request_engine.slot_offers FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: slot_opportunities slot_opportunities_guard_provenance; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_opportunities_guard_provenance BEFORE UPDATE ON request_engine.slot_opportunities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_opportunity_provenance_update();


--
-- Name: slot_opportunities slot_opportunities_guard_transition; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_opportunities_guard_transition BEFORE UPDATE ON request_engine.slot_opportunities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_slot_opportunity_transition();


--
-- Name: slot_opportunities slot_opportunities_offer_consistency_deferred; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER slot_opportunities_offer_consistency_deferred AFTER UPDATE ON request_engine.slot_opportunities DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_offered_slot_offer_source_consistency();


--
-- Name: slot_opportunities slot_opportunities_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_opportunities_revision_step BEFORE UPDATE ON request_engine.slot_opportunities FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: slot_opportunities slot_opportunities_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER slot_opportunities_touch BEFORE UPDATE ON request_engine.slot_opportunities FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: waitlist_entries waitlist_entries_guard_provenance; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER waitlist_entries_guard_provenance BEFORE UPDATE ON request_engine.waitlist_entries FOR EACH ROW EXECUTE FUNCTION request_engine.guard_waitlist_entry_provenance_update();


--
-- Name: waitlist_entries waitlist_entries_revision_step; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER waitlist_entries_revision_step BEFORE UPDATE ON request_engine.waitlist_entries FOR EACH ROW EXECUTE FUNCTION request_engine.guard_exact_revision_step();


--
-- Name: waitlist_entries waitlist_entries_slot_offer_consistency_deferred; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE CONSTRAINT TRIGGER waitlist_entries_slot_offer_consistency_deferred AFTER UPDATE ON request_engine.waitlist_entries DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION request_engine.check_offered_slot_offer_source_consistency();


--
-- Name: waitlist_entries waitlist_entries_touch; Type: TRIGGER; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE TRIGGER waitlist_entries_touch BEFORE UPDATE ON request_engine.waitlist_entries FOR EACH ROW EXECUTE FUNCTION request_engine.touch_updated_at();


--
-- Name: attendance_responses attendance_responses_organization_id_actor_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.attendance_responses
    ADD CONSTRAINT attendance_responses_organization_id_actor_principal_id_fkey FOREIGN KEY (organization_id, actor_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: attendance_responses attendance_responses_organization_id_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.attendance_responses
    ADD CONSTRAINT attendance_responses_organization_id_reservation_id_fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: audit_records audit_records_organization_id_actor_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_organization_id_actor_principal_id_fkey FOREIGN KEY (organization_id, actor_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: audit_records audit_records_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: audit_records audit_records_organization_id_idempotency_record_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_organization_id_idempotency_record_id_fkey FOREIGN KEY (organization_id, idempotency_record_id) REFERENCES request_engine.idempotency_records(organization_id, id);


--
-- Name: audit_records audit_records_organization_id_representation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_organization_id_representation_id_fkey FOREIGN KEY (organization_id, representation_id) REFERENCES request_engine.representations(organization_id, id);


--
-- Name: audit_records audit_records_organization_id_represented_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.audit_records
    ADD CONSTRAINT audit_records_organization_id_represented_party_id_fkey FOREIGN KEY (organization_id, represented_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: booking_context_terms booking_context_terms_organization_id_offering_version_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.booking_context_terms
    ADD CONSTRAINT booking_context_terms_organization_id_offering_version_id_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: booking_context_terms booking_context_terms_organization_id_resource_location_as_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.booking_context_terms
    ADD CONSTRAINT booking_context_terms_organization_id_resource_location_as_fkey FOREIGN KEY (organization_id, resource_location_assignment_id) REFERENCES request_engine.resource_location_assignments(organization_id, id);


--
-- Name: capacity_claims capacity_claims_organization_id_hold_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_organization_id_hold_id_fkey FOREIGN KEY (organization_id, hold_id) REFERENCES request_engine.capacity_holds(organization_id, id);


--
-- Name: capacity_claims capacity_claims_organization_id_replaced_by_claim_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_organization_id_replaced_by_claim_id_fkey FOREIGN KEY (organization_id, replaced_by_claim_id) REFERENCES request_engine.capacity_claims(organization_id, id);


--
-- Name: capacity_claims capacity_claims_organization_id_requirement_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_organization_id_requirement_id_fkey FOREIGN KEY (organization_id, requirement_id) REFERENCES request_engine.offering_resource_requirements(organization_id, id);


--
-- Name: capacity_claims capacity_claims_organization_id_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_organization_id_reservation_id_fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: capacity_claims capacity_claims_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: capacity_claims capacity_claims_resource_location_assignment_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_claims
    ADD CONSTRAINT capacity_claims_resource_location_assignment_fk FOREIGN KEY (organization_id, resource_location_assignment_id) REFERENCES request_engine.resource_location_assignments(organization_id, id);


--
-- Name: capacity_holds capacity_holds_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_holds
    ADD CONSTRAINT capacity_holds_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: capacity_holds capacity_holds_organization_id_offering_version_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_holds
    ADD CONSTRAINT capacity_holds_organization_id_offering_version_id_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: capacity_holds capacity_holds_organization_id_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.capacity_holds
    ADD CONSTRAINT capacity_holds_organization_id_subject_party_id_fkey FOREIGN KEY (organization_id, subject_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: communication_deliveries communication_deliveries_organization_id_communication_tas_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_deliveries
    ADD CONSTRAINT communication_deliveries_organization_id_communication_tas_fkey FOREIGN KEY (organization_id, communication_task_id) REFERENCES request_engine.communication_tasks(organization_id, id);


--
-- Name: communication_escalations communication_escalations_organization_id_child_task_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_escalations
    ADD CONSTRAINT communication_escalations_organization_id_child_task_id_fkey FOREIGN KEY (organization_id, child_task_id) REFERENCES request_engine.communication_tasks(organization_id, id);


--
-- Name: communication_escalations communication_escalations_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_escalations
    ADD CONSTRAINT communication_escalations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: communication_escalations communication_escalations_organization_id_parent_task_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_escalations
    ADD CONSTRAINT communication_escalations_organization_id_parent_task_id_fkey FOREIGN KEY (organization_id, parent_task_id) REFERENCES request_engine.communication_tasks(organization_id, id);


--
-- Name: communication_tasks communication_tasks_organization_id_contact_point_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_tasks
    ADD CONSTRAINT communication_tasks_organization_id_contact_point_id_fkey FOREIGN KEY (organization_id, contact_point_id) REFERENCES request_engine.party_contact_points(organization_id, id);


--
-- Name: communication_tasks communication_tasks_organization_id_recipient_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_tasks
    ADD CONSTRAINT communication_tasks_organization_id_recipient_party_id_fkey FOREIGN KEY (organization_id, recipient_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: communication_tasks communication_tasks_parent_task_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.communication_tasks
    ADD CONSTRAINT communication_tasks_parent_task_fk FOREIGN KEY (organization_id, parent_task_id) REFERENCES request_engine.communication_tasks(organization_id, id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_consumed_reservation_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_consumed_reservation_fk FOREIGN KEY (organization_id, consumed_reservation_id) REFERENCES request_engine.reservations(organization_id, id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_organization_id_mapping_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_organization_id_mapping_id_fkey FOREIGN KEY (organization_id, mapping_id) REFERENCES request_engine.offering_service_classifications(organization_id, id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_organization_id_offering_versio_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_organization_id_offering_versio_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: discovery_booking_handoffs discovery_booking_handoffs_organization_id_publication_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_booking_handoffs
    ADD CONSTRAINT discovery_booking_handoffs_organization_id_publication_id_fkey FOREIGN KEY (organization_id, publication_id) REFERENCES request_engine.discovery_publications(organization_id, id);


--
-- Name: discovery_publications discovery_publications_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: discovery_publications discovery_publications_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: discovery_publications discovery_publications_organization_id_offering_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_organization_id_offering_id_fkey FOREIGN KEY (organization_id, offering_id) REFERENCES request_engine.offerings(organization_id, id);


--
-- Name: discovery_publications discovery_publications_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.discovery_publications
    ADD CONSTRAINT discovery_publications_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: external_correlations external_correlations_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.external_correlations
    ADD CONSTRAINT external_correlations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: external_correlations external_correlations_organization_id_request_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.external_correlations
    ADD CONSTRAINT external_correlations_organization_id_request_id_fkey FOREIGN KEY (organization_id, request_id) REFERENCES request_engine.requests(organization_id, id);


--
-- Name: idempotency_records idempotency_records_organization_id_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.idempotency_records
    ADD CONSTRAINT idempotency_records_organization_id_principal_id_fkey FOREIGN KEY (organization_id, principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: identity_exchange_candidates identity_exchange_candidates_organization_id_created_by_pr_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_exchange_candidates
    ADD CONSTRAINT identity_exchange_candidates_organization_id_created_by_pr_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: identity_exchange_candidates identity_exchange_candidates_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_exchange_candidates
    ADD CONSTRAINT identity_exchange_candidates_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: identity_exchange_candidates identity_exchange_candidates_portable_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.identity_exchange_candidates
    ADD CONSTRAINT identity_exchange_candidates_portable_party_id_fkey FOREIGN KEY (portable_party_id) REFERENCES request_engine.portable_party_identities(id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_poli_organization_id_service_queu_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_poli_organization_id_service_queu_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_polic_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_polic_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_polic_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_polic_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: live_capacity_projection_policies live_capacity_projection_policies_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_projection_policies
    ADD CONSTRAINT live_capacity_projection_policies_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estima_organization_id_workload_cla_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies
    ADD CONSTRAINT live_capacity_workload_estima_organization_id_workload_cla_fkey FOREIGN KEY (organization_id, workload_classification_id) REFERENCES request_engine.operational_workload_classifications(organization_id, id);


--
-- Name: live_capacity_workload_estimate_policies live_capacity_workload_estimate_policies_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.live_capacity_workload_estimate_policies
    ADD CONSTRAINT live_capacity_workload_estimate_policies_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: location_hours_exceptions location_hours_exceptions_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_hours_exceptions
    ADD CONSTRAINT location_hours_exceptions_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: location_operational_hours location_operational_hours_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_operational_hours
    ADD CONSTRAINT location_operational_hours_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: location_public_contact_endpoints location_public_contact_endpoi_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.location_public_contact_endpoints
    ADD CONSTRAINT location_public_contact_endpoi_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: locations locations_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.locations
    ADD CONSTRAINT locations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: offering_resource_requirements offering_resource_requirement_organization_id_capability_i_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_resource_requirements
    ADD CONSTRAINT offering_resource_requirement_organization_id_capability_i_fkey FOREIGN KEY (organization_id, capability_id) REFERENCES request_engine.resource_capabilities(organization_id, id);


--
-- Name: offering_resource_requirements offering_resource_requirement_organization_id_offering_ver_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_resource_requirements
    ADD CONSTRAINT offering_resource_requirement_organization_id_offering_ver_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: offering_service_classifications offering_service_classificatio_organization_id_offering_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_service_classifications
    ADD CONSTRAINT offering_service_classificatio_organization_id_offering_id_fkey FOREIGN KEY (organization_id, offering_id) REFERENCES request_engine.offerings(organization_id, id);


--
-- Name: offering_service_classifications offering_service_classifications_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_service_classifications
    ADD CONSTRAINT offering_service_classifications_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: offering_service_classifications offering_service_classifications_service_classification_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_service_classifications
    ADD CONSTRAINT offering_service_classifications_service_classification_id_fkey FOREIGN KEY (service_classification_id) REFERENCES request_engine.service_classifications(id);


--
-- Name: offering_version_booking_policies offering_version_booking_poli_organization_id_offering_ver_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_policies
    ADD CONSTRAINT offering_version_booking_poli_organization_id_offering_ver_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: offering_version_booking_terms offering_version_booking_term_organization_id_offering_ver_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_version_booking_terms
    ADD CONSTRAINT offering_version_booking_term_organization_id_offering_ver_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: offering_versions offering_versions_organization_id_offering_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offering_versions
    ADD CONSTRAINT offering_versions_organization_id_offering_id_fkey FOREIGN KEY (organization_id, offering_id) REFERENCES request_engine.offerings(organization_id, id);


--
-- Name: offerings offerings_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.offerings
    ADD CONSTRAINT offerings_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: operational_recovery_actions operational_recovery_actions_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_actions
    ADD CONSTRAINT operational_recovery_actions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: operational_recovery_actions operational_recovery_actions_organization_id_incident_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_actions
    ADD CONSTRAINT operational_recovery_actions_organization_id_incident_id_fkey FOREIGN KEY (organization_id, incident_id) REFERENCES request_engine.operational_recovery_incidents(organization_id, id);


--
-- Name: operational_recovery_actions operational_recovery_actions_organization_id_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_actions
    ADD CONSTRAINT operational_recovery_actions_organization_id_principal_id_fkey FOREIGN KEY (organization_id, principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: operational_recovery_autonomy_policies operational_recovery_autonomy_organization_id_service_queu_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_autonomy_policies
    ADD CONSTRAINT operational_recovery_autonomy_organization_id_service_queu_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: operational_recovery_autonomy_policies operational_recovery_autonomy_p_organization_id_granted_by_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_autonomy_policies
    ADD CONSTRAINT operational_recovery_autonomy_p_organization_id_granted_by_fkey FOREIGN KEY (organization_id, granted_by) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: operational_recovery_escalations operational_recovery_escalatio_organization_id_incident_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_escalations
    ADD CONSTRAINT operational_recovery_escalatio_organization_id_incident_id_fkey FOREIGN KEY (organization_id, incident_id) REFERENCES request_engine.operational_recovery_incidents(organization_id, id);


--
-- Name: operational_recovery_escalations operational_recovery_escalations_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_escalations
    ADD CONSTRAINT operational_recovery_escalations_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: operational_recovery_executions operational_recovery_executio_organization_id_communicatio_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executio_organization_id_communicatio_fkey FOREIGN KEY (organization_id, communication_task_id) REFERENCES request_engine.communication_tasks(organization_id, id);


--
-- Name: operational_recovery_executions operational_recovery_executio_organization_id_executed_by__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executio_organization_id_executed_by__fkey FOREIGN KEY (organization_id, executed_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: operational_recovery_executions operational_recovery_executio_organization_id_reservation__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executio_organization_id_reservation__fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: operational_recovery_executions operational_recovery_execution_organization_id_proposal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_execution_organization_id_proposal_id_fkey FOREIGN KEY (organization_id, proposal_id) REFERENCES request_engine.operational_recovery_proposals(organization_id, id);


--
-- Name: operational_recovery_executions operational_recovery_executions_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_executions
    ADD CONSTRAINT operational_recovery_executions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: operational_recovery_incidents operational_recovery_incident_organization_id_current_prop_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incident_organization_id_current_prop_fkey FOREIGN KEY (organization_id, current_proposal_id) REFERENCES request_engine.operational_recovery_proposals(organization_id, id);


--
-- Name: operational_recovery_incidents operational_recovery_incident_organization_id_service_queu_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incident_organization_id_service_queu_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: operational_recovery_incidents operational_recovery_incidents_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incidents_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: operational_recovery_incidents operational_recovery_incidents_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incidents_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: operational_recovery_incidents operational_recovery_incidents_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_incidents
    ADD CONSTRAINT operational_recovery_incidents_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: operational_recovery_proposals operational_recovery_proposal_organization_id_created_by_p_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposal_organization_id_created_by_p_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: operational_recovery_proposals operational_recovery_proposal_organization_id_service_queu_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposal_organization_id_service_queu_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: operational_recovery_proposals operational_recovery_proposals_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposals_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: operational_recovery_proposals operational_recovery_proposals_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposals_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: operational_recovery_proposals operational_recovery_proposals_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_recovery_proposals
    ADD CONSTRAINT operational_recovery_proposals_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: operational_workload_classifications operational_workload_classifications_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.operational_workload_classifications
    ADD CONSTRAINT operational_workload_classifications_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: organization_party_bindings organization_party_bindings_organization_id_created_by_pri_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_party_bindings
    ADD CONSTRAINT organization_party_bindings_organization_id_created_by_pri_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: organization_party_bindings organization_party_bindings_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_party_bindings
    ADD CONSTRAINT organization_party_bindings_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: organization_party_bindings organization_party_bindings_organization_id_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_party_bindings
    ADD CONSTRAINT organization_party_bindings_organization_id_party_id_fkey FOREIGN KEY (organization_id, party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: organization_party_bindings organization_party_bindings_portable_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_party_bindings
    ADD CONSTRAINT organization_party_bindings_portable_party_id_fkey FOREIGN KEY (portable_party_id) REFERENCES request_engine.portable_party_identities(id);


--
-- Name: organization_public_contact_endpoints organization_public_contact_endpoints_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.organization_public_contact_endpoints
    ADD CONSTRAINT organization_public_contact_endpoints_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: outbox_messages outbox_messages_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.outbox_messages
    ADD CONSTRAINT outbox_messages_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: parties parties_created_by_principal_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.parties
    ADD CONSTRAINT parties_created_by_principal_fk FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: parties parties_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.parties
    ADD CONSTRAINT parties_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: parties parties_relay_principal_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.parties
    ADD CONSTRAINT parties_relay_principal_fk FOREIGN KEY (organization_id, relay_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_administrative_identifiers party_administrative_identifi_organization_id_created_by_p_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_administrative_identifiers
    ADD CONSTRAINT party_administrative_identifi_organization_id_created_by_p_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_administrative_identifiers party_administrative_identifi_organization_id_relay_princi_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_administrative_identifiers
    ADD CONSTRAINT party_administrative_identifi_organization_id_relay_princi_fkey FOREIGN KEY (organization_id, relay_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_administrative_identifiers party_administrative_identifiers_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_administrative_identifiers
    ADD CONSTRAINT party_administrative_identifiers_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: party_administrative_identifiers party_administrative_identifiers_organization_id_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_administrative_identifiers
    ADD CONSTRAINT party_administrative_identifiers_organization_id_party_id_fkey FOREIGN KEY (organization_id, party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: party_contact_points party_contact_points_created_by_principal_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_contact_points
    ADD CONSTRAINT party_contact_points_created_by_principal_fk FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_contact_points party_contact_points_organization_id_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_contact_points
    ADD CONSTRAINT party_contact_points_organization_id_party_id_fkey FOREIGN KEY (organization_id, party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: party_contact_points party_contact_points_relay_principal_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_contact_points
    ADD CONSTRAINT party_contact_points_relay_principal_fk FOREIGN KEY (organization_id, relay_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_identity_documents party_identity_documents_organization_id_created_by_princi_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_organization_id_created_by_princi_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_identity_documents party_identity_documents_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: party_identity_documents party_identity_documents_organization_id_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_organization_id_party_id_fkey FOREIGN KEY (organization_id, party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: party_identity_documents party_identity_documents_relay_principal_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_documents
    ADD CONSTRAINT party_identity_documents_relay_principal_fk FOREIGN KEY (organization_id, relay_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_identity_revisions party_identity_revisions_organization_id_actor_principal_i_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_revisions
    ADD CONSTRAINT party_identity_revisions_organization_id_actor_principal_i_fkey FOREIGN KEY (organization_id, actor_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_identity_revisions party_identity_revisions_organization_id_attributed_operat_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_revisions
    ADD CONSTRAINT party_identity_revisions_organization_id_attributed_operat_fkey FOREIGN KEY (organization_id, attributed_operator_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: party_identity_revisions party_identity_revisions_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_revisions
    ADD CONSTRAINT party_identity_revisions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: party_identity_revisions party_identity_revisions_organization_id_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.party_identity_revisions
    ADD CONSTRAINT party_identity_revisions_organization_id_party_id_fkey FOREIGN KEY (organization_id, party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: portable_party_identifiers portable_party_identifiers_portable_party_id_party_kind_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_identifiers
    ADD CONSTRAINT portable_party_identifiers_portable_party_id_party_kind_fkey FOREIGN KEY (portable_party_id, party_kind) REFERENCES request_engine.portable_party_identities(id, party_kind);


--
-- Name: portable_party_profiles portable_party_profiles_portable_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_profiles
    ADD CONSTRAINT portable_party_profiles_portable_party_id_fkey FOREIGN KEY (portable_party_id) REFERENCES request_engine.portable_party_identities(id);


--
-- Name: portable_party_profiles portable_party_profiles_publisher_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.portable_party_profiles
    ADD CONSTRAINT portable_party_profiles_publisher_organization_id_fkey FOREIGN KEY (publisher_organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: principal_contacts principal_contacts_organization_id_created_by_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_contacts
    ADD CONSTRAINT principal_contacts_organization_id_created_by_principal_id_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: principal_contacts principal_contacts_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_contacts
    ADD CONSTRAINT principal_contacts_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: principal_contacts principal_contacts_organization_id_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principal_contacts
    ADD CONSTRAINT principal_contacts_organization_id_principal_id_fkey FOREIGN KEY (organization_id, principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: principals principals_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.principals
    ADD CONSTRAINT principals_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: provider_events provider_events_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.provider_events
    ADD CONSTRAINT provider_events_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: queue_entries queue_entries_expected_workload_fk; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_expected_workload_fk FOREIGN KEY (organization_id, expected_workload_classification_id) REFERENCES request_engine.operational_workload_classifications(organization_id, id);


--
-- Name: queue_entries queue_entries_organization_id_offering_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_organization_id_offering_id_fkey FOREIGN KEY (organization_id, offering_id) REFERENCES request_engine.offerings(organization_id, id);


--
-- Name: queue_entries queue_entries_organization_id_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_organization_id_reservation_id_fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: queue_entries queue_entries_organization_id_service_queue_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_organization_id_service_queue_id_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: queue_entries queue_entries_organization_id_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entries
    ADD CONSTRAINT queue_entries_organization_id_subject_party_id_fkey FOREIGN KEY (organization_id, subject_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: queue_entry_operator_selections queue_entry_operator_selectio_organization_id_queue_entry__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_operator_selections
    ADD CONSTRAINT queue_entry_operator_selectio_organization_id_queue_entry__fkey FOREIGN KEY (organization_id, queue_entry_id) REFERENCES request_engine.queue_entries(organization_id, id);


--
-- Name: queue_entry_operator_selections queue_entry_operator_selectio_organization_id_selected_by__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_operator_selections
    ADD CONSTRAINT queue_entry_operator_selectio_organization_id_selected_by__fkey FOREIGN KEY (organization_id, selected_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: queue_entry_recall_holds queue_entry_recall_holds_organization_id_created_by_princi_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_recall_holds
    ADD CONSTRAINT queue_entry_recall_holds_organization_id_created_by_princi_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: queue_entry_recall_holds queue_entry_recall_holds_organization_id_queue_entry_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_recall_holds
    ADD CONSTRAINT queue_entry_recall_holds_organization_id_queue_entry_id_fkey FOREIGN KEY (organization_id, queue_entry_id) REFERENCES request_engine.queue_entries(organization_id, id);


--
-- Name: queue_entry_skips queue_entry_skips_organization_id_consumed_by_entry_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_skips
    ADD CONSTRAINT queue_entry_skips_organization_id_consumed_by_entry_id_fkey FOREIGN KEY (organization_id, consumed_by_entry_id) REFERENCES request_engine.queue_entries(organization_id, id);


--
-- Name: queue_entry_skips queue_entry_skips_organization_id_created_by_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_skips
    ADD CONSTRAINT queue_entry_skips_organization_id_created_by_principal_id_fkey FOREIGN KEY (organization_id, created_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: queue_entry_skips queue_entry_skips_organization_id_queue_entry_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.queue_entry_skips
    ADD CONSTRAINT queue_entry_skips_organization_id_queue_entry_id_fkey FOREIGN KEY (organization_id, queue_entry_id) REFERENCES request_engine.queue_entries(organization_id, id);


--
-- Name: recovery_source_revisions recovery_source_revisions_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.recovery_source_revisions
    ADD CONSTRAINT recovery_source_revisions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: recovery_source_revisions recovery_source_revisions_organization_id_service_queue_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.recovery_source_revisions
    ADD CONSTRAINT recovery_source_revisions_organization_id_service_queue_id_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: reminder_acknowledgements reminder_acknowledgements_organization_id_reminder_plan_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_acknowledgements
    ADD CONSTRAINT reminder_acknowledgements_organization_id_reminder_plan_id_fkey FOREIGN KEY (organization_id, reminder_plan_id) REFERENCES request_engine.reminder_plans(organization_id, id);


--
-- Name: reminder_acknowledgements reminder_acknowledgements_organization_id_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_acknowledgements
    ADD CONSTRAINT reminder_acknowledgements_organization_id_subject_party_id_fkey FOREIGN KEY (organization_id, subject_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: reminder_plans reminder_plans_organization_id_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reminder_plans
    ADD CONSTRAINT reminder_plans_organization_id_subject_party_id_fkey FOREIGN KEY (organization_id, subject_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: representations representations_organization_id_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.representations
    ADD CONSTRAINT representations_organization_id_principal_id_fkey FOREIGN KEY (organization_id, principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: representations representations_organization_id_represented_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.representations
    ADD CONSTRAINT representations_organization_id_represented_party_id_fkey FOREIGN KEY (organization_id, represented_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: request_definition_versions request_definition_versions_organization_id_request_defini_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definition_versions
    ADD CONSTRAINT request_definition_versions_organization_id_request_defini_fkey FOREIGN KEY (organization_id, request_definition_id) REFERENCES request_engine.request_definitions(organization_id, id);


--
-- Name: request_definitions request_definitions_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_definitions
    ADD CONSTRAINT request_definitions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: request_participants request_participants_organization_id_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_participants
    ADD CONSTRAINT request_participants_organization_id_party_id_fkey FOREIGN KEY (organization_id, party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: request_participants request_participants_organization_id_request_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.request_participants
    ADD CONSTRAINT request_participants_organization_id_request_id_fkey FOREIGN KEY (organization_id, request_id) REFERENCES request_engine.requests(organization_id, id);


--
-- Name: requests requests_organization_id_recipient_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.requests
    ADD CONSTRAINT requests_organization_id_recipient_party_id_fkey FOREIGN KEY (organization_id, recipient_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: requests requests_organization_id_request_definition_version_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.requests
    ADD CONSTRAINT requests_organization_id_request_definition_version_id_fkey FOREIGN KEY (organization_id, request_definition_version_id) REFERENCES request_engine.request_definition_versions(organization_id, id);


--
-- Name: requests requests_organization_id_requester_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.requests
    ADD CONSTRAINT requests_organization_id_requester_party_id_fkey FOREIGN KEY (organization_id, requester_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: reservation_access reservation_access_organization_id_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_access
    ADD CONSTRAINT reservation_access_organization_id_reservation_id_fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_organization_id_asserted_by__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_arrival_estimates
    ADD CONSTRAINT reservation_arrival_estimates_organization_id_asserted_by__fkey FOREIGN KEY (organization_id, asserted_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: reservation_arrival_estimates reservation_arrival_estimates_organization_id_reservation__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_arrival_estimates
    ADD CONSTRAINT reservation_arrival_estimates_organization_id_reservation__fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: reservation_attendance reservation_attendance_organization_id_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_attendance
    ADD CONSTRAINT reservation_attendance_organization_id_reservation_id_fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: reservation_commercial_commitment_context_terms reservation_commercial_commi_organization_id_reservation__fkey1; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitment_context_terms
    ADD CONSTRAINT reservation_commercial_commi_organization_id_reservation__fkey1 FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservation_commercial_commitments(organization_id, reservation_id);


--
-- Name: reservation_commercial_commitment_context_terms reservation_commercial_commit_organization_id_booking_cont_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitment_context_terms
    ADD CONSTRAINT reservation_commercial_commit_organization_id_booking_cont_fkey FOREIGN KEY (organization_id, booking_context_terms_id) REFERENCES request_engine.booking_context_terms(organization_id, id);


--
-- Name: reservation_commercial_commitments reservation_commercial_commit_organization_id_offering_ver_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitments
    ADD CONSTRAINT reservation_commercial_commit_organization_id_offering_ver_fkey FOREIGN KEY (organization_id, offering_version_booking_terms_id) REFERENCES request_engine.offering_version_booking_terms(organization_id, id);


--
-- Name: reservation_commercial_commitments reservation_commercial_commit_organization_id_reservation__fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservation_commercial_commitments
    ADD CONSTRAINT reservation_commercial_commit_organization_id_reservation__fkey FOREIGN KEY (organization_id, reservation_id) REFERENCES request_engine.reservations(organization_id, id);


--
-- Name: reservations reservations_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservations
    ADD CONSTRAINT reservations_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: reservations reservations_organization_id_offering_version_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservations
    ADD CONSTRAINT reservations_organization_id_offering_version_id_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: reservations reservations_organization_id_origin_request_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservations
    ADD CONSTRAINT reservations_organization_id_origin_request_id_fkey FOREIGN KEY (organization_id, origin_request_id) REFERENCES request_engine.requests(organization_id, id);


--
-- Name: reservations reservations_organization_id_subject_party_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.reservations
    ADD CONSTRAINT reservations_organization_id_subject_party_id_fkey FOREIGN KEY (organization_id, subject_party_id) REFERENCES request_engine.parties(organization_id, id);


--
-- Name: resource_activities resource_activities_organization_id_ended_by_principal_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_activities
    ADD CONSTRAINT resource_activities_organization_id_ended_by_principal_id_fkey FOREIGN KEY (organization_id, ended_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: resource_activities resource_activities_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_activities
    ADD CONSTRAINT resource_activities_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: resource_activities resource_activities_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_activities
    ADD CONSTRAINT resource_activities_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: resource_activities resource_activities_organization_id_started_by_principal_i_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_activities
    ADD CONSTRAINT resource_activities_organization_id_started_by_principal_i_fkey FOREIGN KEY (organization_id, started_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: resource_capabilities resource_capabilities_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capabilities
    ADD CONSTRAINT resource_capabilities_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: resource_capability_assignments resource_capability_assignmen_organization_id_capability_i_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capability_assignments
    ADD CONSTRAINT resource_capability_assignmen_organization_id_capability_i_fkey FOREIGN KEY (organization_id, capability_id) REFERENCES request_engine.resource_capabilities(organization_id, id);


--
-- Name: resource_capability_assignments resource_capability_assignment_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_capability_assignments
    ADD CONSTRAINT resource_capability_assignment_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: resource_location_assignments resource_location_assignments_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_assignments
    ADD CONSTRAINT resource_location_assignments_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: resource_location_assignments resource_location_assignments_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_assignments
    ADD CONSTRAINT resource_location_assignments_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: resource_location_availability resource_location_availabilit_organization_id_resource_loc_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_availability
    ADD CONSTRAINT resource_location_availabilit_organization_id_resource_loc_fkey FOREIGN KEY (organization_id, resource_location_assignment_id) REFERENCES request_engine.resource_location_assignments(organization_id, id);


--
-- Name: resource_location_schedule_exceptions resource_location_schedule_ex_organization_id_resource_loc_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_location_schedule_exceptions
    ADD CONSTRAINT resource_location_schedule_ex_organization_id_resource_loc_fkey FOREIGN KEY (organization_id, resource_location_assignment_id) REFERENCES request_engine.resource_location_assignments(organization_id, id);


--
-- Name: resource_public_profiles resource_public_profiles_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resource_public_profiles
    ADD CONSTRAINT resource_public_profiles_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: resources resources_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.resources
    ADD CONSTRAINT resources_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: schedule_exceptions schedule_exceptions_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.schedule_exceptions
    ADD CONSTRAINT schedule_exceptions_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: scheduled_actions scheduled_actions_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.scheduled_actions
    ADD CONSTRAINT scheduled_actions_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: service_classification_authority_events service_classification_authority_service_classification_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_classification_authority_events
    ADD CONSTRAINT service_classification_authority_service_classification_id_fkey FOREIGN KEY (service_classification_id) REFERENCES request_engine.service_classifications(id);


--
-- Name: service_queue_intake_controls service_queue_intake_controls_organization_id_service_queu_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queue_intake_controls
    ADD CONSTRAINT service_queue_intake_controls_organization_id_service_queu_fkey FOREIGN KEY (organization_id, service_queue_id) REFERENCES request_engine.service_queues(organization_id, id);


--
-- Name: service_queue_intake_controls service_queue_intake_controls_organization_id_updated_by_p_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queue_intake_controls
    ADD CONSTRAINT service_queue_intake_controls_organization_id_updated_by_p_fkey FOREIGN KEY (organization_id, updated_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: service_queues service_queues_organization_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queues
    ADD CONSTRAINT service_queues_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES request_engine.organizations(id);


--
-- Name: service_queues service_queues_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queues
    ADD CONSTRAINT service_queues_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: service_queues service_queues_organization_id_offering_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_queues
    ADD CONSTRAINT service_queues_organization_id_offering_id_fkey FOREIGN KEY (organization_id, offering_id) REFERENCES request_engine.offerings(organization_id, id);


--
-- Name: service_session_interruptions service_session_interruptions_organization_id_ended_by_pri_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_session_interruptions
    ADD CONSTRAINT service_session_interruptions_organization_id_ended_by_pri_fkey FOREIGN KEY (organization_id, ended_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: service_session_interruptions service_session_interruptions_organization_id_service_sess_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_session_interruptions
    ADD CONSTRAINT service_session_interruptions_organization_id_service_sess_fkey FOREIGN KEY (organization_id, service_session_id) REFERENCES request_engine.service_sessions(organization_id, id);


--
-- Name: service_session_interruptions service_session_interruptions_organization_id_started_by_p_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_session_interruptions
    ADD CONSTRAINT service_session_interruptions_organization_id_started_by_p_fkey FOREIGN KEY (organization_id, started_by_principal_id) REFERENCES request_engine.principals(organization_id, id);


--
-- Name: service_sessions service_sessions_organization_id_actual_workload_classific_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_organization_id_actual_workload_classific_fkey FOREIGN KEY (organization_id, actual_workload_classification_id) REFERENCES request_engine.operational_workload_classifications(organization_id, id);


--
-- Name: service_sessions service_sessions_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: service_sessions service_sessions_organization_id_queue_entry_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_organization_id_queue_entry_id_fkey FOREIGN KEY (organization_id, queue_entry_id) REFERENCES request_engine.queue_entries(organization_id, id);


--
-- Name: service_sessions service_sessions_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.service_sessions
    ADD CONSTRAINT service_sessions_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: shared_capacity_authority_events shared_capacity_authority_even_shared_capacity_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_authority_events
    ADD CONSTRAINT shared_capacity_authority_even_shared_capacity_identity_id_fkey FOREIGN KEY (shared_capacity_identity_id) REFERENCES request_engine.shared_capacity_identities(id);


--
-- Name: shared_capacity_authority_events shared_capacity_authority_events_global_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_authority_events
    ADD CONSTRAINT shared_capacity_authority_events_global_identity_id_fkey FOREIGN KEY (global_identity_id) REFERENCES request_engine.global_identities(id);


--
-- Name: shared_capacity_bindings shared_capacity_bindings_organization_id_resource_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_bindings
    ADD CONSTRAINT shared_capacity_bindings_organization_id_resource_id_fkey FOREIGN KEY (organization_id, resource_id) REFERENCES request_engine.resources(organization_id, id);


--
-- Name: shared_capacity_bindings shared_capacity_bindings_shared_capacity_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_bindings
    ADD CONSTRAINT shared_capacity_bindings_shared_capacity_identity_id_fkey FOREIGN KEY (shared_capacity_identity_id) REFERENCES request_engine.shared_capacity_identities(id);


--
-- Name: shared_capacity_claim_links shared_capacity_claim_links_capacity_claim_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_claim_links
    ADD CONSTRAINT shared_capacity_claim_links_capacity_claim_id_fkey FOREIGN KEY (capacity_claim_id) REFERENCES request_engine.capacity_claims(id);


--
-- Name: shared_capacity_claim_links shared_capacity_claim_links_shared_capacity_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_claim_links
    ADD CONSTRAINT shared_capacity_claim_links_shared_capacity_identity_id_fkey FOREIGN KEY (shared_capacity_identity_id) REFERENCES request_engine.shared_capacity_identities(id);


--
-- Name: shared_capacity_identities shared_capacity_identities_global_identity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.shared_capacity_identities
    ADD CONSTRAINT shared_capacity_identities_global_identity_id_fkey FOREIGN KEY (global_identity_id) REFERENCES request_engine.global_identities(id);


--
-- Name: slot_offers slot_offers_organization_id_capacity_hold_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_offers
    ADD CONSTRAINT slot_offers_organization_id_capacity_hold_id_fkey FOREIGN KEY (organization_id, capacity_hold_id) REFERENCES request_engine.capacity_holds(organization_id, id);


--
-- Name: slot_offers slot_offers_organization_id_slot_opportunity_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_offers
    ADD CONSTRAINT slot_offers_organization_id_slot_opportunity_id_fkey FOREIGN KEY (organization_id, slot_opportunity_id) REFERENCES request_engine.slot_opportunities(organization_id, id);


--
-- Name: slot_offers slot_offers_organization_id_waitlist_entry_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_offers
    ADD CONSTRAINT slot_offers_organization_id_waitlist_entry_id_fkey FOREIGN KEY (organization_id, waitlist_entry_id) REFERENCES request_engine.waitlist_entries(organization_id, id);


--
-- Name: slot_opportunities slot_opportunities_organization_id_location_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_organization_id_location_id_fkey FOREIGN KEY (organization_id, location_id) REFERENCES request_engine.locations(organization_id, id);


--
-- Name: slot_opportunities slot_opportunities_organization_id_offering_version_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_organization_id_offering_version_id_fkey FOREIGN KEY (organization_id, offering_version_id) REFERENCES request_engine.offering_versions(organization_id, id);


--
-- Name: slot_opportunities slot_opportunities_organization_id_source_reservation_id_fkey; Type: FK CONSTRAINT; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE ONLY request_engine.slot_opportunities
    ADD CONSTRAINT slot_opportunities_organization_id_source_reservation_id_fkey FOREIGN KEY (organization_id, source_reservation_id) REFERENCES request_engine.reservations(organization_id, id);


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
-- Name: identity_exchange_candidates; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.identity_exchange_candidates ENABLE ROW LEVEL SECURITY;

--
-- Name: identity_exchange_candidates identity_exchange_candidates_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY identity_exchange_candidates_tenant_policy ON request_engine.identity_exchange_candidates USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


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
-- Name: organization_public_contact_endpoints; Type: ROW SECURITY; Schema: request_engine; Owner: request_engine_schema_owner
--

ALTER TABLE request_engine.organization_public_contact_endpoints ENABLE ROW LEVEL SECURITY;

--
-- Name: organization_public_contact_endpoints organization_public_contact_endpoints_tenant_policy; Type: POLICY; Schema: request_engine; Owner: request_engine_schema_owner
--

CREATE POLICY organization_public_contact_endpoints_tenant_policy ON request_engine.organization_public_contact_endpoints USING ((organization_id = request_engine.current_organization_id())) WITH CHECK ((organization_id = request_engine.current_organization_id()));


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
