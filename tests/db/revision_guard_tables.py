# Frozen set of revision-managed aggregates that must install a
# ``*_revision_step`` guard trigger. Every entry tracks an accepted, reviewed
# migration that joined the aggregate to the V3 revision-guard protocol.

REVISION_GUARD_TABLES = {
    "representations",
    "requests",
    "capacity_holds",
    "reservations",
    "reservation_attendance",
    "service_classifications",
    "offering_service_classifications",
    "booking_context_terms",
    "discovery_publications",
    "resource_public_profiles",
    "resource_location_assignments",
    "service_queues",
    "queue_entries",
    "waitlist_entries",
    "slot_opportunities",
    "slot_offers",
    "communication_tasks",
    "reminder_plans",
}
