# Reviewed executable authority surface of the request_engine_app runtime role,
# in the ``schema.function(identity_arguments)`` form. Every entry is introduced
# by an accepted, reviewed migration grant; this inventory changes only together
# with a reviewed grant and evidence for the authority being added or removed.
# Trigger functions carry no caller-facing EXECUTE grant by design.

REVIEWED_APP_EXECUTE_ALLOWLIST = {
    # 0038: bounded transport-only shared authentication admission; no direct state-table ACL.
    "request_auth.admit_http_authentication(p_limit integer)",
    # 0025: current HUMAN manager, tenant-local target and delegable ceiling;
    # revision-checked credential replacement, with no direct credential table ACL.
    "request_cmd.lock_agent_credential_manager(p_target uuid)",
    (
        "request_cmd.rotate_agent_credential(p_target uuid, p_expected bigint, "
        "p_credential uuid, p_digest bytea, p_fingerprint text, "
        "p_expiry timestamp with time zone)"
    ),
    # Metadata only; never returns token digest, fingerprint or plaintext.
    "request_read.agent_credential_metadata(p_target uuid)",
    # 0012: closed staff capability gate, current actor locks, no business writes.
    "request_cmd.lock_staff_command_authority(p_capability text)",
    # 0028: current controller-upgrade authority before an idempotency replay.
    "request_cmd.lock_controller_policy_upgrade_authority()",
    # 0027: original-root consent, cancellation, and own-request receipt reads.
    (
        "request_cmd.request_controller_policy_adoption(p_binding_id uuid, "
        "p_expected_authority_revision bigint, p_reason text, p_key_digest text, "
        "p_intent_digest text, p_correlation_id uuid)"
    ),
    (
        "request_cmd.withdraw_controller_policy_adoption(p_request_id uuid, "
        "p_expected_revision bigint, p_binding_id uuid, p_key_digest text, "
        "p_intent_digest text)"
    ),
    "request_cmd.read_controller_policy_adoption(p_request_id uuid, p_binding_id uuid)",
    # 0011: fixed-capability tenant-local profile locks/CAS; no authority writes.
    "request_cmd.lock_staff_member_profile(p_membership uuid)",
    (
        "request_cmd.write_staff_member_profile(p_membership uuid, p_expected bigint, "
        "p_name text, p_provenance text)"
    ),
    # 0009: current manager gate and subject-proof-bound staff materialization.
    "request_cmd.assert_staff_invitation_manager()",
    "request_cmd.lock_staff_invitation_admin(p_id uuid)",
    (
        "request_cmd.lock_staff_invitation_acceptance(p_id uuid, p_digest text, "
        "p_authority uuid, p_identity uuid, p_session uuid)"
    ),
    (
        "request_cmd.materialize_invited_staff(p_id uuid, p_digest text, p_authority uuid, "
        "p_identity uuid, p_session uuid, p_membership uuid, p_principal uuid, p_binding uuid)"
    ),
    # 0007: current-tenant planner projection, not the private cross-tenant predicate.
    "request_read.staff_controller_is_effective(p_principal_id uuid)",
    # 0030: current HUMAN manager revalidation, bounded credential replacement,
    # and tenant-local inspection. Private state mutators remain owner-only.
    "request_cmd.assert_integration_manager(p_capability text)",
    (
        "request_cmd.rotate_integration_credential(p_principal_id uuid, "
        "p_expected_revision bigint, p_credential_id uuid, p_digest bytea, "
        "p_fingerprint text, p_expires_at timestamp with time zone, p_reference text)"
    ),
    "request_read.integrations(p_principal_id uuid, p_after uuid, p_limit integer)",
    (
        "request_cmd.acquire_idempotency(p_organization_id uuid, p_principal_id uuid, "
        "p_capability text, p_idempotency_key text, p_request_fingerprint text)"
    ),
    "request_cmd.cancel_scheduled_action(p_organization_id uuid, p_action_id uuid)",
    "request_cmd.complete_idempotency(p_idempotency_id uuid, p_result_data jsonb)",
    (
        "request_cmd.lock_outbox_message_claim(p_organization_id uuid, "
        "p_message_id uuid, p_claim_token uuid)"
    ),
    "request_cmd.lock_recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid)",
    "request_cmd.lock_scheduled_action_claim(p_action_id uuid, p_claim_token uuid)",
    "request_cmd.lock_shared_capacity_roots(p_organization_id uuid, p_resource_ids uuid[])",
    (
        "request_cmd.mark_queue_entry_service_completed(p_organization_id uuid, "
        "p_queue_entry_id uuid, p_completed_at timestamp with time zone)"
    ),
    (
        "request_cmd.mark_queue_entry_service_started(p_organization_id uuid, "
        "p_queue_entry_id uuid, p_started_at timestamp with time zone)"
    ),
    (
        "request_cmd.schedule_recovery_reassessment(p_organization_id uuid, "
        "p_service_queue_id uuid, p_revision bigint)"
    ),
    (
        "request_engine.bind_consumed_identity_candidate_v1(p_candidate_id uuid, "
        "p_party_id uuid, p_consent_fields text[], p_principal_id uuid)"
    ),
    (
        "request_engine.create_delegation(p_id uuid, p_delegator_principal_id uuid, "
        "p_delegate_principal_id uuid, p_purpose text, p_allowed_capabilities text[], "
        "p_not_before timestamp with time zone, p_expires_at timestamp with time zone, "
        "p_provenance_reference text)"
    ),
    (
        "request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, "
        "p_fingerprint text, p_principal_id uuid)"
    ),
    (
        "request_engine.create_identity_link_intent(p_intent_id uuid, "
        "p_actor_binding_id uuid, p_target_authority_id uuid, p_nonce_digest text, "
        "p_ttl_seconds integer, p_provenance_reference text)"
    ),
    "request_engine.current_authenticated_principal_id()",
    "request_engine.current_correlation_id()",
    "request_engine.current_organization_id()",
    (
        "request_engine.confirm_identity_link_intent(p_intent_id uuid, "
        "p_expected_actor_binding_revision bigint, p_native_identity_id uuid, "
        "p_binding_id uuid, p_provenance_reference text)"
    ),
    (
        "request_engine.confirm_identity_link_subject(p_intent_id uuid, "
        "p_expected_actor_binding_revision bigint, p_subject_id text, "
        "p_binding_id uuid, p_provenance_reference text)"
    ),
    (
        "request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, "
        "p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid)"
    ),
    (
        "request_engine.identity_exchange_existing_party_v1(p_candidate_id uuid, "
        "p_principal_id uuid)"
    ),
    (
        "request_engine.invite_native_staff(p_membership_id uuid, p_principal_id uuid, "
        "p_binding_id uuid, p_identity_authority_id uuid, p_native_identity_id uuid, "
        "p_authority_anchor_party_id uuid, p_provenance_reference text)"
    ),
    (
        "request_engine.lock_current_party_authority(p_organization_id uuid, "
        "p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)"
    ),
    "request_engine.lookup_active_service_classification(p_key text)",
    "request_engine.lookup_service_classification(p_id uuid)",
    (
        "request_engine.provision_agent(p_principal_id uuid, p_binding_id uuid, "
        "p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, "
        "p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at "
        "timestamp with time zone, p_display_name text, p_purpose text, "
        "p_sponsor_principal_id uuid, p_operating_mode text, p_provenance_reference text)"
    ),
    (
        "request_engine.publish_portable_party_v1(p_party_id uuid, p_kind text, "
        "p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid)"
    ),
    "request_engine.read_discovery_booking_handoff(p_token_hash text)",
    "request_engine.read_identity_link_intent(p_intent_id uuid)",
    "request_engine.read_onboarding_identity_facts(p_organization_id uuid)",
    (
        "request_engine.provision_integration(p_principal_id uuid, p_binding_id uuid, "
        "p_workload_identity_id uuid, p_credential_id uuid, p_identity_authority_id uuid, "
        "p_token_digest bytea, p_token_fingerprint text, p_credential_expires_at "
        "timestamp with time zone, p_provenance_reference text)"
    ),
    (
        "request_engine.replace_agent_authority(p_principal_id uuid, "
        "p_expected_authority_revision bigint, p_desired_capabilities text[], "
        "p_provenance_reference text)"
    ),
    (
        "request_engine.replace_integration_authority(p_principal_id uuid, "
        "p_expected_authority_revision bigint, p_desired_capabilities text[], "
        "p_provenance_reference text)"
    ),
    (
        "request_engine.replace_staff_authority(p_membership_id uuid, "
        "p_expected_authority_revision bigint, p_desired_capabilities text[], "
        "p_provenance_reference text)"
    ),
    (
        "request_engine.resolve_current_party_authority(p_organization_id uuid, "
        "p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)"
    ),
    (
        "request_engine.revoke_delegation(p_id uuid, p_expected_revision bigint, "
        "p_provenance_reference text)"
    ),
    (
        "request_engine.set_integration_status(p_principal_id uuid, "
        "p_expected_revision bigint, p_target_status text, p_provenance_reference text)"
    ),
    (
        "request_engine.transition_agent_profile(p_principal_id uuid, "
        "p_expected_revision bigint, p_target_status text, p_provenance_reference text)"
    ),
    (
        "request_engine.transition_identity_binding(p_binding_id uuid, "
        "p_expected_revision bigint, p_target_status text, p_provenance_reference text)"
    ),
    (
        "request_engine.transition_staff_membership(p_membership_id uuid, "
        "p_expected_revision bigint, p_target_status text, p_provenance_reference text)"
    ),
    (
        "request_engine.upgrade_controller_policy(p_target_principal_id uuid, "
        "p_source_policy_key text, p_target_policy_key text, "
        "p_expected_authority_revision bigint, p_provenance_reference text)"
    ),
    (
        "request_engine.upsert_agent_policy(p_agent_principal_id uuid, "
        "p_allowed_capabilities text[], p_denied_capabilities text[], "
        "p_risk_ceiling text, p_max_mutations_per_minute integer, "
        "p_provenance_reference text)"
    ),
    ("request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid)"),
}
