# Reviewed executable authority surface of the request_engine_app runtime role,
# in the ``schema.function(identity_arguments)`` form. Every entry is introduced
# by an accepted, reviewed migration grant; this inventory changes only together
# with a reviewed grant and evidence for the authority being added or removed.
# Trigger functions carry no caller-facing EXECUTE grant by design.

REVIEWED_APP_EXECUTE_ALLOWLIST = {
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
        "request_engine.create_identity_exchange_candidate_v1(p_kind text, p_authority text, "
        "p_fingerprint text, p_principal_id uuid)"
    ),
    "request_engine.current_authenticated_principal_id()",
    "request_engine.current_correlation_id()",
    "request_engine.current_organization_id()",
    (
        "request_engine.consume_identity_exchange_candidate_v1(p_candidate_id uuid, "
        "p_kind text, p_authority text, p_fingerprint text, p_principal_id uuid)"
    ),
    (
        "request_engine.identity_exchange_existing_party_v1(p_candidate_id uuid, "
        "p_principal_id uuid)"
    ),
    (
        "request_engine.lock_current_party_authority(p_organization_id uuid, "
        "p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)"
    ),
    "request_engine.lookup_active_service_classification(p_key text)",
    "request_engine.lookup_service_classification(p_id uuid)",
    (
        "request_engine.publish_portable_party_v1(p_party_id uuid, p_kind text, "
        "p_authority text, p_fingerprint text, p_consent_fields text[], p_principal_id uuid)"
    ),
    "request_engine.read_discovery_booking_handoff(p_token_hash text)",
    (
        "request_engine.resolve_current_party_authority(p_organization_id uuid, "
        "p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)"
    ),
    ("request_read.recovery_source_revision(p_organization_id uuid, p_service_queue_id uuid)"),
}
