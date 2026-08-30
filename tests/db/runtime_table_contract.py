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
}
