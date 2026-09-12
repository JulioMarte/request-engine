# Reviewed current request_engine table-contract exception sets for the runtime login
# proofs. Values are (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES,
# TRIGGER) privilege tuples; every entry tracks an accepted, reviewed migration.

PRIVATE_GLOBAL_TABLES = {
    "initial_controller_policies",
    "global_identities",
    "shared_capacity_authority_events",
    "shared_capacity_bindings",
    "shared_capacity_claim_links",
    "shared_capacity_identities",
}

# F2 taxonomy/discovery tables follow reviewed narrower shapes: taxonomy is
# registered/adjusted by the app but read through definer lookups; the
# authority-event ledger and handoffs are fully definer-mediated.
EXPECTED_TABLE_EXCEPTIONS = {
    "discovery_booking_handoffs": (False,) * 7,
    "service_classification_authority_events": (False,) * 7,
    "service_classifications": (False,) * 7,
    # F4 recomputes assignment availability, legitimately deleting stale rows.
    "resource_location_availability": (True, True, True, True, False, False, False),
    # S0b2 (§9.3): the party identity revision ledger is append-only for the
    # app role; UPDATE/DELETE are denied by grants and by the 0025 guard.
    "party_identity_revisions": (True, True, False, False, False, False, False),
    # Immutable/versioned facts: accepted 0001 ACLs deny table UPDATE. Separate
    # column-grant proofs cover the few explicitly mutable lifecycle columns.
    **dict.fromkeys(
        (
            "attendance_responses",
            "audit_records",
            "communication_escalations",
            "offering_resource_requirements",
            "offering_version_booking_policies",
            "offering_version_booking_terms",
            "offering_versions",
            "operational_recovery_escalations",
            "operational_recovery_executions",
            "operational_recovery_proposals",
            "queue_entry_operator_selections",
            "queue_entry_recall_holds",
            "queue_entry_skips",
            "reminder_acknowledgements",
            "request_definition_versions",
            "reservation_commercial_commitment_context_terms",
            "reservation_commercial_commitments",
        ),
        (True, True, False, False, False, False, False),
    ),
    # Authority writes are mediated by reviewed commands, never ordinary table CRUD
    # (0003, 0006, 0019, 0024, 0025, 0026).
    **dict.fromkeys(
        (
            "agent_policies",
            "agent_profiles",
            "delegations",
            "identity_bindings",
            "principal_authority_grants",
            "staff_memberships",
        ),
        (True, False, False, False, False, False, False),
    ),
    # Private identity/provider/provisioning state (0001, 0006-0019, 0023, 0030).
    # This is deliberately an exact inventory, not permission inferred from names.
    **dict.fromkeys(
        (
            "identity_authorities",
            "identity_exchange_candidates",
            "integration_governance_facts",
            "native_credentials",
            "native_identities",
            "native_recovery_intents",
            "native_sessions",
            "organization_party_bindings",
            "organization_provisioning_facts",
            "organization_root_provisioning_facts",
            "platform_bootstrap_intents",
            "portable_party_identifiers",
            "portable_party_identities",
            "portable_party_profiles",
            "recovery_source_revisions",
            "workload_credentials",
            "workload_identities",
        ),
        (False,) * 7,
    ),
}
