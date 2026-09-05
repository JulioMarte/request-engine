# PostgreSQL routine ownership manifest

Status: pre-rebaseline effective-model audit

Source: effective catalog version 5 from green head `4a4a3e20ad79cecf59132f55b8fd671023b06427`, adjusted for `0044_remove_redundant_slot_guard`, which removes only `request_engine.guard_slot_offer_subject_match()`.

Every surviving routine is accounted for exactly once: **146/146 classified, 0 unclassified**. `Capability owner` describes semantic responsibility. Entries under `composition:*` are intentionally cross-capability PostgreSQL boundaries and are not assigned falsely to one module.

Unless stated otherwise, classification is `KEEP`.

## Booking — 29

- `request_admin.activate_shared_capacity_binding()`
- `request_admin.create_shared_capacity_identity()`
- `request_admin.revoke_shared_capacity_binding()`
- `request_cmd.lock_shared_capacity_roots()`
- `request_engine.assert_hold_claim_completeness()`
- `request_engine.assert_reservation_claim_completeness()`
- `request_engine.attach_shared_capacity_claim_link()`
- `request_engine.bump_resource_availability_revision()`
- `request_engine.bump_resource_from_assignment()`
- `request_engine.bump_resource_from_assignment_child()`
- `request_engine.check_capacity_owner_completeness()`
- `request_engine.guard_booking_context_terms_scope()`
- `request_engine.guard_capacity_claim()`
- `request_engine.guard_capacity_claim_contextual_assignment()`
- `request_engine.guard_capacity_claim_replacement_provenance()`
- `request_engine.guard_capacity_claim_tenant_context()`
- `request_engine.guard_capacity_claim_terminal_transition()`
- `request_engine.guard_capacity_hold_provenance_update()`
- `request_engine.guard_hold_transition()`
- `request_engine.guard_linked_capacity_claim_provenance()`
- `request_engine.guard_person_shared_capacity_cardinality()` — Booking invariant that reads Tenancy GlobalIdentity to constrain SharedCapacity identity cardinality.
- `request_engine.guard_promoted_capacity_claim_owner()`
- `request_engine.guard_reservation_transition()`
- `request_engine.guard_resource_commitment_sensitive_change()`
- `request_engine.guard_resource_location_assignment()`
- `request_engine.guard_shared_capacity_binding()`
- `request_engine.guard_shared_capacity_rebinding()`
- `request_engine.lock_booking_context_terms_resource()`
- `request_engine.lock_offering_version_booking_terms_root()`

## Catalog — 3

- `request_engine.bump_location_operational_revision_from_child()`
- `request_engine.guard_location_operational_revision()`
- `request_engine.validate_offering_version_delivery_policy()`

## Communications — 2

- `request_engine.guard_communication_escalations()`
- `request_engine.guard_reminder_plan_transition()`

## Delivery — 5

- `request_engine.assert_session_interruption_coherence()`
- `request_engine.guard_live_resource_occupation()` — Delivery serialization invariant over Booking Resource/assignment configuration.
- `request_engine.guard_resource_activity_transition()`
- `request_engine.guard_service_session_interruption_transition()`
- `request_engine.guard_service_session_transition()`

## Discovery — 13

- `request_admin.create_service_classification()`
- `request_admin.retire_service_classification()`
- `request_engine.guard_discovery_handoff_latest_version()`
- `request_engine.guard_discovery_handoff_reservation()`
- `request_engine.guard_f2_mapping_lifecycle()`
- `request_engine.guard_f2_publication_broad_specific_overlap()`
- `request_engine.guard_f2_publication_lifecycle()`
- `request_engine.has_active_discovery_mapping()`
- `request_engine.issue_discovery_booking_handoff()`
- `request_engine.lookup_active_service_classification()`
- `request_engine.lookup_service_classification()`
- `request_engine.read_discovery_booking_handoff()`
- `request_engine.search_discovery_candidates_v2()` — explicit cross-tenant projection over approved Tenancy/Catalog/Booking public facts, owned by Discovery's published search contract.

## Live Capacity — 2

- `request_engine.guard_live_capacity_projection_policy()`
- `request_engine.guard_live_capacity_workload_estimate_policy()`

## Operational Recovery — 4

- `request_cmd.find_recovery_sweep_scopes()`
- `request_engine.guard_operational_recovery_escalation()`
- `request_engine.guard_operational_recovery_execution()`
- `request_engine.guard_operational_recovery_proposal()`

## Platform — 33

- `request_admin.replay_dead_outbox_message()`
- `request_admin.replay_dead_scheduled_action()`
- `request_admin.replay_provider_event()`
- `request_cmd.acquire_idempotency()`
- `request_cmd.cancel_scheduled_action()`
- `request_cmd.claim_outbox_messages()`
- `request_cmd.claim_provider_events()`
- `request_cmd.claim_scheduled_actions()`
- `request_cmd.complete_idempotency()`
- `request_cmd.complete_outbox_message()`
- `request_cmd.complete_provider_event()`
- `request_cmd.complete_scheduled_action()`
- `request_cmd.dead_letter_outbox_message()`
- `request_cmd.dead_letter_provider_event()`
- `request_cmd.dead_letter_scheduled_action()`
- `request_cmd.lock_outbox_message_claim()`
- `request_cmd.lock_scheduled_action_claim()`
- `request_cmd.reject_provider_event()`
- `request_cmd.renew_outbox_message_lease()`
- `request_cmd.renew_provider_event_lease()`
- `request_cmd.renew_scheduled_action_lease()`
- `request_cmd.retry_outbox_message()`
- `request_cmd.retry_outbox_message_after()`
- `request_cmd.retry_provider_event_after()`
- `request_cmd.retry_scheduled_action()`
- `request_cmd.retry_scheduled_action_after()`
- `request_engine.current_authenticated_principal_id()`
- `request_engine.current_correlation_id()`
- `request_engine.current_organization_id()`
- `request_engine.guard_exact_revision_step()`
- `request_engine.reject_immutable_mutation()`
- `request_engine.require_trusted_actor_context()`
- `request_engine.touch_updated_at()`

## Queue — 12

- `request_engine.assert_arrival_estimate_reservation_confirmed()` — Queue check-in/arrival invariant referencing a Booking Reservation.
- `request_engine.guard_operational_workload_classification()`
- `request_engine.guard_queue_entry_recall_hold()`
- `request_engine.guard_queue_entry_skip()`
- `request_engine.guard_queue_entry_transition()`
- `request_engine.guard_reservation_arrival_estimate()`
- `request_engine.guard_slot_opportunity_provenance_update()`
- `request_engine.guard_slot_opportunity_transition()`
- `request_engine.guard_waitlist_entry_provenance_update()`
- `request_engine.initialize_queue_entry_times()`
- `request_engine.initialize_service_queue_intake_control()`
- `request_engine.reject_queue_entry_operator_selection_mutation()`

## Requests — 1

- `request_engine.guard_request_transition()`

## Tenancy — 17

- `request_admin.create_global_identity()` — Tenancy identity creation; also appends to the shared identity authority ledger described below.
- `request_engine.bind_consumed_identity_candidate_v1()`
- `request_engine.consume_identity_exchange_candidate_v1()`
- `request_engine.create_identity_exchange_candidate_v1()`
- `request_engine.guard_party_administrative_identifier_facts()`
- `request_engine.guard_party_contact_point_verification()`
- `request_engine.guard_party_identity_documents()`
- `request_engine.guard_party_identity_revisions()`
- `request_engine.guard_party_kind_immutable()`
- `request_engine.guard_principal_contacts()`
- `request_engine.identity_exchange_country_code_v1()`
- `request_engine.identity_exchange_existing_party_v1()`
- `request_engine.identity_exchange_identifier_valid_v1()`
- `request_engine.identity_exchange_subject_kind_v1()`
- `request_engine.lock_current_party_authority()`
- `request_engine.publish_portable_party_v1()`
- `request_engine.resolve_current_party_authority()`

## Booking ↔ Queue composition — 6

Released-slot recovery composes Queue interest/opportunity facts with Booking Hold/Claim/OfferingVersion authority. The retained functions enforce that composition without transferring ownership of either source model.

- `request_engine.assert_offered_slot_offer_source_consistency()`
- `request_engine.assert_slot_offer_consistency()`
- `request_engine.check_offered_slot_offer_source_consistency()`
- `request_engine.guard_slot_offer_live_hold()`
- `request_engine.guard_slot_offer_provenance_update()`
- `request_engine.guard_slot_offer_transition()`

`request_engine.guard_slot_offer_subject_match()` is intentionally absent: `0044` removes it because `guard_slot_offer_live_hold()` already enforces the same subject invariant plus the complete live-hold/source consistency contract.

## Live Capacity ↔ Operational Recovery composition — 15

These routines maintain/read the synchronous recovery freshness fence and schedule/coalesce reassessment. Their cross-owner source reads are intentional because the fence exists specifically to version the F4/F5 composition scope.

- `request_cmd.lock_recovery_source_revision()`
- `request_cmd.schedule_recovery_reassessment()`
- `request_engine.bump_capacity_claim_recovery_source_revision()`
- `request_engine.bump_estimate_policy_recovery_source_revision()`
- `request_engine.bump_intake_control_recovery_source_revision()`
- `request_engine.bump_interruption_recovery_source_revision()`
- `request_engine.bump_location_revision_recovery_sources()`
- `request_engine.bump_projection_policy_recovery_source_revision()`
- `request_engine.bump_queue_recovery_source_revision()`
- `request_engine.bump_recovery_source_revision()`
- `request_engine.bump_reservation_recovery_source_revision()`
- `request_engine.bump_resource_activity_recovery_source_revision()`
- `request_engine.bump_resource_revision_recovery_sources()`
- `request_engine.bump_service_session_recovery_source_revision()`
- `request_read.recovery_source_revision()`

## Queue ↔ Delivery composition — 3

- `request_cmd.mark_queue_entry_service_completed()`
- `request_cmd.mark_queue_entry_service_started()`
- `request_engine.assert_service_queue_coherence()`

These are the explicit atomic lifecycle boundary introduced/hardened by `0043`; Delivery owns ServiceSession execution and Queue owns QueueEntry waiting/calling state.

## Tenancy ↔ Booking authority-ledger composition — 1

- `request_engine.stamp_shared_capacity_authority_event_context()`

`shared_capacity_authority_events` records both `global_identity.created` and SharedCapacity identity/binding authority events. It is therefore a cross-boundary authority ledger rather than ordinary Booking state. `create_global_identity()` remains Tenancy-owned; SharedCapacity identity/binding commands remain Booking-owned.

## Totals

| Owner / explicit composition | Routines |
|---|---:|
| Platform | 33 |
| Booking | 29 |
| Tenancy | 17 |
| Live Capacity + Operational Recovery | 15 |
| Discovery | 13 |
| Queue | 12 |
| Booking + Queue | 6 |
| Delivery | 5 |
| Operational Recovery | 4 |
| Queue + Delivery | 3 |
| Catalog | 3 |
| Communications | 2 |
| Live Capacity | 2 |
| Requests | 1 |
| Tenancy + Booking authority ledger | 1 |
| **Total** | **146** |

## Rebaseline implication

Routine ownership is no longer unclassified for the post-`0044` effective topology. Final exact-head catalog validation must still prove that the removed SlotOffer routine is absent and that no later migration added an unclassified routine. Trigger ownership must be audited separately because one routine may be installed on several owner tables and that installation topology, not only function semantics, determines whether a cross-module persistence path is justified.
