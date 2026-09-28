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
-- Name: TABLE organizations; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.organizations TO request_engine_app;
GRANT ALL ON TABLE request_engine.organizations TO request_engine_admin;
GRANT SELECT ON TABLE request_engine.organizations TO request_engine_discovery_definer;


--
-- Name: COLUMN organizations.id; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(id) ON TABLE request_engine.organizations TO request_platform_control_definer;


--
-- Name: COLUMN organizations.organization_key; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(organization_key) ON TABLE request_engine.organizations TO request_platform_control_definer;


--
-- Name: COLUMN organizations.display_name; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT INSERT(display_name) ON TABLE request_engine.organizations TO request_platform_control_definer;


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
-- Name: COLUMN platform_owner_invitations.expires_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT(expires_at),INSERT(expires_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.enrolled_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(enrolled_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.consumed_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(consumed_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


--
-- Name: COLUMN platform_owner_invitations.revoked_at; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT UPDATE(revoked_at) ON TABLE request_engine.platform_owner_invitations TO request_platform_control_definer;


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

GRANT INSERT(organization_id) ON TABLE request_engine.principal_authority_grants TO request_platform_control_definer;


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
-- Name: TABLE staff_memberships; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT ON TABLE request_engine.staff_memberships TO request_engine_app;


--
-- Name: TABLE waitlist_entries; Type: ACL; Schema: request_engine; Owner: request_engine_schema_owner
--

GRANT SELECT,INSERT,UPDATE ON TABLE request_engine.waitlist_entries TO request_engine_app;
GRANT ALL ON TABLE request_engine.waitlist_entries TO request_engine_admin;


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


