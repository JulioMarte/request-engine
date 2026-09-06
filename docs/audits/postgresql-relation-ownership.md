# PostgreSQL relation ownership manifest

Status: **closed for pre-rebaseline effective-model ownership**

Final exact-head evidence: CI **#4164** on branch head `4ba7dbf092528f26aee5db1003af455a381d3431`, after migrations through `0050_remove_admin_health_views`.

The current effective model contains **99 relations**. The same 99-relation catalog was reproduced both in a second database of the source cluster and in an independent PostgreSQL 18 cluster with Request Engine roles bootstrapped from zero. Both schema comparisons report `equivalent: true` and `first_difference: null`; the independent role comparison does as well.

Database object ownership remains `request_engine_schema_owner`; `capability owner` below means semantic/persistence responsibility, not PostgreSQL `relowner`. Unless explicitly marked as a composition boundary, every surviving relation is classified `KEEP` under one capability owner.

## Booking — 19

- `request_engine.attendance_responses`
- `request_engine.booking_context_terms`
- `request_engine.capacity_claims`
- `request_engine.capacity_holds`
- `request_engine.offering_version_booking_terms`
- `request_engine.reservation_commercial_commitment_context_terms`
- `request_engine.reservation_commercial_commitments`
- `request_engine.reservations`
- `request_engine.resource_capability_assignments`
- `request_engine.resource_location_assignments`
- `request_engine.resource_location_availability`
- `request_engine.resource_location_schedule_exceptions`
- `request_engine.resources`
- `request_engine.schedule_exceptions`
- `request_engine.shared_capacity_bindings`
- `request_engine.shared_capacity_claim_links`
- `request_engine.shared_capacity_identities`
- `request_read.reservation_day_v1` — Booking/Queue front-desk read composition; Booking owns the Reservation-day projection contract.
- `request_read.reservation_status_v1`

`request_engine.availability_schedules` is intentionally absent. It was pre-launch compatibility persistence superseded by Resource-at-Location assignments and contextual availability and was removed by `0048_remove_legacy_location`.

## Catalog — 12

- `request_engine.location_hours_exceptions`
- `request_engine.location_operational_hours`
- `request_engine.location_public_contact_endpoints`
- `request_engine.locations`
- `request_engine.offering_resource_requirements`
- `request_engine.offering_version_booking_policies`
- `request_engine.offering_versions`
- `request_engine.offerings`
- `request_engine.organization_public_contact_endpoints`
- `request_engine.resource_capabilities`
- `request_read.business_info_v1`
- `request_read.locations_v1`

## Communications — 6

- `request_engine.communication_deliveries`
- `request_engine.communication_escalations`
- `request_engine.communication_tasks`
- `request_engine.organization_channel_policies`
- `request_engine.reminder_acknowledgements`
- `request_engine.reminder_plans`

## Delivery — 6

- `request_engine.reservation_access`
- `request_engine.resource_activities`
- `request_engine.service_session_interruptions`
- `request_engine.service_sessions`
- `request_read.reservation_access_v1`
- `request_read.service_session_status_v1`

## Discovery — 6

Discovery owns ServiceClassification mapping semantics and OfferingServiceClassification provenance.

- `request_engine.discovery_booking_handoffs`
- `request_engine.discovery_publications`
- `request_engine.offering_service_classifications`
- `request_engine.resource_public_profiles`
- `request_engine.service_classification_authority_events`
- `request_engine.service_classifications`

## Live Capacity — 2

- `request_engine.live_capacity_projection_policies`
- `request_engine.live_capacity_workload_estimate_policies`

## Operational Recovery — 6

- `request_engine.operational_recovery_actions`
- `request_engine.operational_recovery_autonomy_policies`
- `request_engine.operational_recovery_escalations`
- `request_engine.operational_recovery_executions`
- `request_engine.operational_recovery_incidents`
- `request_engine.operational_recovery_proposals`

## Platform — 6

Platform ownership here is technical mechanics, not a business catch-all.

- `request_admin.worker_dead_letters_v1` — **KEEP** as the explicit external/operator dead-letter projection defined by `docs/v3/10-worker-runtime-hardening.md`; absence of a Python consumer does not make an administrative SQL contract dead.
- `request_engine.audit_records`
- `request_engine.idempotency_records`
- `request_engine.outbox_messages`
- `request_engine.provider_events`
- `request_engine.scheduled_actions`

Removed before rebaseline by `0050_remove_admin_health_views`:

- `request_admin.outbox_health_v1`;
- `request_admin.scheduled_action_health_v1`.

Those two projections had no production consumer, no database dependent and no explicit operator contract; their count/min/max summaries did not justify carrying implicit observability APIs into a new baseline.

## Queue — 14

- `request_engine.operational_workload_classifications`
- `request_engine.queue_entries`
- `request_engine.queue_entry_operator_selections`
- `request_engine.queue_entry_recall_holds`
- `request_engine.queue_entry_skips`
- `request_engine.reservation_arrival_estimates`
- `request_engine.reservation_attendance`
- `request_engine.service_queue_intake_controls`
- `request_engine.service_queues`
- `request_engine.slot_offers`
- `request_engine.slot_opportunities`
- `request_engine.waitlist_entries`
- `request_read.live_service_staff_v1` — Queue-owned staff projection composed with Delivery execution facts.
- `request_read.service_queue_status_v2` — Queue-owned projection retained because `live_service_staff_v1` depends on it.

## Requests — 5

- `request_engine.external_correlations`
- `request_engine.request_definition_versions`
- `request_engine.request_definitions`
- `request_engine.request_participants`
- `request_engine.requests`

## Tenancy — 15

- `request_engine.global_identities`
- `request_engine.identity_exchange_candidates`
- `request_engine.organization_party_bindings`
- `request_engine.organizations`
- `request_engine.parties`
- `request_engine.party_administrative_identifiers`
- `request_engine.party_contact_points`
- `request_engine.party_identity_documents`
- `request_engine.party_identity_revisions`
- `request_engine.portable_party_identifiers`
- `request_engine.portable_party_identities`
- `request_engine.portable_party_profiles`
- `request_engine.principal_contacts`
- `request_engine.principals`
- `request_engine.representations`

## Explicit composition boundaries — 2

- `request_engine.recovery_source_revisions` — **KEEP**, Live Capacity ↔ Operational Recovery synchronous freshness/version fence. Direct app DML was removed by `0042`; supported access is through explicit read/lock boundaries.
- `request_engine.shared_capacity_authority_events` — **KEEP**, Tenancy ↔ Booking authority ledger. It records both global-identity and SharedCapacity authority events and is intentionally cross-boundary.

## Totals

| Capability owner | Relations |
|---|---:|
| Booking | 19 |
| Tenancy | 15 |
| Queue | 14 |
| Catalog | 12 |
| Platform | 6 |
| Communications | 6 |
| Discovery | 6 |
| Delivery | 6 |
| Operational Recovery | 6 |
| Requests | 5 |
| Live Capacity | 2 |
| Explicit Live Capacity + Operational Recovery composition | 1 |
| Explicit Tenancy + Booking authority-ledger composition | 1 |
| **Total** | **99** |

## Rebaseline implication

Relation ownership is no longer a rebaseline blocker. CI #4164 proves the exact 99-relation target can be reconstructed in a fresh PostgreSQL 18 cluster together with the audited six-role topology. The remaining gate is not another relation cleanup pass: it is to materialize the proposed replacement `0001`, install that baseline from a truly clean cluster and demonstrate that it reproduces this manifest and passes the full current-product proof before the historical Alembic chain is deleted.
