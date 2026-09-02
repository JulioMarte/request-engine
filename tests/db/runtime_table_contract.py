# Frozen request_engine table-contract exception sets for the runtime login
# proofs. Values are (SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES,
# TRIGGER) privilege tuples; every entry tracks an accepted, reviewed migration.

PRIVATE_GLOBAL_TABLES = {
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
    "service_classifications": (False, True, True, False, False, False, False),
    # F4 recomputes assignment availability, legitimately deleting stale rows.
    "resource_location_availability": (True, True, True, True, False, False, False),
    # S0b2 (§9.3): the party identity revision ledger is append-only for the
    # app role; UPDATE/DELETE are denied by grants and by the 0025 guard.
    "party_identity_revisions": (True, True, False, False, False, False, False),
    # F7e: selection facts are an immutable operational audit ledger. The app
    # may read/append facts but cannot revise or delete a recorded selection.
    "queue_selection_facts": (True, True, False, False, False, False, False),
}
