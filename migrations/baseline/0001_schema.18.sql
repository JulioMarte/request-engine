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
-- Name: COLUMN recovery_code_sets.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.recovery_code_sets TO request_platform_control_definer;


--
-- Name: COLUMN recovery_code_sets.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),UPDATE(native_identity_id) ON TABLE request_engine.recovery_code_sets TO request_platform_control_definer;


--
-- Name: COLUMN recovery_code_sets.setup_session_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(setup_session_id),UPDATE(setup_session_id) ON TABLE request_engine.recovery_code_sets TO request_platform_control_definer;


--
-- Name: COLUMN recovery_code_sets.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.recovery_code_sets TO request_platform_control_definer;


--
-- Name: COLUMN recovery_codes.set_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(set_id) ON TABLE request_engine.recovery_codes TO request_platform_control_definer;


--
-- Name: COLUMN recovery_codes.used_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(used_at) ON TABLE request_engine.recovery_codes TO request_platform_control_definer;


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
-- Name: COLUMN representations.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(organization_id) ON TABLE request_engine.representations TO request_platform_control_definer;


--
-- Name: COLUMN representations.principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(principal_id) ON TABLE request_engine.representations TO request_platform_control_definer;


--
-- Name: COLUMN representations.represented_party_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(represented_party_id) ON TABLE request_engine.representations TO request_platform_control_definer;


--
-- Name: COLUMN representations.scope_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(scope_key) ON TABLE request_engine.representations TO request_platform_control_definer;


--
-- Name: COLUMN representations.authority_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(authority_kind) ON TABLE request_engine.representations TO request_platform_control_definer;


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
-- Name: COLUMN setup_pending_identity.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_identity.setup_session_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(setup_session_id),INSERT(setup_session_id) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_identity.login_handle; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(login_handle),INSERT(login_handle),UPDATE(login_handle) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_identity.verifier; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(verifier),INSERT(verifier),UPDATE(verifier) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_identity.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_identity.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_identity.promoted_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(promoted_at),UPDATE(promoted_at) ON TABLE request_engine.setup_pending_identity TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.setup_session_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(setup_session_id),INSERT(setup_session_id) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.credential_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(credential_id),INSERT(credential_id) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.public_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(public_key),INSERT(public_key) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.sign_count; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(sign_count),INSERT(sign_count) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.aaguid; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(aaguid),INSERT(aaguid) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.backup_eligible; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(backup_eligible),INSERT(backup_eligible) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.backup_state; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(backup_state),INSERT(backup_state) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.user_verified; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(user_verified),INSERT(user_verified) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_pending_webauthn_credential.promoted_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(promoted_at) ON TABLE request_engine.setup_pending_webauthn_credential TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.instance_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(instance_id),INSERT(instance_id) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.token_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(token_digest),INSERT(token_digest) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.token_fingerprint; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(token_fingerprint),INSERT(token_fingerprint) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.mode; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(mode),INSERT(mode) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at),INSERT(expires_at) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(consumed_at),UPDATE(consumed_at) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


--
-- Name: COLUMN setup_sessions.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revoked_at) ON TABLE request_engine.setup_sessions TO request_platform_control_definer;


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
-- Name: TABLE staff_invitation_deliveries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.staff_invitation_deliveries TO request_engine_app;


--
-- Name: TABLE staff_invitation_proposals; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.staff_invitation_proposals TO request_engine_app;


--
-- Name: COLUMN staff_member_profiles.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id) ON TABLE request_engine.staff_member_profiles TO request_engine_app;


--
-- Name: COLUMN staff_member_profiles.membership_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(membership_id) ON TABLE request_engine.staff_member_profiles TO request_engine_app;


--
-- Name: COLUMN staff_member_profiles.display_name; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(display_name) ON TABLE request_engine.staff_member_profiles TO request_engine_app;


--
-- Name: COLUMN staff_member_profiles.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision) ON TABLE request_engine.staff_member_profiles TO request_engine_app;


--
-- Name: TABLE staff_memberships; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.staff_memberships TO request_engine_app;


--
-- Name: COLUMN staff_memberships.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.staff_memberships TO request_platform_definer;
GRANT SELECT(id),UPDATE(id) ON TABLE request_engine.staff_memberships TO request_platform_control_definer;


--
-- Name: COLUMN staff_memberships.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id) ON TABLE request_engine.staff_memberships TO request_platform_definer;
GRANT SELECT(organization_id) ON TABLE request_engine.staff_memberships TO request_platform_control_definer;


--
-- Name: COLUMN staff_memberships.principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_id) ON TABLE request_engine.staff_memberships TO request_platform_definer;
GRANT SELECT(principal_id) ON TABLE request_engine.staff_memberships TO request_platform_control_definer;


--
-- Name: COLUMN staff_memberships.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.staff_memberships TO request_platform_definer;
GRANT SELECT(status) ON TABLE request_engine.staff_memberships TO request_platform_control_definer;


--
-- Name: TABLE waitlist_entries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.waitlist_entries TO request_engine_app;
GRANT ALL ON TABLE request_engine.waitlist_entries TO request_engine_admin;


--
-- Name: TABLE webauthn_challenges; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT DELETE ON TABLE request_engine.webauthn_challenges TO request_webauthn_retention_definer;


--
-- Name: COLUMN webauthn_challenges.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),UPDATE(id) ON TABLE request_engine.webauthn_challenges TO request_webauthn_retention_definer;


--
-- Name: COLUMN webauthn_challenges.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.webauthn_challenges TO request_webauthn_retention_definer;


--
-- Name: COLUMN webauthn_challenges.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at) ON TABLE request_engine.webauthn_challenges TO request_webauthn_retention_definer;


--
-- Name: COLUMN webauthn_challenges.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(consumed_at) ON TABLE request_engine.webauthn_challenges TO request_webauthn_retention_definer;


--
-- Name: COLUMN webauthn_credentials.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),INSERT(native_identity_id) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.credential_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(credential_id) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.public_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(public_key) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.sign_count; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(sign_count) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.aaguid; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(aaguid) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.backup_eligible; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(backup_eligible) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.backup_state; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(backup_state) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.user_verified; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(user_verified),INSERT(user_verified) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: COLUMN webauthn_credentials.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.webauthn_credentials TO request_platform_control_definer;


--
-- Name: TABLE business_info_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.business_info_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.business_info_v1 TO request_engine_admin;


--
-- Name: TABLE change_feed_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.change_feed_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.change_feed_v1 TO request_engine_admin;


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
-- Name: TABLE reservation_calendar_v1; Type: ACL; Schema: request_read; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_read.reservation_calendar_v1 TO request_engine_app;
GRANT SELECT ON TABLE request_read.reservation_calendar_v1 TO request_engine_admin;


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


