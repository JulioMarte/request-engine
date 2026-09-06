# PostgreSQL relation ownership manifest

Status: pre-rebaseline effective-model audit

Source checkpoint: green current-product catalog from `4a4a3e20ad79cecf59132f55b8fd671023b06427` (catalog schema version 5), followed by reviewed migrations through `0048_remove_legacy_location`. `0044` removes a redundant trigger/function, `0045`/`0046` harden ACLs, `0047` removes a redundant index, and `0048` removes the pre-launch `availability_schedules` relation plus the legacy `resources.location_id` column. Of those changes, only `0048` changes the relation count.

This manifest accounts for the expected effective relation set after `0048`: **101 relations**. Exact-head PostgreSQL catalog export remains required before this count is treated as final rebaseline evidence. Unless explicitly noted as a composition boundary, each surviving relation is classified `KEEP` under the capability owner below.

Database object ownership remains `request_engine_schema_owner`; `capability owner` here means semantic/persistence responsibility, not PostgreSQL `relowner`.

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

`request_engine.availability_schedules` is intentionally absent. It was a pre-launch compatibility relation superseded by Resource-at-Location assignments plus contextual recurring availability and was removed by `0048_remove_legacy_location`.

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

Discovery's module contract explicitly owns ServiceClassification mapping semantics and OfferingServiceClassification provenance.

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

## Platform — 8

Platform ownership here is technical mechanics, not a business catch-all.

- `request_admin.outbox_health_v1`
- `request_admin.scheduled_action_health_v1`
- `request_admin.worker_dead_letters_v1`
- `request_engine.audit_records`
- `request_engine.idempotency_records`
- `request_engine.outbox_messages`
- `request_engine.provider_events`
- `request_engine.scheduled_actions`

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
- `request_read.live_service_staff_v1` — Queue-owned staff read projection composed with Delivery execution facts.
- `request_read.service_queue_status_v2` — Queue-owned projection with Delivery-dependent composition; retained because `live_service_staff_v1` depends on it.

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

- `request_engine.recovery_source_revisions` — **KEEP**, jointly scoped Live Capacity ↔ Operational Recovery transactional freshness fence. Direct app DML was removed by `0042`; supported access is through `request_read.recovery_source_revision(...)` and `request_cmd.lock_recovery_source_revision(...)`.
- `request_engine.shared_capacity_authority_events` — **KEEP**, Tenancy ↔ Booking authority ledger. It records both `global_identity.created` and SharedCapacity identity/binding authority events, so assigning it solely to Booking would hide an intentional cross-boundary audit fact.

## Totals

| Capability owner | Relations |
|---|---:|
| Booking | 19 |
| Tenancy | 15 |
| Queue | 14 |
| Catalog | 12 |
| Platform | 8 |
| Communications | 6 |
| Discovery | 6 |
| Delivery | 6 |
| Operational Recovery | 6 |
| Requests | 5 |
| Live Capacity | 2 |
| Explicit Live Capacity + Operational Recovery composition | 1 |
| Explicit Tenancy + Booking authority-ledger composition | 1 |
| **Total** | **101** |

## Rebaseline implication

Relation ownership is no longer a `NEEDS_PROOF` blocker for the previously exported #3902 relation set, and `availability_schedules` has now been deliberately removed from the target model. Rebaseline still requires an exact-head catalog export after `0048` to verify the expected 101-relation set and to account exhaustively for routines, triggers, policies/roles/grants and every later object-level correction before this manifest can be treated as final evidence.
