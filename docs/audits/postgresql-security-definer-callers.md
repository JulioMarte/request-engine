# PostgreSQL SECURITY DEFINER caller manifest

Status: pre-rebaseline effective-model audit

Source checkpoint: exact PostgreSQL 18 catalog from green head `3aa13def2102e3fdb225d5a7302971f8f8db824b`, CI #4126, after migrations through `0049_consolidate_recovery_bump`.

The effective catalog contains **69 SECURITY DEFINER routines**. All 69 have an explicit owner/caller topology below. There are:

- **0 PUBLIC EXECUTE grants**;
- **0 grantable routine grants**;
- **0 SECURITY DEFINER routines with an unclassified caller set**.

The schema owner naturally retains owner execution authority; the lists below describe the meaningful non-owner runtime/admin caller classes.

## `request_admin.*` — admin-only, 9

Caller: `request_engine_admin` only.

- `activate_shared_capacity_binding`
- `create_global_identity`
- `create_service_classification`
- `create_shared_capacity_identity`
- `replay_dead_outbox_message`
- `replay_dead_scheduled_action`
- `replay_provider_event`
- `retire_service_classification`
- `revoke_shared_capacity_binding`

These are explicit administrative authority surfaces. They must not become app/worker callable merely because a rebaseline can express their DDL more compactly.

Classification: `KEEP`.

## `request_cmd.*` — worker/admin runtime primitives, 19

Callers: `request_engine_worker` + `request_engine_admin`.

- `claim_outbox_messages`
- `claim_provider_events`
- `claim_scheduled_actions`
- `complete_outbox_message`
- `complete_provider_event`
- `complete_scheduled_action`
- `dead_letter_outbox_message`
- `dead_letter_provider_event`
- `dead_letter_scheduled_action`
- `find_recovery_sweep_scopes`
- `reject_provider_event`
- `renew_outbox_message_lease`
- `renew_provider_event_lease`
- `renew_scheduled_action_lease`
- `retry_outbox_message`
- `retry_outbox_message_after`
- `retry_provider_event_after`
- `retry_scheduled_action`
- `retry_scheduled_action_after`

These are lease/fencing/retry/worker primitives and one recovery sweep discovery command. Ordinary app execution would broaden worker authority unnecessarily.

Classification: `KEEP`.

## `request_cmd.*` — app/admin lock primitives, 4

Callers: `request_engine_app` + `request_engine_admin`.

- `cancel_scheduled_action`
- `lock_outbox_message_claim`
- `lock_recovery_source_revision`
- `lock_shared_capacity_roots`

These are narrow command/serialization surfaces used by current application orchestration. They do not expose workflow-sized stored procedures.

Classification: `KEEP`.

## `request_cmd.lock_scheduled_action_claim` — app + worker, 1

Callers: `request_engine_app` + `request_engine_worker`.

This shared lock/fencing primitive is needed on both the orchestration and worker sides of ScheduledAction handling. Admin does not need a separate explicit grant because this is not the admin replay surface.

Classification: `KEEP`.

## `request_cmd.*` — app-only composition commands, 3

Caller: `request_engine_app`.

- `mark_queue_entry_service_completed`
- `mark_queue_entry_service_started`
- `schedule_recovery_reassessment`

The first two are the explicit Queue ↔ Delivery atomic mutation boundary. The third is the application-side scheduling/coalescing boundary for recovery reassessment.

Classification: `KEEP`.

## Trigger/internal invariant routines — owner/trigger only, 19

No non-owner EXECUTE caller.

- `attach_shared_capacity_claim_link`
- `bump_capacity_claim_recovery_source_revision`
- `bump_direct_queue_recovery_source_revision`
- `bump_estimate_policy_recovery_source_revision`
- `bump_intake_control_recovery_source_revision`
- `bump_interruption_recovery_source_revision`
- `bump_location_revision_recovery_sources`
- `bump_recovery_source_revision`
- `bump_reservation_recovery_source_revision`
- `bump_resource_activity_recovery_source_revision`
- `bump_resource_revision_recovery_sources`
- `bump_service_session_recovery_source_revision`
- `check_capacity_owner_completeness`
- `check_offered_slot_offer_source_consistency`
- `guard_capacity_claim`
- `guard_linked_capacity_claim_provenance`
- `guard_shared_capacity_rebinding`
- `initialize_service_queue_intake_control`
- `require_trusted_actor_context`

These routines exist as trigger/invariant internals. Their absence of app/worker EXECUTE is intentional least privilege, not a missing grant.

Classification: `KEEP`.

## App-owned identity/lookup definer surfaces — 7

Caller: `request_engine_app`.

- `bind_consumed_identity_candidate_v1`
- `consume_identity_exchange_candidate_v1`
- `create_identity_exchange_candidate_v1`
- `identity_exchange_existing_party_v1`
- `lookup_active_service_classification`
- `lookup_service_classification`
- `publish_portable_party_v1`

These are bounded Tenancy/Discovery support surfaces used by application orchestration. The historical `_v1` suffix on identity-exchange functions is not by itself a legacy-removal signal; the functions remain current consumers of the federated identity contract.

Classification: `KEEP`.

## Discovery definer owner — 6

All six are owned by `request_engine_discovery_definer`, the dedicated `NOLOGIN BYPASSRLS` definer role. Caller sets are intentionally different by surface.

### Public Discovery search/handoff issue — 2

Callers: `request_engine_discovery` + `request_engine_admin`.

- `issue_discovery_booking_handoff`
- `search_discovery_candidates_v2`

These are the cross-tenant Discovery projection/opaque-handoff surfaces. They must not become ordinary app callable.

Classification: `KEEP`.

### Booking handoff read — 1

Callers: `request_engine_app` + `request_engine_admin`.

- `read_discovery_booking_handoff`

Booking needs to consume the opaque handoff inside its tenant-authoritative path; the cross-tenant search role does not need this read.

Classification: `KEEP`.

### Trigger/admin Discovery fences — 3

Caller: `request_engine_admin` as the only non-owner explicit EXECUTE grantee.

- `guard_discovery_handoff_latest_version`
- `guard_discovery_handoff_reservation`
- `has_active_discovery_mapping`

The two guards execute principally as database trigger functions; they are not app-callable mutation APIs. Their definer object/row-lock authority is reviewed separately in `postgresql-security-privilege-topology.md`.

Classification: `KEEP`.

## `request_read.recovery_source_revision` — app/admin read boundary, 1

Callers: `request_engine_app` + `request_engine_admin`.

This is the explicit read side of the Live Capacity ↔ Operational Recovery freshness-fence boundary.

Classification: `KEEP`.

## One app/admin Discovery read helper — 1

Caller set: `request_engine_app` + `request_engine_admin`.

- `request_engine.read_discovery_booking_handoff`

This routine is listed in the Discovery-definer section above and counted there among the six definer-owned routines. It is called out here only to emphasize that the caller split is deliberate; it is **not** an additional routine in the total.

## Caller-topology totals

The 69 SECURITY DEFINER routines partition as follows:

| Caller/owner class | Count |
|---|---:|
| admin-only `request_admin.*` | 9 |
| worker + admin `request_cmd.*` | 19 |
| app + admin `request_cmd.*` | 4 |
| app + worker scheduled-action lock | 1 |
| app-only `request_cmd.*` | 3 |
| trigger/internal owner-only | 19 |
| app identity/lookup helpers | 7 |
| Discovery-definer owned | 6 |
| app + admin `request_read` freshness read | 1 |
| **Total** | **69** |

## Rebaseline implication

SECURITY DEFINER caller topology is exhaustively classified for the #4126 effective schema. A clean baseline must reproduce the **authority classes**, not necessarily historical GRANT statement ordering.

Final exact-head requirements:

1. SECURITY DEFINER routine count and ownership must be reconcilable against the final routine manifest;
2. no routine may gain PUBLIC EXECUTE or `WITH GRANT OPTION`;
3. trigger/internal routines must remain without unnecessary app/worker execution;
4. `request_engine_discovery_definer` must remain `NOLOGIN`, membership-free and narrowly privileged;
5. worker/admin/app caller partitions must not broaden silently.

No current SECURITY DEFINER routine is classified `REMOVE`, `RESHAPE` or `NEEDS_PROOF`.
