GRANT ALL ON FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) TO request_engine_app;
GRANT ALL ON FUNCTION request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[]) TO request_engine_admin;


--
-- Name: FUNCTION lock_staff_command_authority(p_capability text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_staff_command_authority(p_capability text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_staff_command_authority(p_capability text) TO request_engine_app;


--
-- Name: TABLE staff_invitations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.staff_invitations TO request_engine_app;


--
-- Name: COLUMN staff_invitations.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.staff_invitations TO request_platform_definer;


--
-- Name: COLUMN staff_invitations.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id) ON TABLE request_engine.staff_invitations TO request_platform_definer;


--
-- Name: COLUMN staff_invitations.token_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(token_digest) ON TABLE request_engine.staff_invitations TO request_platform_definer;


--
-- Name: FUNCTION lock_staff_invitation_acceptance(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_staff_invitation_acceptance(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_staff_invitation_acceptance(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid) TO request_engine_app;


--
-- Name: FUNCTION lock_staff_invitation_admin(p_id uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_staff_invitation_admin(p_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_staff_invitation_admin(p_id uuid) TO request_engine_app;


--
-- Name: FUNCTION lock_staff_member_profile(p_membership uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.lock_staff_member_profile(p_membership uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.lock_staff_member_profile(p_membership uuid) TO request_engine_app;


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
-- Name: FUNCTION materialize_invited_staff(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid, p_membership uuid, p_principal uuid, p_binding uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.materialize_invited_staff(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid, p_membership uuid, p_principal uuid, p_binding uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.materialize_invited_staff(p_id uuid, p_digest text, p_authority uuid, p_identity uuid, p_session uuid, p_membership uuid, p_principal uuid, p_binding uuid) TO request_engine_app;


--
-- Name: FUNCTION read_controller_policy_adoption(p_request_id uuid, p_binding_id uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.read_controller_policy_adoption(p_request_id uuid, p_binding_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.read_controller_policy_adoption(p_request_id uuid, p_binding_id uuid) TO request_engine_app;


--
-- Name: FUNCTION record_temporary_proof_retention(p_backend uuid, p_mount text, p_reference text, p_version bigint, p_created timestamp with time zone, p_deletion timestamp with time zone, p_expiry timestamp with time zone); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.record_temporary_proof_retention(p_backend uuid, p_mount text, p_reference text, p_version bigint, p_created timestamp with time zone, p_deletion timestamp with time zone, p_expiry timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.record_temporary_proof_retention(p_backend uuid, p_mount text, p_reference text, p_version bigint, p_created timestamp with time zone, p_deletion timestamp with time zone, p_expiry timestamp with time zone) TO request_retention_recorder;


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
-- Name: FUNCTION request_controller_policy_adoption(p_binding_id uuid, p_expected_authority_revision bigint, p_reason text, p_key_digest text, p_intent_digest text, p_correlation_id uuid); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.request_controller_policy_adoption(p_binding_id uuid, p_expected_authority_revision bigint, p_reason text, p_key_digest text, p_intent_digest text, p_correlation_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.request_controller_policy_adoption(p_binding_id uuid, p_expected_authority_revision bigint, p_reason text, p_key_digest text, p_intent_digest text, p_correlation_id uuid) TO request_engine_app;


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
-- Name: FUNCTION rotate_agent_credential(p_target uuid, p_expected bigint, p_credential uuid, p_digest bytea, p_fingerprint text, p_expiry timestamp with time zone); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.rotate_agent_credential(p_target uuid, p_expected bigint, p_credential uuid, p_digest bytea, p_fingerprint text, p_expiry timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.rotate_agent_credential(p_target uuid, p_expected bigint, p_credential uuid, p_digest bytea, p_fingerprint text, p_expiry timestamp with time zone) TO request_engine_app;


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
-- Name: FUNCTION withdraw_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_binding_id uuid, p_key_digest text, p_intent_digest text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.withdraw_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_binding_id uuid, p_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.withdraw_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_binding_id uuid, p_key_digest text, p_intent_digest text) TO request_engine_app;


--
-- Name: FUNCTION write_staff_member_profile(p_membership uuid, p_expected bigint, p_name text, p_provenance text); Type: ACL; Schema: request_cmd; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_cmd.write_staff_member_profile(p_membership uuid, p_expected bigint, p_name text, p_provenance text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_cmd.write_staff_member_profile(p_membership uuid, p_expected bigint, p_name text, p_provenance text) TO request_engine_app;


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
-- Name: FUNCTION adopt_platform_owner_v4(); Type: ACL; Schema: request_engine; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_engine.adopt_platform_owner_v4() FROM PUBLIC;


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
-- Name: FUNCTION assert_temporary_proof_worker(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.assert_temporary_proof_worker() FROM PUBLIC;


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
-- Name: FUNCTION guard_staff_invitation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_staff_invitation() FROM PUBLIC;


--
-- Name: FUNCTION guard_staff_invitation_proposal(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.guard_staff_invitation_proposal() FROM PUBLIC;


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
GRANT ALL ON FUNCTION request_engine.lock_tenant_staff_root() TO request_platform_control_definer;


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
-- Name: FUNCTION notify_outbox_change(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.notify_outbox_change() FROM PUBLIC;


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
-- Name: FUNCTION reject_native_identity_provision_receipt_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_native_identity_provision_receipt_mutation() FROM PUBLIC;


--
-- Name: FUNCTION reject_queue_entry_operator_selection_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_queue_entry_operator_selection_mutation() FROM PUBLIC;


--
-- Name: FUNCTION reject_temporary_proof_receipt_mutation(); Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_engine.reject_temporary_proof_receipt_mutation() FROM PUBLIC;


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
-- Name: FUNCTION apply_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_key_digest text, p_intent_digest text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.apply_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_key_digest text, p_intent_digest text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.apply_controller_policy_adoption(p_request_id uuid, p_expected_revision bigint, p_key_digest text, p_intent_digest text) TO request_platform_control;


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
-- Name: FUNCTION assert_owner_read_actor(); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.assert_owner_read_actor() FROM PUBLIC;


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
-- Name: FUNCTION list_controller_policy_adoptions(p_after uuid, p_limit integer, p_request_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.list_controller_policy_adoptions(p_after uuid, p_limit integer, p_request_id uuid) FROM PUBLIC;


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
-- Name: FUNCTION provision_native_identity(p_authority uuid, p_identity uuid, p_login text, p_credential uuid, p_verifier text, p_key text, p_intent text); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.provision_native_identity(p_authority uuid, p_identity uuid, p_login text, p_credential uuid, p_verifier text, p_key text, p_intent text) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.provision_native_identity(p_authority uuid, p_identity uuid, p_login text, p_credential uuid, p_verifier text, p_key text, p_intent text) TO request_platform_control;


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
-- Name: FUNCTION read_native_identity_profiles(p_identity_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_native_identity_profiles(p_identity_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


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
-- Name: FUNCTION read_platform_organizations(p_organization_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_organizations(p_organization_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


--
-- Name: FUNCTION read_platform_owner_invitations(p_invitation_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_owner_invitations(p_invitation_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


--
-- Name: FUNCTION read_platform_owners(p_principal_id uuid, p_after uuid, p_limit integer); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.read_platform_owners(p_principal_id uuid, p_after uuid, p_limit integer) FROM PUBLIC;


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
-- Name: FUNCTION review_controller_policy_adoption(p_request_id uuid); Type: ACL; Schema: request_platform; Owner: request_platform_control_definer
--

REVOKE ALL ON FUNCTION request_platform.review_controller_policy_adoption(p_request_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_platform.review_controller_policy_adoption(p_request_id uuid) TO request_platform_control;


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
-- Name: FUNCTION agent_credential_metadata(p_target uuid); Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_read.agent_credential_metadata(p_target uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_read.agent_credential_metadata(p_target uuid) TO request_engine_app;


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
-- Name: FUNCTION staff_controller_is_effective(p_principal_id uuid); Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

REVOKE ALL ON FUNCTION request_read.staff_controller_is_effective(p_principal_id uuid) FROM PUBLIC;
GRANT ALL ON FUNCTION request_read.staff_controller_is_effective(p_principal_id uuid) TO request_engine_app;


--
-- Name: TABLE outbox_messages; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.outbox_messages TO request_engine_app;
GRANT ALL ON TABLE request_engine.outbox_messages TO request_engine_admin;


--
-- Name: COLUMN outbox_messages.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.outbox_messages TO request_operator_metrics_definer;


--
-- Name: COLUMN outbox_messages.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.outbox_messages TO request_operator_metrics_definer;


--
-- Name: TABLE provider_events; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.provider_events TO request_engine_app;
GRANT ALL ON TABLE request_engine.provider_events TO request_engine_admin;


--
-- Name: COLUMN provider_events.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.provider_events TO request_operator_metrics_definer;


--
-- Name: COLUMN provider_events.received_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(received_at) ON TABLE request_engine.provider_events TO request_operator_metrics_definer;


--
-- Name: COLUMN provider_events.updated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(updated_at) ON TABLE request_engine.provider_events TO request_operator_metrics_definer;


--
-- Name: TABLE scheduled_actions; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.scheduled_actions TO request_engine_app;
GRANT ALL ON TABLE request_engine.scheduled_actions TO request_engine_admin;


--
-- Name: COLUMN scheduled_actions.execute_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(execute_at) ON TABLE request_engine.scheduled_actions TO request_operator_metrics_definer;


--
-- Name: COLUMN scheduled_actions.next_attempt_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(next_attempt_at) ON TABLE request_engine.scheduled_actions TO request_operator_metrics_definer;


--
-- Name: COLUMN scheduled_actions.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.scheduled_actions TO request_operator_metrics_definer;


--
-- Name: COLUMN scheduled_actions.lease_until; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(lease_until) ON TABLE request_engine.scheduled_actions TO request_operator_metrics_definer;


--
-- Name: COLUMN scheduled_actions.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.scheduled_actions TO request_operator_metrics_definer;


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
-- Name: COLUMN communication_deliveries.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.communication_deliveries TO request_operator_metrics_definer;


--
-- Name: COLUMN communication_deliveries.updated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(updated_at) ON TABLE request_engine.communication_deliveries TO request_operator_metrics_definer;


--
-- Name: TABLE communication_escalations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.communication_escalations TO request_engine_app;
GRANT ALL ON TABLE request_engine.communication_escalations TO request_engine_admin;


--
