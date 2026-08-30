# Frozen reviewed executable surface of the request_engine_app runtime role,
# in the ``schema.function(identity_arguments)`` form. Every entry is
# introduced by an accepted, reviewed migration grant; this inventory must
# change only together with a new reviewed grant and its own evidence.
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
        "request_cmd.schedule_recovery_reassessment(p_organization_id uuid, "
        "p_service_queue_id uuid, p_revision bigint)"
    ),
    "request_engine.current_authenticated_principal_id()",
    "request_engine.current_correlation_id()",
    "request_engine.current_organization_id()",
    (
        "request_engine.lock_current_party_authority(p_organization_id uuid, "
        "p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)"
    ),
    "request_engine.lookup_active_service_classification(p_key text)",
    "request_engine.lookup_service_classification(p_id uuid)",
    "request_engine.read_discovery_booking_handoff(p_token_hash text)",
    (
        "request_engine.resolve_current_party_authority(p_organization_id uuid, "
        "p_principal_id uuid, p_represented_party_id uuid, p_scope_key text)"
    ),
}
