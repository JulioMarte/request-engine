# F7e Same-Day Selection Semantics — normative amendment draft

Status: scratch-branch decision record for F7e. The implementation and proofs described here are prepared on `tmp/f7e-same-day-selection-semantics` but are **not CI-validated, merged or normative product state yet**. This document closes the semantic gate that blocked implementation in `36-front-desk-operations-contract.md` §7 and must be folded into the canonical F7 contract after the serialized integration lane is available.

## 1. Preserved invariants

F7e does not create a priority queue or mutable queue position.

- Default selection remains FIFO by `(admitted_at, id)`.
- Queue position remains derived.
- `ServiceQueue` remains the selection serialization root and is locked before any selected/target `QueueEntry`.
- `waiting`, `called`, `serving`, `completed`, `cancelled`, `no_show` remain the QueueEntry lifecycle states. Hold/skip are selection facts, not lifecycle states.
- One active QueueEntry per `(ServiceQueue, subject Party)` remains unchanged.
- Terminal lifecycle state supersedes a recall gate. An unreleased historical hold on an entry that is no longer `waiting` is not an active gate and does not make F4 indeterminate.
- Terminal exits remain terminal; F7e cannot resurrect them.

## 2. Closed commands

### `queue.operator_select`

Calls one specific `waiting` QueueEntry now without rewriting FIFO order.

Closed reason set:

```text
urgent_operational_need
booked_time_due
operator_override
```

These are operational dispatch reasons only. They must not encode diagnosis, symptoms or clinical triage scores.

The command requires the QueueEntry `expected_revision`; this is a directed operator click and stale UI intent must not act on a newer QueueEntry state.

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock target QueueEntry
validate target belongs to queue and is waiting
validate target revision
validate target has no active recall hold
transition target to called
append selection fact + audit + queue.entry_called.v1
commit
```

`operator_select` uses the same called transition and outbox consequence as `call_next`. If the target is no longer waiting, held or revision-stale, the command loses cleanly and makes no partial selection fact.

### `queue.recall_hold`

Creates or replaces the current hold gate for one `waiting` QueueEntry. The QueueEntry remains `waiting`; `admitted_at` and position truth do not change.

Closed hold kinds:

```text
until_time
until_customer_initiates
```

`until_event` remains reserved in the broader F7 vocabulary but is **not implementable in v1** until a closed authoritative event-source contract exists. The API does not accept it; Request Engine must not invent event matching or a generic condition DSL.

`until_time`:

- requires `release_at` as an offset-aware instant strictly after the transaction database clock;
- is active while `release_at > observed database time`;
- expires derivatively from the database clock; no ScheduledAction is required for correctness;
- expiry does not rewrite history or fabricate `released_at`. The unreleased row simply ceases to be a gate.

`until_customer_initiates`:

- has no timestamp expiry;
- remains active until an explicit `queue.release_recall_hold` command by an operator or a future customer-authority lowering separately admitted by contract;
- F7e v1 exposes only the operator release command. No inbound bot/customer release is inferred here.

Multiple QueueEntries may be held simultaneously. At most one unreleased hold row exists per QueueEntry. Creating a replacement closes the previous row append-preservingly and creates a new hold fact.

`recall_hold` requires `expected_revision`. A successful create/replacement increments `QueueEntry.revision`; therefore a stale screen cannot replace a newer hold using the old revision.

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock QueueEntry
validate waiting + expected_revision
validate hold shape / database-time rule
close current unreleased hold if one exists
increment QueueEntry revision
append new hold fact
append audit/outbox
commit
```

### `queue.release_recall_hold`

Explicitly releases the **exact hold the operator observed**. The command requires:

```text
queue_entry_id
hold_id
expected_revision
```

This is intentionally stronger than “release whatever hold is current”. A stale click must never release a replacement hold created after the screen was read.

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock QueueEntry
validate waiting + expected_revision
lock exact active hold_id for that QueueEntry
if exact hold is absent/expired -> deterministic no-op
otherwise populate release metadata once
increment QueueEntry revision
append audit/outbox
commit
```

A successful explicit release advances `QueueEntry.revision`. Derived expiry of `until_time` does not.

### `queue.skip`

A skip is a **single-selection defer**, never a reorder.

- It applies only to the current eligible FIFO head at the moment the ServiceQueue lock is held.
- It records that the head was intentionally bypassed for one selection attempt.
- In the same transaction, `skip` selects and calls the next eligible waiting entry, if any.
- The skipped entry remains `waiting` with unchanged `admitted_at` and unchanged revision.
- After commit, the skip has no future gating effect. The skipped entry is again eligible for the next ordinary `call_next` unless a recall hold or lifecycle transition makes it ineligible.
- If no second eligible entry exists, `skip` records the defer and returns no called entry; the skipped entry remains immediately eligible for the next selection attempt.

Protocol:

```text
acquire idempotency
lock ServiceQueue
select+lock up to two eligible FIFO entries using the same selector as call_next
record first as skipped
if second exists: transition second to called and emit queue.entry_called.v1
append selection fact + audit/outbox for skip
commit
```

`skip` is count-bounded by definition: one command can bypass exactly one head for exactly one selection attempt.

## 3. Automatic `call_next` eligibility

The degenerate path with no active holds is unchanged semantically and must return the same QueueEntry as the pre-F7e rule.

There is one shared Queue-owned eligible-FIFO selector used by ordinary `call_next` and `skip`:

```text
QueueEntry.status = waiting
AND no active recall hold at database transaction time
ORDER BY admitted_at, id
```

An `until_time` row with `release_at <= clock_timestamp()` is not active and does not require a release write before selection.

`call_next` does not consume or rewrite expired hold history.

## 4. Durable facts

F7e uses a Queue-owned append-oriented `queue_selection_facts` relation for operator selection/skip history and a Queue-owned append-preserving `queue_recall_holds` relation for hold history/current gating.

`queue_recall_holds` minimum fields:

```text
organization_id
id
service_queue_id
queue_entry_id
hold_kind
release_at?
reason?
created_by_principal_id
created_at
released_at?
released_by_principal_id?
release_reason?
```

Backstops:

- tenant-composite FKs to ServiceQueue, QueueEntry and principals;
- QueueEntry must belong to the referenced ServiceQueue;
- hold insert requires the target QueueEntry to be `waiting`;
- one unreleased row per QueueEntry via partial unique index;
- `until_time` requires `release_at`; `until_customer_initiates` forbids it;
- hold meaning/identity is immutable; only one release transition may populate release metadata;
- forced RLS applies to the relation.

`queue_selection_facts` minimum fields:

```text
organization_id
id
service_queue_id
queue_entry_id
selection_kind = operator_select | skip
reason
selected_by_principal_id
selected_at
called_queue_entry_id?   # for skip, the entry actually called in the same transaction
```

Database backstops verify that an `operator_select` fact references an entry that is actually `called`, a `skip` target remains `waiting`, and any `called_queue_entry_id` is in the same queue and actually `called`.

Selection facts never become ordering authority.

## 5. Reads and projections

### 5.1 Staff live queue

Queue remains the owner of recall-hold truth. Existing `queue.staff_read` joins the current active hold for each live QueueEntry and exposes:

```text
recall_hold_kind?
recall_hold_release_at?
```

It does not expose a stored queue position and does not reconstruct hold state into terminal history. `queue.staff_history_read` returns the new hold fields as null because a live gate is not a terminal lifecycle fact.

The Booking-owned F7g day board is **not** changed to join Queue internals in this tranche. Any future one-screen composition across Reservation and Queue facts requires an explicit owner-backed contract amendment; F7e does not create a second hold truth in Booking.

### 5.2 F4 live-capacity projection

Held work remains in the Queue projection snapshot; it is not dropped from workload merely because the entry is temporarily non-callable.

A Queue projection snapshot carries `has_active_recall_hold` when at least one unreleased gate applies to an entry that is still `waiting` at the snapshot time. F4 then returns:

```text
state = indeterminate
reason includes active_recall_hold
ETA/headroom derived from future order = unavailable
```

This is deliberately conservative. F7e v1 does not invent a reordered timeline or pretend the held patient's workload disappeared.

The customer live-capacity path applies the same blocker. `entries_ahead` remains the authoritative derived FIFO-membership count, but `estimated_wait_seconds` and `estimated_start` are null while future callable order is indeterminate.

## 6. Capabilities and authority

Operator-only capabilities:

```text
queue.operator_select          revision = required
queue.recall_hold              revision = required
queue.release_recall_hold      revision = required
queue.skip                     revision = server_selected
```

All mutations use the authenticated operator principal and mandatory idempotency. F7e grants no customer capability and performs no clinical priority inference.

The HTTP surface is Queue-owned and registered through the existing `add_capability_route` / canonical capability registry path; no second authorization mechanism exists.

## 7. Required PostgreSQL 18 proofs

Prepared on the scratch branch; none may be claimed passed until the canonical PostgreSQL lane executes them.

1. Degenerate equivalence: with no active holds/facts, `call_next` chooses the same `(admitted_at,id)` FIFO row.
2. `until_time` blocks selection before `release_at` and stops blocking after database time passes it without a release worker; expiry does not fabricate release history.
3. `until_customer_initiates` remains blocking until exact explicit release.
4. `skip` never changes `admitted_at`, bypasses exactly one eligible head for one selection attempt, and the skipped head is eligible again afterward.
5. `operator_select` calls the requested waiting row while bypassed rows remain waiting and ordered unchanged.
6. Concurrent `call_next` vs `operator_select` serializes on ServiceQueue; no target is double-called.
7. Concurrent `call_next` vs `recall_hold` has only coherent winner states: called/no-hold or waiting/held with the next eligible row called.
8. Concurrent `recall_hold` vs `recall_hold` with the same revision leaves exactly one current hold and one revision-conflict loser.
9. Concurrent `skip` vs `call_next` records the exact head observed under the ServiceQueue lock and never permanently reorders FIFO.
10. Staff live read exposes an active hold and clears it after release without changing terminal history semantics.
11. Cross-tenant rows remain opaque under forced RLS/runtime roles and public HTTP probes.
12. Out-of-order operator actions have audit/outbox consequences and append-oriented selection facts.
13. F4/customer projection degrades honestly under a waiting active recall hold and ignores historical holds after the QueueEntry leaves `waiting`.

## 8. Explicit non-goals

- no clinical triage scoring;
- no tenant-configurable priority policy;
- no generic condition/event DSL;
- no arbitrary reorder endpoint;
- no mutable position counter;
- no automatic dispatch from hold expiry;
- no customer/bot direct `operator_select` or `skip` authority;
- no `until_event` implementation until its authoritative event vocabulary is separately closed;
- no Booking-owned duplicate of recall-hold truth;
- no claim that this scratch implementation is integrated until exact-head CI runs after the serialized F7g lane is merged.
