# V3 worker fencing and crash-recovery inventory

Status: Phase 6 G09/G10 executable closure inventory.

This document freezes the worker-control surface and the failure claims that must be executable before G09 (worker concurrency/fencing) or G10 (crash/recovery) can move to `PASS`. It does not add a workflow engine, change provider business semantics, or promise exactly-once execution outside PostgreSQL.

Base for this closure: `development@cc46234c9e3e1c3109b0aa87484d83cbefe28633`.

## Durable work families

The production worker owns three technical work families:

| Family | Due state | Claimed state | Success state | Retry state | Terminal failure | Semantic rejection |
|---|---|---|---|---|---|---|
| ScheduledAction | `pending` | `leased` | `completed` | `pending` | `dead` | n/a |
| OutboxMessage | `pending` | `leased` | `delivered` | `pending` | `dead` | n/a |
| ProviderEvent | `received` | `leased` | `processed` | `received` | `dead` | `rejected` |

All three families use a fresh UUID `claim_token`, a finite `lease_until`, and a lifetime `attempt_count`. Reclaim replaces the token. No stale token may renew, finalize, retry, dead-letter, reject, or authorize a business write after ownership has moved.

## Frozen worker-control operations

### ScheduledAction

- `request_cmd.claim_scheduled_actions(integer, interval)`
- `request_cmd.renew_scheduled_action_lease(uuid, uuid, interval)`
- `request_cmd.complete_scheduled_action(uuid, uuid)`
- `request_cmd.retry_scheduled_action_after(uuid, uuid, interval, text)`
- `request_cmd.dead_letter_scheduled_action(uuid, uuid, text)`
- cancellation/fence operations used by authoritative modules
- `request_admin.replay_dead_scheduled_action(...)` only through trusted admin context

### OutboxMessage

- `request_cmd.claim_outbox_messages(integer, interval)`
- `request_cmd.renew_outbox_message_lease(uuid, uuid, interval)`
- `request_cmd.complete_outbox_message(uuid, uuid)`
- `request_cmd.retry_outbox_message_after(uuid, uuid, interval, text)`
- `request_cmd.dead_letter_outbox_message(uuid, uuid, text)`
- `request_cmd.lock_outbox_message_claim(...)` for app-role authoritative post-I/O writes
- `request_admin.replay_dead_outbox_message(...)` only through trusted admin context

### ProviderEvent

- `request_cmd.claim_provider_events(integer, interval)`
- `request_cmd.renew_provider_event_lease(uuid, uuid, interval)`
- `request_cmd.complete_provider_event(uuid, uuid)`
- `request_cmd.retry_provider_event_after(uuid, uuid, interval, text)`
- `request_cmd.dead_letter_provider_event(uuid, uuid, text)`
- `request_cmd.reject_provider_event(uuid, uuid, text)`
- `request_admin.replay_provider_event(...)` only through trusted admin context

Any future runtime control operation added to these families must be classified here and receive equivalent current-owner/stale-owner evidence before the release inventory remains closed.

## G09 concurrency/fencing claims

### R12 — claim vs claim

For each work family, two independent `request_engine_worker` sessions must overlap while claiming the same due row. `FOR UPDATE SKIP LOCKED` must make exactly one session the current owner of that row. The row must end with one `claim_token`, one lease and exactly one increment of `attempt_count` for that ownership transition.

Executable evidence: `tests/integration/v3_worker_runtime/test_worker_fencing_release_matrix.py::test_r12_claim_vs_claim_has_one_current_owner`, parametrized over ScheduledAction, OutboxMessage and ProviderEvent.

### R13 — stale finalizer vs reclaimed worker

After worker A's lease expires and worker B reclaims the row with a new token, A must be unable to complete, retry, dead-letter, reject ProviderEvent work, or otherwise clear or replace B's ownership. The final row must remain leased by B until B itself performs a valid transition.

Executable evidence: `test_r13_r14_reclaim_fences_every_stale_transition_and_late_renewal` exercises all three families. `tests/db/test_v3_worker_expired_leases.py` separately proves that an expired token cannot finalize even before another worker has reclaimed the row.

### R14 — late renewal vs reclaimed worker

An expired owner cannot extend its lease. After reclaim, the old token cannot renew the new owner's lease. Renewal must require the exact current token and an unexpired current lease.

Executable evidence: the same release matrix exercises stale renewal across all three families; `tests/db/test_v3_worker_runtime.py` and `test_v3_worker_expired_leases.py` preserve the lower-level lease-boundary regressions.

### R15 — ScheduledAction cancellation vs claim

Both serialized orders must remain valid: cancellation-first prevents a new claim; claim-first makes cancellation serialize with ownership and fences obsolete execution. A claimed-but-obsolete handler cannot perform a new authoritative consequence after cancellation wins.

Executable evidence: `tests/integration/v3_worker_runtime/test_scheduled_action_cancel_race.py` deliberately exercises both row-lock orders with real app/worker sessions. Cancellation-first makes worker discovery `SKIP LOCKED`; claim-first makes cancellation block until claim commit, then invalidates both the stale completion token and `lock_scheduled_action_claim` authority.

### R16 — Outbox completion vs lease reclaim

If completion wins while the lease is current, reclaim cannot subsequently acquire delivered work. If reclaim wins after expiry, the stale publisher/finalizer cannot mark the new owner's row delivered.

Executable evidence: `test_worker_fencing_release_matrix.py` proves both row-lock orders. Completion-first holds the Outbox row lock and a competing claim must skip it. Reclaim-first holds the replacement claim uncommitted while stale completion is observed blocked on the PostgreSQL row lock; after replacement commit, stale completion returns false and the new claimant remains authoritative.

## G10 crash/recovery claims

### Crash after claim commit

A process crash after durable claim commit leaves leased work reclaimable after `lease_until`, with a new token and a fenced old owner.

Executable evidence:

- ScheduledAction: `tests/integration/v3_worker_runtime/test_process_crash_recovery.py` starts a real subprocess, claims through `request_engine_worker`, fsyncs the token, then terminates itself with `SIGKILL`; a later worker reclaims and fences the dead process token.
- OutboxMessage and ProviderEvent: `test_process_crash_recovery_other_families.py` executes the same real-process SIGKILL boundary and requires fresh-token reclaim plus stale-completion rejection for both remaining families.

### Crash after idempotent internal consequence / before Outbox completion

`tests/integration/v3_worker_runtime/test_worker_runtime.py::test_outbox_replays_idempotent_local_effect_after_publish_crash` runs the internal consequence, fails the publisher, retries the same Outbox fact and requires semantic application once while the idempotent internal handler may be invoked again. Final Outbox state is delivered with lifetime `attempt_count = 2`.

Reservation lifecycle composition adds a business-level proof: `tests/integration/v3_reservation_lifecycle/test_reservation_lifecycle_outbox_composition.py` replays durable Reservation facts after independently committed partial scheduling/communications consequences and requires convergence without duplicate downstream state.

### Authoritative post-I/O fencing and external-effect recovery

A provider/network result cannot become authoritative merely because the worker once owned the work item. The app transaction publishing authoritative state must prove the exact current worker claim.

Two real provider-facing families exercise this boundary:

- **Communications:** `tests/integration/v3_worker_runtime/test_communication_fencing.py::test_worker_that_loses_lease_during_provider_io_cannot_finalize_delivery` lets `provider.send()` succeed while another worker reclaims the ScheduledAction. The stale worker raises `LeaseLostWorkError` and cannot mark the delivery delivered. The replacement claimant performs provider `lookup` rather than a second send, so `send_count == 1`, then publishes the recovered provider result under the current claim.
- **ReservationAccess:** `tests/integration/v3_delivery/test_reservation_access_races.py::test_lost_outbox_lease_cannot_publish_but_replay_reuses_provider_evidence` loses the Outbox lease during provisioning. The stale claimant leaves only non-authoritative pending evidence; the replacement claimant reuses provider evidence and does not create a second provider resource. `test_cancel_recovers_provider_success_that_crashed_before_db_evidence` additionally proves non-creating lookup when provider success occurred before local evidence was durably published.

These tests close the worker/crash ownership boundary. They do **not** claim the entire R20/G13 provider ambiguity matrix: provider callback reorder, ambiguous provider outcomes, reconciliation policy and communications failure semantics remain owned by G13. This branch may close G10 while R20 remains `PARTIAL` until that wider semantic claim is proven.

### Processing timeout and heartbeat loss

`tests/unit/test_worker_runtime_failure_boundaries.py` proves the asyncio runtime mechanics directly:

- a handler exceeding `processing_timeout` is cancelled and classified as retryable `processing_timeout` rather than completed/dead;
- heartbeat renewal failure produces `STALE` and suppresses complete/retry/dead finalization even if the processor later returns.

### Process/supervisor failure

The real SIGKILL tests above prove durable recovery after abrupt worker death. `test_worker_runtime_failure_boundaries.py` separately proves structured concurrency: an unexpected worker-stream failure cancels its sibling stream and propagates the specific stream failure through `TaskGroup`; the same graceful-stop event is shared with all streams.

### Retry, exhaustion, replay and history

Existing DB/runtime evidence remains part of the closure:

- `tests/db/test_v3_worker_runtime.py::test_retry_after_uses_database_clock_and_preserves_lifetime_attempt_count` requires DB-clock retry scheduling and monotonic lifetime attempts;
- `test_admin_replay_is_privileged_preserves_history_and_is_audited` proves the worker cannot replay, trusted admin replay adds attempt budget, preserves `attempt_count`, increments replay history and records actor/correlation audit provenance;
- terminal ProviderEvent rejected/dead semantics remain distinct;
- runtime poison/unknown work is dead-lettered instead of retrying forever.

### Bounded concurrency and tenant fairness

`FencedWorkerRuntime.run_once()` claims `min(claim_batch_size, max_concurrency)` and config validation caps both values. Existing DB tests prove rank-round fairness for ScheduledAction and OutboxMessage. `tests/db/test_v3_worker_provider_fairness.py` adds the equivalent ProviderEvent proof: with two due items for one hot tenant and one newer due item for a quiet tenant, claim order must be hot rank-1, quiet rank-1, then hot rank-2.

This closes fairness correctness only. Representative-cardinality query-plan/performance evidence for the ranking queries remains G15.

## Role boundary

Release evidence executes worker-control functions through a real `request_engine_worker` role. Business-state writes continue through `request_engine_app`. Admin/setup connections may construct fixtures and inspect final state, but they do not count as fencing proof.

`tests/integration/v3_worker_runtime/test_production_worker_assembly.py` proves that the production composition root receives separate worker/app factories, that the worker credential is a worker member but not an app member, and that Booking/Queue domain handlers receive the app factory while ScheduledAction/Outbox/ProviderEvent control stays on the worker side.

No G09/G10 closure may widen `request_engine_worker` into authoritative business DML or bypass the existing narrow SECURITY DEFINER fences.

## Promotion rule

G09 and G10 remain `PARTIAL` until the complete inventory above has current-branch executable evidence and the exact branch head passes canonical CI with a `VALID` candidate artifact. R12-R16 move independently only when their named interleaving is fully demonstrated with deliberate PostgreSQL overlap and final-state/cardinality assertions.

Global V3 release status remains `NOT_READY` after this branch; ProviderEvent/communications ambiguity (G13), invariant registry closure (G05), API freeze (G16), performance/index proof (G15), `0001_initial` equivalence (G17), unified adversarial proof (G18), production-like bootstrap (G19), and the exact-head final manifest (G20) remain separate release work.