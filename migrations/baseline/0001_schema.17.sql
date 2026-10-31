-- Name: TABLE communication_tasks; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.communication_tasks TO request_engine_app;
GRANT ALL ON TABLE request_engine.communication_tasks TO request_engine_admin;


--
-- Name: COLUMN controller_policy_adoption_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.request_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(request_id),INSERT(request_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id),INSERT(organization_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.controller_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_principal_id),INSERT(controller_principal_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.controller_binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(controller_binding_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.platform_approver_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(platform_approver_principal_id),INSERT(platform_approver_principal_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.source_policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(source_policy_key),INSERT(source_policy_key) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.target_policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(target_policy_key),INSERT(target_policy_key) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.authority_revision_before; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(authority_revision_before),INSERT(authority_revision_before) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.authority_revision_after; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(authority_revision_after),INSERT(authority_revision_after) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.added_capabilities; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(added_capabilities),INSERT(added_capabilities) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.platform_authority_revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(platform_authority_revision),INSERT(platform_authority_revision) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(correlation_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.applied_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(applied_at) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.controller_native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_native_identity_id),INSERT(controller_native_identity_id) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_facts.controller_recovery_epoch; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_recovery_epoch),INSERT(controller_recovery_epoch) ON TABLE request_engine.controller_policy_adoption_facts TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(organization_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(organization_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.controller_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_principal_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(controller_principal_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(controller_principal_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.controller_binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_binding_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(controller_binding_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.source_policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(source_policy_key) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(source_policy_key) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(source_policy_key) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.target_policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(target_policy_key) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(target_policy_key) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(target_policy_key) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.expected_authority_revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expected_authority_revision) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(expected_authority_revision) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(expected_authority_revision) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.reason; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(reason) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(reason) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(status) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(revision) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(created_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(created_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT SELECT(expires_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_definer;
GRANT SELECT(expires_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.closed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(closed_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_engine_app;
GRANT UPDATE(closed_at) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.controller_native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_native_identity_id) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


--
-- Name: COLUMN controller_policy_adoption_requests.controller_recovery_epoch; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_recovery_epoch) ON TABLE request_engine.controller_policy_adoption_requests TO request_platform_control_definer;


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
-- Name: COLUMN http_auth_admission_state.singleton; Type: ACL; Schema: request_engine; Owner: postgres
--

GRANT SELECT(singleton) ON TABLE request_engine.http_auth_admission_state TO request_http_admission_definer;


--
-- Name: COLUMN http_auth_admission_state.configured_limit; Type: ACL; Schema: request_engine; Owner: postgres
--

GRANT SELECT(configured_limit),UPDATE(configured_limit) ON TABLE request_engine.http_auth_admission_state TO request_http_admission_definer;


--
-- Name: COLUMN http_auth_admission_state.attempts; Type: ACL; Schema: request_engine; Owner: postgres
--

GRANT SELECT(attempts),UPDATE(attempts) ON TABLE request_engine.http_auth_admission_state TO request_http_admission_definer;


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
GRANT SELECT(id) ON TABLE request_engine.identity_authorities TO request_platform_definer;


--
-- Name: COLUMN identity_authorities.kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(kind) ON TABLE request_engine.identity_authorities TO request_bootstrap_definer;
GRANT SELECT(kind) ON TABLE request_engine.identity_authorities TO request_platform_control_definer;
GRANT SELECT(kind) ON TABLE request_engine.identity_authorities TO request_platform_definer;


--
-- Name: COLUMN identity_authorities.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.identity_authorities TO request_bootstrap_definer;
GRANT SELECT(status) ON TABLE request_engine.identity_authorities TO request_platform_control_definer;
GRANT SELECT(status) ON TABLE request_engine.identity_authorities TO request_platform_definer;


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
-- Name: COLUMN initial_controller_policies.grants; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(grants) ON TABLE request_engine.initial_controller_policies TO request_platform_control_definer;


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
GRANT SELECT(login_handle) ON TABLE request_engine.native_identities TO request_platform_definer;


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
-- Name: COLUMN native_identity_provision_receipts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.native_identity_provision_receipts TO request_platform_control_definer;


--
-- Name: COLUMN native_identity_provision_receipts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.native_identity_provision_receipts TO request_platform_control_definer;


--
-- Name: COLUMN native_identity_provision_receipts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.native_identity_provision_receipts TO request_platform_control_definer;


--
-- Name: COLUMN native_identity_provision_receipts.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),INSERT(native_identity_id) ON TABLE request_engine.native_identity_provision_receipts TO request_platform_control_definer;


--
-- Name: COLUMN native_identity_provision_receipts.login_handle; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(login_handle),INSERT(login_handle) ON TABLE request_engine.native_identity_provision_receipts TO request_platform_control_definer;


--
-- Name: COLUMN native_identity_provision_receipts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(correlation_id) ON TABLE request_engine.native_identity_provision_receipts TO request_platform_control_definer;


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
-- Name: COLUMN organization_provisioning_facts.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(organization_id) ON TABLE request_engine.organization_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_provisioning_facts.provisioned_by_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(provisioned_by_principal_id) ON TABLE request_engine.organization_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_provisioning_facts.provenance_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(provenance_reference) ON TABLE request_engine.organization_provisioning_facts TO request_platform_control_definer;


--
-- Name: TABLE organization_public_contact_endpoints; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.organization_public_contact_endpoints TO request_engine_app;
GRANT ALL ON TABLE request_engine.organization_public_contact_endpoints TO request_engine_admin;


--
-- Name: COLUMN organization_root_provisioning_facts.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id),INSERT(organization_id) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_root_provisioning_facts.organization_party_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_party_id),INSERT(organization_party_id) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_root_provisioning_facts.controller_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_principal_id),INSERT(controller_principal_id) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_root_provisioning_facts.controller_binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(controller_binding_id),INSERT(controller_binding_id) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_root_provisioning_facts.provisioned_by_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(provisioned_by_principal_id),INSERT(provisioned_by_principal_id) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_root_provisioning_facts.provenance_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(provenance_reference),INSERT(provenance_reference) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN organization_root_provisioning_facts.initial_controller_policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(initial_controller_policy_key) ON TABLE request_engine.organization_root_provisioning_facts TO request_platform_control_definer;


--
-- Name: TABLE organizations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.organizations TO request_engine_app;
GRANT ALL ON TABLE request_engine.organizations TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.organizations TO request_engine_discovery_definer;


--
-- Name: COLUMN organizations.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.organizations TO request_platform_control_definer;
GRANT SELECT(id) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.organization_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(organization_key) ON TABLE request_engine.organizations TO request_platform_control_definer;
GRANT SELECT(organization_key) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.display_name; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(display_name) ON TABLE request_engine.organizations TO request_platform_control_definer;
GRANT SELECT(display_name) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.updated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(updated_at) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.default_timezone; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(default_timezone) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.default_locale; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(default_locale) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.default_currency; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(default_currency) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: COLUMN organizations.operational_status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(operational_status) ON TABLE request_engine.organizations TO request_platform_definer;


--
-- Name: TABLE parties; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.parties TO request_engine_app;
GRANT ALL ON TABLE request_engine.parties TO request_engine_admin;


--
-- Name: COLUMN parties.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.parties TO request_platform_control_definer;


--
-- Name: COLUMN parties.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(organization_id) ON TABLE request_engine.parties TO request_platform_control_definer;


--
-- Name: COLUMN parties.party_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(party_kind) ON TABLE request_engine.parties TO request_platform_control_definer;


--
-- Name: COLUMN parties.display_name; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(display_name) ON TABLE request_engine.parties TO request_platform_control_definer;


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
-- Name: COLUMN party_identity_revisions.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(organization_id) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN party_identity_revisions.party_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(party_id) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN party_identity_revisions.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(revision) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN party_identity_revisions.change_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(change_kind) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN party_identity_revisions.display_name; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(display_name) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN party_identity_revisions.active; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(active) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN party_identity_revisions.state; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(state) ON TABLE request_engine.party_identity_revisions TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_id),INSERT(principal_id) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.action; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(action),INSERT(action) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.actor_authentication_method; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(actor_authentication_method) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.reason_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(reason_code) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.external_case_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(external_case_reference) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.revision_before; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(revision_before) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.revision_after; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision_after),INSERT(revision_after) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(correlation_id) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.capability_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(capability_key),INSERT(capability_key) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_authority_lifecycle_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_authority_lifecycle_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_bootstrap_intents.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.token_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(token_digest) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.permitted_action; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(permitted_action) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.provenance_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(provenance_reference) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_bootstrap_intents.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(consumed_at) ON TABLE request_engine.platform_bootstrap_intents TO request_bootstrap_definer;


--
-- Name: COLUMN platform_configuration_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.event_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(event_kind),INSERT(event_kind) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;
GRANT SELECT(event_kind) ON TABLE request_engine.platform_configuration_facts TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_facts.configuration_revision_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(configuration_revision_id),INSERT(configuration_revision_id) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;
GRANT SELECT(configuration_revision_id) ON TABLE request_engine.platform_configuration_facts TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_facts.configuration_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(configuration_kind),INSERT(configuration_kind) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),INSERT(revision) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.secret_binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(secret_binding_id),INSERT(secret_binding_id) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.actor_authentication_method; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_authentication_method),INSERT(actor_authentication_method) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(correlation_id),INSERT(correlation_id) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.detail; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(detail),INSERT(detail) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;
GRANT SELECT(detail) ON TABLE request_engine.platform_configuration_facts TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_facts.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;
GRANT SELECT(created_at) ON TABLE request_engine.platform_configuration_facts TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_facts.capability_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(capability_key),INSERT(capability_key) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_configuration_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_configuration_revisions.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(id) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.configuration_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(configuration_kind),INSERT(configuration_kind) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(configuration_kind) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.provider_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(provider_kind),INSERT(provider_kind) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(provider_kind) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),INSERT(revision) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(revision) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.configuration; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(configuration),INSERT(configuration) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(configuration) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.secret_binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(secret_binding_id),INSERT(secret_binding_id) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(secret_binding_id) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.state; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(state),UPDATE(state) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(state) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.created_by_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_by_principal_id),INSERT(created_by_principal_id) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(created_by_principal_id) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(created_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.validated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(validated_at),UPDATE(validated_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(validated_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.activated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(activated_at),UPDATE(activated_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(activated_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_configuration_revisions.disabled_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(disabled_at),UPDATE(disabled_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_control_definer;
GRANT SELECT(disabled_at) ON TABLE request_engine.platform_configuration_revisions TO request_platform_definer;


--
-- Name: COLUMN platform_identity_disable_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.capability_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(capability_key),INSERT(capability_key) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),INSERT(native_identity_id) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.native_authority_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(native_authority_id) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.revision_before; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(revision_before) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.revision_after; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision_after),INSERT(revision_after) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.reason_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(reason_code) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.external_case_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(external_case_reference) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.affected_tenant_count; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(affected_tenant_count),INSERT(affected_tenant_count) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.affected_platform; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(affected_platform),INSERT(affected_platform) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_disable_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(correlation_id) ON TABLE request_engine.platform_identity_disable_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.case_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(case_id),INSERT(case_id) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.action; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(action),INSERT(action) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.actor_authentication_method; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(actor_authentication_method) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.reason_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(reason_code) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.external_case_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(external_case_reference) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.revision_before; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(revision_before) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.revision_after; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision_after),INSERT(revision_after) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(correlation_id) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.capability_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(capability_key),INSERT(capability_key) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_identity_recovery_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_identity_recovery_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.instance_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(instance_id),INSERT(instance_id) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.setup_session_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(setup_session_id),INSERT(setup_session_id) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.owner_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(owner_principal_id),INSERT(owner_principal_id) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),INSERT(native_identity_id) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(policy_key),INSERT(policy_key) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.claim_provenance; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(claim_provenance),INSERT(claim_provenance) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(correlation_id),INSERT(correlation_id) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_installation_claim_facts.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_installation_claim_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.singleton_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(singleton_key) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.state; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(state),UPDATE(state) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.built_in_native_authority_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(built_in_native_authority_id) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.built_in_workload_authority_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(built_in_workload_authority_id) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.claimed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(claimed_at),UPDATE(claimed_at) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.initial_owner_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(initial_owner_principal_id),UPDATE(initial_owner_principal_id) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_instance.claim_provenance; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(claim_provenance),UPDATE(claim_provenance) ON TABLE request_engine.platform_instance TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.invitation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(invitation_id) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.action; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(action),INSERT(action) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(native_identity_id) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.revision_before; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(revision_before) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.revision_after; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision_after),INSERT(revision_after) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(correlation_id) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.reason_code; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(reason_code) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitation_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_owner_invitation_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.token_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(token_digest),INSERT(token_digest) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.token_fingerprint; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(token_fingerprint),INSERT(token_fingerprint) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.invited_by_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(invited_by_principal_id),INSERT(invited_by_principal_id) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),UPDATE(native_identity_id) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.provenance_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(provenance_reference),INSERT(provenance_reference) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at),INSERT(expires_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.enrolled_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(enrolled_at),UPDATE(enrolled_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(consumed_at),UPDATE(consumed_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revoked_at),UPDATE(revoked_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_policies.policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(policy_key) ON TABLE request_engine.platform_owner_policies TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_policies.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision) ON TABLE request_engine.platform_owner_policies TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_policies.grants; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(grants) ON TABLE request_engine.platform_owner_policies TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_id),INSERT(principal_id) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.native_identity_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(native_identity_id),INSERT(native_identity_id) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.policy_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(policy_key),INSERT(policy_key) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.provenance_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(provenance_reference),INSERT(provenance_reference) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_provisioning_facts.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(correlation_id),INSERT(correlation_id) ON TABLE request_engine.platform_owner_provisioning_facts TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_bindings.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id),INSERT(id) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(id) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.purpose; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(purpose),INSERT(purpose) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(purpose) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.backend; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(backend),INSERT(backend) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(backend) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.secret_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(secret_id),INSERT(secret_id) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(secret_id) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.backend_version; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(backend_version),INSERT(backend_version),UPDATE(backend_version) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(backend_version) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(status) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(revision) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(created_at) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.rotated_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(rotated_at),UPDATE(rotated_at) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(rotated_at) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_bindings.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revoked_at),UPDATE(revoked_at) ON TABLE request_engine.platform_secret_bindings TO request_platform_control_definer;
GRANT SELECT(revoked_at) ON TABLE request_engine.platform_secret_bindings TO request_platform_definer;


--
-- Name: COLUMN platform_secret_mutations.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.operation_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(operation_kind),INSERT(operation_kind) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.capability_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(capability_key),INSERT(capability_key) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.actor_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_principal_id),INSERT(actor_principal_id) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.actor_authentication_method; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(actor_authentication_method),INSERT(actor_authentication_method) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.correlation_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(correlation_id),INSERT(correlation_id) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(binding_id),INSERT(binding_id) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.secret_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(secret_id),INSERT(secret_id) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.purpose; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(purpose),INSERT(purpose) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.backend; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(backend),INSERT(backend) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.expected_binding_revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expected_binding_revision),INSERT(expected_binding_revision) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.expected_backend_version; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expected_backend_version),INSERT(expected_backend_version) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.applied_backend_version; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(applied_backend_version),UPDATE(applied_backend_version) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.state; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(state),UPDATE(state) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.idempotency_key_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(idempotency_key_digest),INSERT(idempotency_key_digest) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.intent_digest; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(intent_digest),INSERT(intent_digest) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.result_binding_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(result_binding_id),UPDATE(result_binding_id) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.result_binding_revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(result_binding_revision),UPDATE(result_binding_revision) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.result_binding_status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(result_binding_status),UPDATE(result_binding_status) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.created_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(created_at) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.backend_applied_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(backend_applied_at),UPDATE(backend_applied_at) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.committed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(committed_at),UPDATE(committed_at) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


--
-- Name: COLUMN platform_secret_mutations.reconcile_required_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(reconcile_required_at),UPDATE(reconcile_required_at) ON TABLE request_engine.platform_secret_mutations TO request_platform_control_definer;


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
-- Name: TABLE principal_authority_grants; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.principal_authority_grants TO request_engine_app;


--
-- Name: COLUMN principal_authority_grants.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id),INSERT(organization_id) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_id) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;
GRANT INSERT(principal_id) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(principal_id),INSERT(principal_id) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.principal_plane; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_plane) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;
GRANT INSERT(principal_plane) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(principal_plane),INSERT(principal_plane) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.authority_plane; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(authority_plane) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;
GRANT INSERT(authority_plane) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(authority_plane),INSERT(authority_plane) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.capability_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(capability_key) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;
GRANT INSERT(capability_key) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(capability_key),INSERT(capability_key) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.delegable; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(delegable) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;
GRANT INSERT(delegable) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(delegable),INSERT(delegable) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.status; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(status) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;
GRANT SELECT(status),UPDATE(status) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(revision),UPDATE(revision) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.granted_by_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(granted_by_principal_id),INSERT(granted_by_principal_id) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.provenance_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(provenance_kind) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(provenance_kind),INSERT(provenance_kind) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;
GRANT SELECT(provenance_kind) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;


--
-- Name: COLUMN principal_authority_grants.provenance_reference; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(provenance_reference) ON TABLE request_engine.principal_authority_grants TO request_bootstrap_definer;
GRANT SELECT(provenance_reference),INSERT(provenance_reference) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;
GRANT SELECT(provenance_reference) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;


--
-- Name: COLUMN principal_authority_grants.granted_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(granted_at) ON TABLE request_engine.principal_authority_grants TO request_platform_definer;


--
-- Name: COLUMN principal_authority_grants.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


--
-- Name: COLUMN principal_authority_grants.revoked_by_principal_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_by_principal_id) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


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
-- Name: COLUMN principals.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(id) ON TABLE request_engine.principals TO request_platform_definer;
GRANT SELECT(id),INSERT(id) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(id),INSERT(id) ON TABLE request_engine.principals TO request_platform_control_definer;


--
-- Name: COLUMN principals.organization_id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(organization_id) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(organization_id),INSERT(organization_id) ON TABLE request_engine.principals TO request_platform_control_definer;
GRANT SELECT(organization_id) ON TABLE request_engine.principals TO request_platform_definer;


--
-- Name: COLUMN principals.principal_kind; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_kind) ON TABLE request_engine.principals TO request_platform_definer;
GRANT INSERT(principal_kind) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(principal_kind),INSERT(principal_kind) ON TABLE request_engine.principals TO request_platform_control_definer;


--
-- Name: COLUMN principals.external_subject; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(external_subject) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(external_subject),INSERT(external_subject) ON TABLE request_engine.principals TO request_platform_control_definer;


--
-- Name: COLUMN principals.active; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(active) ON TABLE request_engine.principals TO request_platform_definer;
GRANT SELECT(active) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(active) ON TABLE request_engine.principals TO request_platform_control_definer;


--
-- Name: COLUMN principals.principal_plane; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(principal_plane) ON TABLE request_engine.principals TO request_platform_definer;
GRANT SELECT(principal_plane),INSERT(principal_plane) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(principal_plane),INSERT(principal_plane) ON TABLE request_engine.principals TO request_platform_control_definer;


--
-- Name: COLUMN principals.authority_revision; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(authority_revision) ON TABLE request_engine.principals TO request_platform_definer;
GRANT SELECT(authority_revision),UPDATE(authority_revision) ON TABLE request_engine.principals TO request_bootstrap_definer;
GRANT SELECT(authority_revision),UPDATE(authority_revision) ON TABLE request_engine.principals TO request_platform_control_definer;


--
-- Name: TABLE queue_entries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.queue_entries TO request_engine_app;
GRANT ALL ON TABLE request_engine.queue_entries TO request_engine_admin;


--
-- Name: TABLE queue_entry_operator_selections; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT ON TABLE request_engine.queue_entry_operator_selections TO request_engine_app;
