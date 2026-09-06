# PostgreSQL trigger topology audit

Status: pre-rebaseline effective-model audit

Source: catalog version 5 from green head `4a4a3e20ad79cecf59132f55b8fd671023b06427`, adjusted through `0048_remove_legacy_location`. `0044_remove_redundant_slot_guard` removes the redundant SlotOffer subject trigger; `0048` removes `availability_schedules` and therefore its capability-local `availability_schedules_bump_resource` trigger.

The post-`0048` topology contains **162 triggers**. Every trigger resolves to a classified routine and a classified relation; there are no unknown trigger functions.

Classification result:

| Topology class | Triggers | Decision |
|---|---:|---|
| capability-local invariant | 71 | `KEEP` |
| shared Platform persistence mechanic | 67 | `KEEP` |
| explicit cross-capability composition | 24 | `KEEP` after the redundant SlotOffer subject guard removal |
| unexplained owner mismatch | **0** | none |
| **Total** | **162** | |

A trigger is capability-local when its relation owner and routine owner match. Shared Platform mechanics are intentionally reusable persistence utilities such as `touch_updated_at`, `guard_exact_revision_step` and `reject_immutable_mutation`; they do not claim business ownership. Cross-capability triggers are listed exhaustively below.

## Booking ↔ Queue released-slot composition — 9

These triggers compose Booking Hold/Claim/OfferingVersion authority with Queue WaitlistEntry/SlotOpportunity/SlotOffer truth. They preserve independent ownership of the source facts.

- `capacity_holds.capacity_holds_slot_offer_consistency_deferred` → `request_engine.check_offered_slot_offer_source_consistency()`
- `capacity_holds.slot_offer_holds_consistency_guard` → `request_engine.assert_slot_offer_consistency()`
- `slot_offers.slot_offers_consistency_guard` → `request_engine.assert_slot_offer_consistency()`
- `slot_offers.slot_offers_guard_live_hold` → `request_engine.guard_slot_offer_live_hold()`
- `slot_offers.slot_offers_guard_provenance` → `request_engine.guard_slot_offer_provenance_update()`
- `slot_offers.slot_offers_guard_transition` → `request_engine.guard_slot_offer_transition()`
- `slot_offers.slot_offers_source_consistency_deferred` → `request_engine.check_offered_slot_offer_source_consistency()`
- `slot_opportunities.slot_opportunities_offer_consistency_deferred` → `request_engine.check_offered_slot_offer_source_consistency()`
- `waitlist_entries.waitlist_entries_slot_offer_consistency_deferred` → `request_engine.check_offered_slot_offer_source_consistency()`

`slot_offers_00_guard_subject_match` is intentionally absent. Its function checked only the Hold/Waitlist subject relation already enforced by `guard_slot_offer_live_hold()` and was therefore a duplicate mutation path, not an independent invariant.

## Discovery ↔ Booking handoff fence — 2

Discovery options are advisory, but Booking commitment must fence the exact Discovery publication/mapping observation inside the Reservation transaction. The Discovery module contract explicitly permits this narrow PostgreSQL composition boundary.

- `reservations.reservations_guard_discovery_handoff` → `request_engine.guard_discovery_handoff_reservation()`
- `reservations.reservations_guard_discovery_latest_version` → `request_engine.guard_discovery_handoff_latest_version()`

These functions are not classified as ordinary Discovery-local guards: they are the transactional Discovery ↔ Booking fence.

## Live Capacity ↔ Operational Recovery freshness propagation — 11

These triggers advance the synchronous recovery source revision when authoritative facts that can change the F4/F5 assessment scope change. They are the reason the freshness ledger is not disposable shadow state.

- `capacity_claims.capacity_claims_bump_recovery_source_revision` → `request_engine.bump_capacity_claim_recovery_source_revision()`
- `live_capacity_projection_policies.live_capacity_projection_policies_bump_recovery_source_revision` → `request_engine.bump_projection_policy_recovery_source_revision()`
- `live_capacity_workload_estimate_policies.live_capacity_workload_estimate_policies_bump_recovery_source_r` → `request_engine.bump_estimate_policy_recovery_source_revision()`
- `locations.locations_bump_recovery_source_revision` → `request_engine.bump_location_revision_recovery_sources()`
- `queue_entries.queue_entries_bump_recovery_source_revision` → `request_engine.bump_queue_recovery_source_revision()`
- `reservations.reservations_bump_recovery_source_revision` → `request_engine.bump_reservation_recovery_source_revision()`
- `resource_activities.resource_activities_bump_recovery_source_revision` → `request_engine.bump_resource_activity_recovery_source_revision()`
- `resources.resources_bump_recovery_source_revision` → `request_engine.bump_resource_revision_recovery_sources()`
- `service_queue_intake_controls.service_queue_intake_controls_bump_recovery_source_revision` → `request_engine.bump_intake_control_recovery_source_revision()`
- `service_session_interruptions.service_session_interruptions_bump_recovery_source_revision` → `request_engine.bump_interruption_recovery_source_revision()`
- `service_sessions.service_sessions_bump_recovery_source_revision` → `request_engine.bump_service_session_recovery_source_revision()`

Classification: `KEEP` as the explicit Live Capacity ↔ Operational Recovery transactional freshness boundary.

## Queue ↔ Delivery lifecycle coherence — 2

- `queue_entries.queue_entries_service_session_coherence` → `request_engine.assert_service_queue_coherence()`
- `service_sessions.service_sessions_queue_entry_coherence` → `request_engine.assert_service_queue_coherence()`

These are database invariant backstops around the atomic StartService/CompleteService composition. `0043` separately moved supported mutation through `request_cmd.mark_queue_entry_service_started/completed`, so the trigger does not justify direct cross-owner adapter writes.

## Shared Platform persistence mechanics — 67

These are not business composition boundaries. They install one of the reviewed generic persistence helpers on owner tables:

- `request_engine.touch_updated_at()` — timestamp maintenance;
- `request_engine.guard_exact_revision_step()` — generic optimistic revision-step invariant;
- `request_engine.reject_immutable_mutation()` — generic append-only enforcement.

The relation retains its capability owner; Platform owns only the reusable mechanism. The catalog/routine manifests account for the relations and functions independently.

Classification: `KEEP`.

## Capability-local invariants — 71

The remaining 71 triggers invoke a routine classified to the same capability as the relation. They include Booking capacity/provenance guards, Queue lifecycle/FIFO facts, Delivery execution/interruption guards, Discovery publication/mapping lifecycle, Tenancy identity/contact facts, Catalog operational revisions, Communications transitions, Live Capacity policy guards, Operational Recovery immutable/transition facts, Requests lifecycle and local Platform worker mechanics.

The removed `availability_schedules_bump_resource` trigger belonged to this class. Its removal follows directly from removal of the pre-launch `availability_schedules` recurring-authority table; `schedule_exceptions` and contextual assignment children retain their current Resource revision propagation paths.

Because both sides of each surviving installation have already been exhaustively mapped in `postgresql-relation-ownership.md` and `postgresql-routine-ownership.md`, these triggers require no artificial cross-module owner.

Classification: `KEEP`.

## Rebaseline implication

The trigger topology has no remaining unexplained cross-owner installation in the post-`0048` model. Final exact-head CI must confirm the effective catalog contains 162 triggers, no `availability_schedules_bump_resource`, no `slot_offers_00_guard_subject_match`, and no `guard_slot_offer_subject_match()` routine. Any later migration that changes those counts requires re-running the topology classification rather than treating these numbers as a permanent repository freeze.
