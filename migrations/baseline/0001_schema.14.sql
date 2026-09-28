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
-- Name: FUNCTION bump_principal_authority_from_grant(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_principal_authority_from_grant() FROM PUBLIC;


--
-- Name: FUNCTION bump_principal_authority_from_identity_binding(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_principal_authority_from_identity_binding() FROM PUBLIC;


--
-- Name: FUNCTION bump_principal_authority_from_representation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.bump_principal_authority_from_representation() FROM PUBLIC;


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
-- Name: FUNCTION confirm_identity_link_intent(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_native_identity_id uuid, p_binding_id uuid, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.confirm_identity_link_intent(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_native_identity_id uuid, p_binding_id uuid, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.confirm_identity_link_intent(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_native_identity_id uuid, p_binding_id uuid, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION confirm_identity_link_subject(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_subject_id text, p_binding_id uuid, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.confirm_identity_link_subject(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_subject_id text, p_binding_id uuid, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.confirm_identity_link_subject(p_intent_id uuid, p_expected_actor_binding_revision bigint, p_subject_id text, p_binding_id uuid, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION create_delegation(p_id uuid, p_delegator_principal_id uuid, p_delegate_principal_id uuid, p_purpose text, p_allowed_capabilities text[], p_not_before timestamp with time zone, p_expires_at timestamp with time zone, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.create_delegation(p_id uuid, p_delegator_principal_id uuid, p_delegate_principal_id uuid, p_purpose text, p_allowed_capabilities text[], p_not_before timestamp with time zone, p_expires_at timestamp with time zone, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.create_delegation(p_id uuid, p_delegator_principal_id uuid, p_delegate_principal_id uuid, p_purpose text, p_allowed_capabilities text[], p_not_before timestamp with time zone, p_expires_at timestamp with time zone, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid) TO request_engine_app;


--
-- Name: FUNCTION create_identity_link_intent(p_intent_id uuid, p_actor_binding_id uuid, p_target_authority_id uuid, p_nonce_digest text, p_ttl_seconds integer, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.create_identity_link_intent(p_intent_id uuid, p_actor_binding_id uuid, p_target_authority_id uuid, p_nonce_digest text, p_ttl_seconds integer, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.create_identity_link_intent(p_intent_id uuid, p_actor_binding_id uuid, p_target_authority_id uuid, p_nonce_digest text, p_ttl_seconds integer, p_provenance_reference text) TO request_engine_app;


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
-- Name: FUNCTION derive_authentication_assurance(p_methods text[], p_user_verified boolean, p_recovery_derived boolean); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.derive_authentication_assurance(p_methods text[], p_user_verified boolean, p_recovery_derived boolean) FROM PUBLIC;


--
-- Name: FUNCTION guard_agent_profile(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_agent_profile() FROM PUBLIC;


--
-- Name: FUNCTION guard_authority_reference_tenant(); Type: ACL; Schema: request_engine; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_engine.guard_authority_reference_tenant() FROM PUBLIC;


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
-- Name: FUNCTION guard_delegation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_delegation() FROM PUBLIC;


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
-- Name: FUNCTION guard_identity_binding(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_identity_binding() FROM PUBLIC;


--
-- Name: FUNCTION guard_identity_link_intent(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_identity_link_intent() FROM PUBLIC;


--
-- Name: FUNCTION guard_integration_fact(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_integration_fact() FROM PUBLIC;


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
-- Name: FUNCTION guard_native_credential(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_native_credential() FROM PUBLIC;


--
-- Name: FUNCTION guard_native_identity(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_native_identity() FROM PUBLIC;


--
-- Name: FUNCTION guard_native_recovery_intent(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_native_recovery_intent() FROM PUBLIC;


--
-- Name: FUNCTION guard_native_session(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_native_session() FROM PUBLIC;


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
-- Name: FUNCTION guard_platform_bootstrap_intent(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_platform_bootstrap_intent() FROM PUBLIC;


--
-- Name: FUNCTION guard_platform_configuration_revision(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_platform_configuration_revision() FROM PUBLIC;


--
-- Name: FUNCTION guard_platform_instance(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_platform_instance() FROM PUBLIC;


--
-- Name: FUNCTION guard_platform_secret_binding(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_platform_secret_binding() FROM PUBLIC;


--
-- Name: FUNCTION guard_principal_authority_grant(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_principal_authority_grant() FROM PUBLIC;


--
-- Name: FUNCTION guard_principal_contacts(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_principal_contacts() FROM PUBLIC;


--
-- Name: FUNCTION guard_principal_security_identity(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_principal_security_identity() FROM PUBLIC;


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
-- Name: FUNCTION guard_setup_session(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_setup_session() FROM PUBLIC;


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
-- Name: FUNCTION guard_staff_membership(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_staff_membership() FROM PUBLIC;


--
-- Name: FUNCTION guard_waitlist_entry_provenance_update(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_waitlist_entry_provenance_update() FROM PUBLIC;


--
-- Name: FUNCTION guard_workload_credential(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_workload_credential() FROM PUBLIC;


--
-- Name: FUNCTION guard_workload_identity(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_workload_identity() FROM PUBLIC;


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
-- Name: FUNCTION invite_native_staff(p_membership_id uuid, p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_authority_anchor_party_id uuid, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.invite_native_staff(p_membership_id uuid, p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_authority_anchor_party_id uuid, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.invite_native_staff(p_membership_id uuid, p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_authority_anchor_party_id uuid, p_provenance_reference text) TO request_engine_app;


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
-- Name: FUNCTION lock_tenant_staff_root(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.lock_tenant_staff_root() FROM PUBLIC;


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
-- Name: FUNCTION notify_platform_secret_runtime_change(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.notify_platform_secret_runtime_change() FROM PUBLIC;


--
-- Name: FUNCTION principal_is_effective_tenant_controller(p_organization_id uuid, p_principal_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.principal_is_effective_tenant_controller(p_organization_id uuid, p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.principal_is_effective_tenant_controller(p_organization_id uuid, p_principal_id uuid) TO request_platform_control_definer;


--
-- Name: FUNCTION project_managed_oidc_authority(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.project_managed_oidc_authority() FROM PUBLIC;


--
-- Name: FUNCTION provision_agent(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_display_name text, p_purpose text, p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.provision_agent(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_display_name text, p_purpose text, p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.provision_agent(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_display_name text, p_purpose text, p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION provision_integration(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.provision_integration(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.provision_integration(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION provision_integration_state(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.provision_integration_state(p_principal_id uuid, p_binding_id uuid, p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at timestamp with time zone, p_provenance_reference text) FROM PUBLIC;


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
-- Name: FUNCTION read_identity_link_intent(p_intent_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.read_identity_link_intent(p_intent_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.read_identity_link_intent(p_intent_id uuid) TO request_engine_app;


--
-- Name: FUNCTION read_onboarding_identity_facts(p_organization_id uuid); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.read_onboarding_identity_facts(p_organization_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.read_onboarding_identity_facts(p_organization_id uuid) TO request_engine_app;


--
-- Name: FUNCTION reject_immutable_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_immutable_mutation() FROM PUBLIC;


--
-- Name: FUNCTION reject_queue_entry_operator_selection_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_queue_entry_operator_selection_mutation() FROM PUBLIC;


--
-- Name: FUNCTION replace_agent_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.replace_agent_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.replace_agent_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION replace_integration_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.replace_integration_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.replace_integration_authority(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION replace_integration_authority_state(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.replace_integration_authority_state(p_principal_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) FROM PUBLIC;


--
-- Name: FUNCTION replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.replace_staff_authority(p_membership_id uuid, p_expected_authority_revision bigint, p_desired_capabilities text[], p_provenance_reference text) TO request_engine_app;


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
-- Name: FUNCTION revoke_delegation(p_id uuid, p_expected_revision bigint, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.revoke_delegation(p_id uuid, p_expected_revision bigint, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.revoke_delegation(p_id uuid, p_expected_revision bigint, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION revoke_webauthn_credentials_on_disable(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.revoke_webauthn_credentials_on_disable() FROM PUBLIC;


--
-- Name: FUNCTION search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer); Type: ACL; Schema: request_engine; Owner: request_engine_discovery_definer
--

REVOKE ALL ON FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) TO request_engine_discovery;
GRANT ALL ON FUNCTION request_engine.search_discovery_candidates_v2(p_classification_key text, p_origin_latitude double precision, p_origin_longitude double precision, p_radius_meters integer, p_window_start timestamp with time zone, p_window_end timestamp with time zone, p_limit integer) TO request_engine_admin;


--
-- Name: FUNCTION seed_initial_controller_policy(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.seed_initial_controller_policy() FROM PUBLIC;


--
-- Name: FUNCTION seed_root_staff_membership(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.seed_root_staff_membership() FROM PUBLIC;


--
-- Name: FUNCTION seed_root_staff_read_authority(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.seed_root_staff_read_authority() FROM PUBLIC;


--
-- Name: FUNCTION set_integration_status(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.set_integration_status(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.set_integration_status(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION set_integration_status_state(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.set_integration_status_state(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) FROM PUBLIC;


--
-- Name: FUNCTION stamp_shared_capacity_authority_event_context(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.stamp_shared_capacity_authority_event_context() FROM PUBLIC;


--
-- Name: FUNCTION touch_updated_at(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.touch_updated_at() FROM PUBLIC;


--
-- Name: FUNCTION transition_agent_profile(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.transition_agent_profile(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.transition_agent_profile(p_principal_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION transition_identity_binding(p_binding_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.transition_identity_binding(p_binding_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.transition_identity_binding(p_binding_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.transition_staff_membership(p_membership_id uuid, p_expected_revision bigint, p_target_status text, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION upgrade_controller_policy(p_target_principal_id uuid, p_source_policy_key text, p_target_policy_key text, p_expected_authority_revision bigint, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.upgrade_controller_policy(p_target_principal_id uuid, p_source_policy_key text, p_target_policy_key text, p_expected_authority_revision bigint, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.upgrade_controller_policy(p_target_principal_id uuid, p_source_policy_key text, p_target_policy_key text, p_expected_authority_revision bigint, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION upsert_agent_policy(p_agent_principal_id uuid, p_allowed_capabilities text[], p_denied_capabilities text[], p_risk_ceiling text, p_max_mutations_per_minute integer, p_provenance_reference text); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.upsert_agent_policy(p_agent_principal_id uuid, p_allowed_capabilities text[], p_denied_capabilities text[], p_risk_ceiling text, p_max_mutations_per_minute integer, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_engine.upsert_agent_policy(p_agent_principal_id uuid, p_allowed_capabilities text[], p_denied_capabilities text[], p_risk_ceiling text, p_max_mutations_per_minute integer, p_provenance_reference text) TO request_engine_app;


--
-- Name: FUNCTION validate_offering_version_delivery_policy(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.validate_offering_version_delivery_policy() FROM PUBLIC;


--
-- Name: FUNCTION activate_platform_configuration(p_configuration_kind text, p_revision bigint, p_expected_active_revision bigint, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.activate_platform_configuration(p_configuration_kind text, p_revision bigint, p_expected_active_revision bigint, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.activate_platform_configuration(p_configuration_kind text, p_revision bigint, p_expected_active_revision bigint, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION activate_platform_owner_invitation(p_invitation_id uuid, p_principal_id uuid, p_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.activate_platform_owner_invitation(p_invitation_id uuid, p_principal_id uuid, p_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.activate_platform_owner_invitation(p_invitation_id uuid, p_principal_id uuid, p_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION approve_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.approve_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.approve_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION assert_other_platform_controller(p_excluded_principal_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_other_platform_controller(p_excluded_principal_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION assert_other_platform_owner(p_excluded_principal_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_other_platform_owner(p_excluded_principal_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION assert_platform_configuration_actor(p_capability text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_platform_configuration_actor(p_capability text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.assert_platform_configuration_actor(p_capability text) TO request_platform_definer;


--
-- Name: FUNCTION assert_platform_has_controller(); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_platform_has_controller() FROM PUBLIC;


--
-- Name: FUNCTION assert_platform_identity_actor(p_capability text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_platform_identity_actor(p_capability text) FROM PUBLIC;


--
-- Name: FUNCTION assert_platform_owner_actor(p_capability text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_platform_owner_actor(p_capability text) FROM PUBLIC;


--
-- Name: FUNCTION claim_identity_recovery_delivery_tickets(p_limit integer, p_lease_seconds integer); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.claim_identity_recovery_delivery_tickets(p_limit integer, p_lease_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.claim_identity_recovery_delivery_tickets(p_limit integer, p_lease_seconds integer) TO request_engine_worker;


--
-- Name: FUNCTION commit_platform_secret_mutation(p_operation_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.commit_platform_secret_mutation(p_operation_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.commit_platform_secret_mutation(p_operation_id uuid) TO request_platform_control;


--
-- Name: FUNCTION commit_platform_secret_rotation(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_new_backend_version integer, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.commit_platform_secret_rotation(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_new_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;


--
-- Name: FUNCTION complete_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_outcome text, p_error_class text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.complete_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.complete_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_outcome text, p_error_class text) TO request_engine_worker;


--
-- Name: FUNCTION create_identity_recovery_case(p_case_id uuid, p_target_native_identity_id uuid, p_reason_code text, p_evidence_reference text, p_delivery_destination_reference text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.create_identity_recovery_case(p_case_id uuid, p_target_native_identity_id uuid, p_reason_code text, p_evidence_reference text, p_delivery_destination_reference text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.create_identity_recovery_case(p_case_id uuid, p_target_native_identity_id uuid, p_reason_code text, p_evidence_reference text, p_delivery_destination_reference text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION create_platform_owner_invitation(p_invitation_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.create_platform_owner_invitation(p_invitation_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.create_platform_owner_invitation(p_invitation_id uuid, p_token_digest bytea, p_token_fingerprint text, p_expires_at timestamp with time zone, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION create_setup_session(p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_mode text, p_ttl_seconds integer); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.create_setup_session(p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_mode text, p_ttl_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.create_setup_session(p_session_id uuid, p_token_digest bytea, p_token_fingerprint text, p_mode text, p_ttl_seconds integer) TO request_platform_control;


--
-- Name: FUNCTION disable_native_identity(p_native_identity_id uuid, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.disable_native_identity(p_native_identity_id uuid, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.disable_native_identity(p_native_identity_id uuid, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION disable_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.disable_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.disable_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION enroll_platform_owner_invitation(p_token_digest bytea, p_native_identity_id uuid, p_credential_id uuid, p_login_handle text, p_password_verifier text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.enroll_platform_owner_invitation(p_token_digest bytea, p_native_identity_id uuid, p_credential_id uuid, p_login_handle text, p_password_verifier text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.enroll_platform_owner_invitation(p_token_digest bytea, p_native_identity_id uuid, p_credential_id uuid, p_login_handle text, p_password_verifier text) TO request_platform_control;


--
-- Name: FUNCTION establish_root(p_intent_id uuid, p_token_digest bytea, p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_password_verifier text, p_principal_id uuid, p_binding_id uuid); Type: ACL; Schema: request_platform; Owner: request_bootstrap_definer
--

REVOKE ALL ON FUNCTION request_platform.establish_root(p_intent_id uuid, p_token_digest bytea, p_identity_authority_id uuid, p_native_identity_id uuid, p_login_handle text, p_credential_id uuid, p_password_verifier text, p_principal_id uuid, p_binding_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION finalize_instance_claim(p_setup_session_id uuid, p_idempotency_key_digest text, p_intent_digest text, p_claim_provenance text, p_actor_authentication_method text, p_correlation_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.finalize_instance_claim(p_setup_session_id uuid, p_idempotency_key_digest text, p_intent_digest text, p_claim_provenance text, p_actor_authentication_method text, p_correlation_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.finalize_instance_claim(p_setup_session_id uuid, p_idempotency_key_digest text, p_intent_digest text, p_claim_provenance text, p_actor_authentication_method text, p_correlation_id uuid) TO request_platform_control;


--
-- Name: FUNCTION grant_platform_owner_v2_capabilities_on_claim(); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.grant_platform_owner_v2_capabilities_on_claim() FROM PUBLIC;


--
-- Name: FUNCTION issue_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_ticket_id uuid, p_secret_reference text, p_secret_digest text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.issue_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_ticket_id uuid, p_secret_reference text, p_secret_digest text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.issue_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_generation integer, p_recovery_id uuid, p_token_digest bytea, p_token_fingerprint text, p_proof_expires_at timestamp with time zone, p_ticket_id uuid, p_secret_reference text, p_secret_digest text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint); Type: ACL; Schema: request_platform; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_platform.managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.managed_oidc_projection_matches(p_issuer text, p_jwks_uri text, p_audience text, p_revision bigint) TO request_platform_definer;


--
-- Name: FUNCTION mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.mark_platform_secret_backend_applied(p_operation_id uuid, p_applied_backend_version integer) TO request_platform_control;


--
-- Name: FUNCTION native_identity_ready_for_platform_owner(p_identity_authority_id uuid, p_native_identity_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.native_identity_ready_for_platform_owner(p_identity_authority_id uuid, p_native_identity_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION prepare_identity_recovery_issue(p_case_id uuid, p_expected_revision bigint, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.prepare_identity_recovery_issue(p_case_id uuid, p_expected_revision bigint, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.prepare_identity_recovery_issue(p_case_id uuid, p_expected_revision bigint, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION prepare_platform_secret_mutation(p_operation_kind text, p_purpose text, p_backend text, p_binding_id uuid, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.prepare_platform_secret_mutation(p_operation_kind text, p_purpose text, p_backend text, p_binding_id uuid, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.prepare_platform_secret_mutation(p_operation_kind text, p_purpose text, p_backend text, p_binding_id uuid, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION principal_is_effective_platform_controller(p_principal_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.principal_is_effective_platform_controller(p_principal_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION principal_is_effective_platform_owner(p_principal_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.principal_is_effective_platform_owner(p_principal_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION provision_native_organization_root(p_organization_id uuid, p_organization_key text, p_display_name text, p_organization_party_id uuid, p_controller_principal_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.provision_native_organization_root(p_organization_id uuid, p_organization_key text, p_display_name text, p_organization_party_id uuid, p_controller_principal_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.provision_native_organization_root(p_organization_id uuid, p_organization_key text, p_display_name text, p_organization_party_id uuid, p_controller_principal_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) TO request_platform_control;


--
-- Name: FUNCTION provision_native_platform_owner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.provision_native_platform_owner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;


--
-- Name: FUNCTION provision_native_recovery_operator(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.provision_native_recovery_operator(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.provision_native_recovery_operator(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) TO request_platform_control;


--
-- Name: FUNCTION provision_native_tenant_provisioner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.provision_native_tenant_provisioner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.provision_native_tenant_provisioner(p_principal_id uuid, p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, p_provenance_reference text) TO request_platform_control;


--
-- Name: FUNCTION provision_tenant_provisioner(p_new_principal_id uuid, p_external_subject text, p_provenance_reference text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.provision_tenant_provisioner(p_new_principal_id uuid, p_external_subject text, p_provenance_reference text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.provision_tenant_provisioner(p_new_principal_id uuid, p_external_subject text, p_provenance_reference text) TO request_platform_control;


--
-- Name: FUNCTION read_active_appointment_option_signing_keyring(); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_active_appointment_option_signing_keyring() FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_active_appointment_option_signing_keyring() TO request_engine_app;


--
-- Name: FUNCTION read_active_platform_runtime_configuration(p_configuration_kind text); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_active_platform_runtime_configuration(p_configuration_kind text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_active_platform_runtime_configuration(p_configuration_kind text) TO request_engine_worker;
GRANT ALL ON FUNCTION request_platform.read_active_platform_runtime_configuration(p_configuration_kind text) TO request_platform_control;


--
-- Name: FUNCTION read_claim_readiness(p_setup_session_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_claim_readiness(p_setup_session_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_claim_readiness(p_setup_session_id uuid) TO request_platform_control;


--
-- Name: FUNCTION read_identity_recovery_cases(p_case_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_identity_recovery_cases(p_case_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


--
-- Name: FUNCTION read_installation_claim(p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_installation_claim(p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_installation_claim(p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION read_installation_claim_intent_digest(p_idempotency_key_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_installation_claim_intent_digest(p_idempotency_key_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_installation_claim_intent_digest(p_idempotency_key_digest text) TO request_platform_control;


--
-- Name: FUNCTION read_native_identities(p_identity_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_native_identities(p_identity_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


--
-- Name: FUNCTION read_platform_configuration_revisions(p_configuration_kind text); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_configuration_revisions(p_configuration_kind text) FROM PUBLIC;


--
-- Name: FUNCTION read_platform_instance(); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_instance() FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_platform_instance() TO request_platform_control;


--
-- Name: FUNCTION read_platform_provider_candidate(p_configuration_kind text, p_revision bigint, p_capability_key text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_provider_candidate(p_configuration_kind text, p_revision bigint, p_capability_key text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_platform_provider_candidate(p_configuration_kind text, p_revision bigint, p_capability_key text) TO request_platform_control;


--
-- Name: FUNCTION read_platform_provisioners(p_principal_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_provisioners(p_principal_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


--
-- Name: FUNCTION read_platform_readiness(); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_readiness() FROM PUBLIC;


--
-- Name: FUNCTION read_platform_runtime_configuration_revision(p_configuration_kind text, p_revision bigint); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_runtime_configuration_revision(p_configuration_kind text, p_revision bigint) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_platform_runtime_configuration_revision(p_configuration_kind text, p_revision bigint) TO request_engine_worker;


--
-- Name: FUNCTION read_platform_secret_binding(p_binding_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_secret_binding(p_binding_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION read_principal_authority(p_principal_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_principal_authority(p_principal_id uuid) FROM PUBLIC;


--
-- Name: FUNCTION read_setup_pending_identity(p_setup_session_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_setup_pending_identity(p_setup_session_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_setup_pending_identity(p_setup_session_id uuid) TO request_platform_control;


--
-- Name: FUNCTION read_setup_session(p_token_digest bytea); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_setup_session(p_token_digest bytea) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.read_setup_session(p_token_digest bytea) TO request_platform_control;


--
-- Name: FUNCTION record_platform_provider_test(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_outcome text, p_detail_code text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.record_platform_provider_test(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_outcome text, p_detail_code text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.record_platform_provider_test(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_outcome text, p_detail_code text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION record_platform_secret_binding(p_purpose text, p_backend text, p_secret_id uuid, p_backend_version integer, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.record_platform_secret_binding(p_purpose text, p_backend text, p_secret_id uuid, p_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;


--
-- Name: FUNCTION renew_identity_recovery_delivery_ticket_lease(p_ticket_id uuid, p_claim_token uuid, p_extension_seconds integer); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.renew_identity_recovery_delivery_ticket_lease(p_ticket_id uuid, p_claim_token uuid, p_extension_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.renew_identity_recovery_delivery_ticket_lease(p_ticket_id uuid, p_claim_token uuid, p_extension_seconds integer) TO request_engine_worker;


--
-- Name: FUNCTION resolve_platform_provider_secret(p_binding_id uuid, p_capability_key text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.resolve_platform_provider_secret(p_binding_id uuid, p_capability_key text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.resolve_platform_provider_secret(p_binding_id uuid, p_capability_key text) TO request_platform_control;


--
-- Name: FUNCTION retry_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.retry_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.retry_identity_recovery_delivery_ticket(p_ticket_id uuid, p_claim_token uuid, p_delay_seconds integer, p_error_class text) TO request_engine_worker;


--
-- Name: FUNCTION revoke_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.revoke_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.revoke_identity_recovery_case(p_case_id uuid, p_expected_revision bigint, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION revoke_platform_owner_invitation(p_invitation_id uuid, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.revoke_platform_owner_invitation(p_invitation_id uuid, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.revoke_platform_owner_invitation(p_invitation_id uuid, p_reason_code text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION revoke_platform_secret_binding(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.revoke_platform_secret_binding(p_binding_id uuid, p_expected_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;


--
-- Name: FUNCTION select_initial_controller_policy(p_policy_key text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.select_initial_controller_policy(p_policy_key text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.select_initial_controller_policy(p_policy_key text) TO request_platform_control;


--
-- Name: FUNCTION set_setup_pending_identity(p_native_identity_id uuid, p_setup_session_id uuid, p_login_handle text, p_verifier text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.set_setup_pending_identity(p_native_identity_id uuid, p_setup_session_id uuid, p_login_handle text, p_verifier text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.set_setup_pending_identity(p_native_identity_id uuid, p_setup_session_id uuid, p_login_handle text, p_verifier text) TO request_platform_control;


--
-- Name: FUNCTION stage_platform_configuration(p_configuration_kind text, p_provider_kind text, p_configuration jsonb, p_secret_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.stage_platform_configuration(p_configuration_kind text, p_provider_kind text, p_configuration jsonb, p_secret_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.stage_platform_configuration(p_configuration_kind text, p_provider_kind text, p_configuration jsonb, p_secret_binding_id uuid, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION transition_native_platform_owner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.transition_native_platform_owner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.transition_native_platform_owner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION transition_native_platform_provisioner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.transition_native_platform_provisioner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.transition_native_platform_provisioner(p_principal_id uuid, p_action text, p_expected_revision bigint, p_reason_code text, p_external_case_reference text, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION validate_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.validate_platform_configuration(p_configuration_kind text, p_revision bigint, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;


--
-- Name: FUNCTION validate_platform_configuration_provider(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.validate_platform_configuration_provider(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.validate_platform_configuration_provider(p_configuration_kind text, p_revision bigint, p_expected_binding_revision bigint, p_expected_backend_version integer, p_idempotency_key_digest text, p_intent_digest text) TO request_platform_control;


--
-- Name: FUNCTION integrations(p_principal_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_read.integrations(p_principal_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;
GRANT ALL ON FUNCTION request_read.integrations(p_principal_id uuid, p_after uuid, p_limit integer) TO request_engine_app;


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
-- Name: TABLE agent_budget_windows; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.agent_budget_windows TO request_engine_app;


--
-- Name: TABLE agent_policies; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.agent_policies TO request_engine_app;


--
-- Name: TABLE agent_profiles; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.agent_profiles TO request_engine_app;


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
-- Name: TABLE delegations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.delegations TO request_engine_app;


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
-- Name: COLUMN identity_authorities.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.identity_authorities TO request_bootstrap_definer;
GRANT SELECT(id) ON TABLE request_engine.identity_authorities TO request_platform_control_definer;


--
-- Name: COLUMN identity_authorities.kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(kind) ON TABLE request_engine.identity_authorities TO request_bootstrap_definer;
GRANT SELECT(kind) ON TABLE request_engine.identity_authorities TO request_platform_control_definer;


--
-- Name: COLUMN identity_authorities.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.identity_authorities TO request_bootstrap_definer;
GRANT SELECT(status) ON TABLE request_engine.identity_authorities TO request_platform_control_definer;


--
-- Name: TABLE identity_bindings; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.identity_bindings TO request_engine_app;


--
-- Name: COLUMN identity_bindings.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.identity_bindings TO request_bootstrap_definer;
GRANT SELECT(id),INSERT(id) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(id) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id),INSERT(organization_id) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(organization_id) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(principal_id) ON TABLE request_engine.identity_bindings TO request_bootstrap_definer;
GRANT SELECT(principal_id),INSERT(principal_id) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(principal_id) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.principal_plane; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(principal_plane) ON TABLE request_engine.identity_bindings TO request_bootstrap_definer;
GRANT SELECT(principal_plane),INSERT(principal_plane) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(principal_plane) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.identity_authority_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(identity_authority_id) ON TABLE request_engine.identity_bindings TO request_bootstrap_definer;
GRANT SELECT(identity_authority_id),INSERT(identity_authority_id) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(identity_authority_id) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.subject_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(subject_id) ON TABLE request_engine.identity_bindings TO request_bootstrap_definer;
GRANT SELECT(subject_id),INSERT(subject_id) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(subject_id) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(status) ON TABLE request_engine.identity_bindings TO request_bootstrap_definer;
GRANT SELECT(status),INSERT(status),UPDATE(status) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;
GRANT SELECT(status) ON TABLE request_engine.identity_bindings TO request_platform_definer;


--
-- Name: COLUMN identity_bindings.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision) ON TABLE request_engine.identity_bindings TO request_platform_definer;
GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;


--
-- Name: COLUMN identity_bindings.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE request_engine.identity_bindings TO request_platform_control_definer;


--
-- Name: TABLE identity_exchange_candidates; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT ALL ON TABLE request_engine.identity_exchange_candidates TO request_engine_admin;


--
-- Name: COLUMN identity_recovery_cases.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(id) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.target_native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(target_native_identity_id),INSERT(target_native_identity_id) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(target_native_identity_id) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.requester_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(requester_principal_id),INSERT(requester_principal_id) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.approver_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(approver_principal_id),UPDATE(approver_principal_id) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),INSERT(status),UPDATE(status) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(status) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.delivery_status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(delivery_status),UPDATE(delivery_status) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(delivery_status) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.reason_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(reason_code),INSERT(reason_code) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.evidence_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(evidence_reference),INSERT(evidence_reference) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.delivery_destination_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(delivery_destination_reference),INSERT(delivery_destination_reference) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.recovery_intent_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(recovery_intent_id),UPDATE(recovery_intent_id) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.issuance_generation; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(issuance_generation),UPDATE(issuance_generation) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(issuance_generation) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.approval_expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(approval_expires_at),UPDATE(approval_expires_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(approval_expires_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.proof_expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(proof_expires_at),UPDATE(proof_expires_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(proof_expires_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(revision) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(created_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.updated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(updated_at),UPDATE(updated_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_cases.approved_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(approved_at),UPDATE(approved_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(approved_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.issued_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(issued_at),UPDATE(issued_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(issued_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(consumed_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(consumed_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revoked_at),UPDATE(revoked_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;
GRANT SELECT(revoked_at) ON TABLE request_engine.identity_recovery_cases TO request_platform_definer;


--
-- Name: COLUMN identity_recovery_cases.revoke_reason_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revoke_reason_code),UPDATE(revoke_reason_code) ON TABLE request_engine.identity_recovery_cases TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.case_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(case_id),INSERT(case_id) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.generation; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(generation),INSERT(generation) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),INSERT(status),UPDATE(status) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.secret_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(secret_reference),INSERT(secret_reference) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.secret_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(secret_digest),INSERT(secret_digest) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.destination_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(destination_reference),INSERT(destination_reference) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at),INSERT(expires_at) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.claim_token; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(claim_token),UPDATE(claim_token) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.lease_until; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(lease_until),UPDATE(lease_until) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.attempt_count; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(attempt_count),UPDATE(attempt_count) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.max_attempts; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(max_attempts) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.next_attempt_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(next_attempt_at),UPDATE(next_attempt_at) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.last_error_class; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(last_error_class),UPDATE(last_error_class) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.updated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(updated_at),UPDATE(updated_at) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_delivery_tickets.delivered_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(delivered_at),UPDATE(delivered_at) ON TABLE request_engine.identity_recovery_delivery_tickets TO request_platform_control_definer;


--
-- Name: TABLE identity_recovery_issuance_reservations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT DELETE ON TABLE request_engine.identity_recovery_issuance_reservations TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_issuance_reservations.case_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(case_id),INSERT(case_id) ON TABLE request_engine.identity_recovery_issuance_reservations TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_issuance_reservations.generation; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(generation),INSERT(generation) ON TABLE request_engine.identity_recovery_issuance_reservations TO request_platform_control_definer;


--
-- Name: COLUMN identity_recovery_issuance_reservations.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.identity_recovery_issuance_reservations TO request_platform_control_definer;


--
-- Name: COLUMN initial_controller_policies.policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(policy_key) ON TABLE request_engine.initial_controller_policies TO request_platform_control_definer;


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
-- Name: COLUMN native_credentials.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.native_credentials TO request_bootstrap_definer;
GRANT INSERT(id) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_credentials.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(native_identity_id) ON TABLE request_engine.native_credentials TO request_bootstrap_definer;
GRANT SELECT(native_identity_id),INSERT(native_identity_id) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_credentials.kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(kind) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_credentials.verifier; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(verifier) ON TABLE request_engine.native_credentials TO request_bootstrap_definer;
GRANT INSERT(verifier) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_credentials.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_credentials.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_credentials.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE request_engine.native_credentials TO request_platform_control_definer;


--
-- Name: COLUMN native_identities.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.native_identities TO request_bootstrap_definer;
GRANT SELECT(id),INSERT(id) ON TABLE request_engine.native_identities TO request_platform_control_definer;
GRANT SELECT(id) ON TABLE request_engine.native_identities TO request_platform_definer;


--
-- Name: COLUMN native_identities.identity_authority_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(identity_authority_id) ON TABLE request_engine.native_identities TO request_bootstrap_definer;
GRANT SELECT(identity_authority_id),INSERT(identity_authority_id) ON TABLE request_engine.native_identities TO request_platform_control_definer;
GRANT SELECT(identity_authority_id) ON TABLE request_engine.native_identities TO request_platform_definer;


--
-- Name: COLUMN native_identities.login_handle; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(login_handle) ON TABLE request_engine.native_identities TO request_bootstrap_definer;
GRANT INSERT(login_handle) ON TABLE request_engine.native_identities TO request_platform_control_definer;


--
-- Name: COLUMN native_identities.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.native_identities TO request_platform_control_definer;
GRANT SELECT(status) ON TABLE request_engine.native_identities TO request_platform_definer;


--
-- Name: COLUMN native_identities.session_epoch; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(session_epoch),UPDATE(session_epoch) ON TABLE request_engine.native_identities TO request_platform_control_definer;


--
-- Name: COLUMN native_identities.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision) ON TABLE request_engine.native_identities TO request_platform_definer;
GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.native_identities TO request_platform_control_definer;


--
-- Name: COLUMN native_identities.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.native_identities TO request_platform_definer;


--
-- Name: COLUMN native_identities.updated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(updated_at),UPDATE(updated_at) ON TABLE request_engine.native_identities TO request_platform_control_definer;


--
-- Name: COLUMN native_identities.disabled_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(disabled_at) ON TABLE request_engine.native_identities TO request_platform_definer;
GRANT SELECT(disabled_at),UPDATE(disabled_at) ON TABLE request_engine.native_identities TO request_platform_control_definer;


--
-- Name: COLUMN native_recovery_intents.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.native_recovery_intents TO request_platform_control_definer;


--
-- Name: COLUMN native_recovery_intents.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id) ON TABLE request_engine.native_recovery_intents TO request_platform_control_definer;


--
-- Name: COLUMN native_recovery_intents.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.native_recovery_intents TO request_platform_control_definer;


--
-- Name: COLUMN native_recovery_intents.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE request_engine.native_recovery_intents TO request_platform_control_definer;


--
-- Name: COLUMN native_sessions.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id) ON TABLE request_engine.native_sessions TO request_platform_control_definer;


--
-- Name: COLUMN native_sessions.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.native_sessions TO request_platform_control_definer;


--
-- Name: COLUMN native_sessions.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE request_engine.native_sessions TO request_platform_control_definer;


--
-- Name: COLUMN native_sessions.revocation_reason; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revocation_reason) ON TABLE request_engine.native_sessions TO request_platform_control_definer;


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
