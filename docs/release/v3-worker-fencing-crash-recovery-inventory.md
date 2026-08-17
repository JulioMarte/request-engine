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

### R13 — stale finalizer vs reclaimed worker

After worker A's lease expires and worker B reclaims the row with a new token, A must be unable to:

- complete;
- retry;
- dead-letter;
- reject ProviderEvent work;
- otherwise clear or replace B's ownership.

The final row must remain leased by B until B itself performs a valid transition.

### R14 — late renewal vs reclaimed worker

An expired owner cannot extend its lease. After reclaim, the old token cannot renew the new owner's lease. Renewal must require the exact current token and an unexpired current lease.

### R15 — ScheduledAction cancellation vs claim

Both serialized orders must remain valid: cancellation-first prevents a new claim; claim-first makes cancellation serialize with ownership and fences obsolete execution. A claimed-but-obsolete handler cannot perform a new authoritative consequence after cancellation wins.

### R16 — Outbox completion vs lease reclaim

If completion wins while the lease is current, reclaim cannot subsequently acquire delivered work. If reclaim wins after expiry, the stale publisher/finalizer cannot mark the new owner's row delivered.

## G10 crash/recovery claims

The executable crash matrix must cover these boundaries without relying on worker host time:

1. **Crash after claim commit:** leased work remains durable and becomes reclaimable after `lease_until` with a new token.
2. **Crash after idempotent internal consequence:** replay converges without duplicate semantic state.
3. **Crash after authoritative domain commit but before worker completion:** reclaim/replay observes the committed business result and converges without a second business mutation.
4. **External effect succeeds but local finalization is missing:** the runtime must not blindly create an uncontrolled duplicate semantic effect. Stable provider identity/evidence and reconciliation are required; provider-specific ambiguity closure remains owned by G13.
5. **Processing timeout/cancellation:** a hung handler cannot renew forever; timeout becomes retryable `processing_timeout` work and the lease can eventually be reclaimed.
6. **Process/supervisor failure:** abrupt process death leaves leased rows recoverable; unexpected stream failure cancels siblings without falsely completing unfinished work; graceful shutdown stops new claiming.
7. **Retry/dead transition:** attempt counts remain monotonic, max-attempt exhaustion is terminal, and admin replay adds budget without resetting lifetime history.

## Role boundary

Release evidence must execute worker-control functions through a real `request_engine_worker` role. Business-state writes continue through `request_engine_app`. Admin/setup connections may construct fixtures and inspect final state, but they do not count as fencing proof.

No G09/G10 closure may widen `request_engine_worker` into authoritative business DML or bypass the existing narrow SECURITY DEFINER fences.

## Promotion rule

G09 and G10 remain `PARTIAL` until the complete inventory above has current-branch executable evidence and the exact branch head passes canonical CI with a `VALID` candidate artifact. R12-R16 move independently only when their named interleaving is fully demonstrated with deliberate PostgreSQL overlap and final-state/cardinality assertions.

Global V3 release status remains `NOT_READY` after this branch; ProviderEvent/communications ambiguity (G13), invariant registry closure (G05), API freeze (G16), performance/index proof (G15), `0001_initial` equivalence (G17), unified adversarial proof (G18), production-like bootstrap (G19), and the exact-head final manifest (G20) remain separate release work.