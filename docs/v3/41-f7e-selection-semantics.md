# F7e Same-Day Selection Semantics — normative amendment draft

Status: scratch-branch decision record for F7e. This closes the implementation gate in `36-front-desk-operations-contract.md` §7 before any production branch changes `call_next`. It must be folded into the canonical F7 contract when the integration lane is available.

## 1. Preserved invariants

F7e does not create a priority queue or mutable queue position.

- Default selection remains FIFO by `(admitted_at, id)`.
- Queue position remains derived.
- `ServiceQueue` remains the selection serialization root and is locked before any selected/target `QueueEntry`.
- `waiting`, `called`, `serving`, `completed`, `cancelled`, `no_show` remain the QueueEntry lifecycle states. Hold/skip are selection facts, not lifecycle states.
- One active QueueEntry per `(ServiceQueue, subject Party)` remains unchanged.
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

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock target QueueEntry
validate target belongs to queue and is waiting
validate target has no active recall hold
transition target to called
append selection fact + audit + queue.entry_called.v1
commit
```

`operator_select` uses the same called transition and outbox consequence as `call_next`. If the target is no longer waiting, the command loses cleanly and makes no partial selection fact.

### `queue.recall_hold`

Creates or replaces the current hold gate for one `waiting` QueueEntry. The QueueEntry remains `waiting`; `admitted_at` and position truth do not change.

Closed hold kinds:

```text
until_time
until_customer_initiates
```

`until_event` remains reserved in the F7 vocabulary but is **not implementable in v1** until a closed authoritative event-source contract exists. The API must reject it rather than invent event matching or a generic condition DSL.

`until_time`:

- requires `release_at` as an offset-aware instant strictly after the transaction clock;
- is active while `release_at > clock_timestamp()`;
- expires derivatively from the database clock; no ScheduledAction is required for correctness;
- expiry does not rewrite history. The current gate simply ceases to be active.

`until_customer_initiates`:

- has no timestamp expiry;
- remains active until an explicit `queue.release_recall_hold` command by an operator or a future customer-authority lowering that is separately admitted by contract;
- F7e v1 exposes only the operator release command. No inbound bot/customer release is inferred here.

Multiple QueueEntries may be held simultaneously. At most one active hold exists per QueueEntry. Replacing a current hold closes the previous hold append-only and creates a new hold fact.

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock QueueEntry
validate waiting
close current active hold if one exists
append new hold fact
append audit/outbox
commit
```

### `queue.release_recall_hold`

Explicitly releases the current non-expired/non-derived hold for a waiting QueueEntry. It is idempotent. Releasing an already absent/expired hold is a semantic no-op with a deterministic replayable result.

### `queue.skip`

A skip is a **single-selection defer**, never a reorder.

- It applies only to the current automatic FIFO head at the moment the queue lock is held.
- It records that the head was intentionally bypassed for one automatic selection attempt.
- In the same transaction, `skip` selects and calls the next eligible waiting entry, if any.
- The skipped entry remains `waiting` with unchanged `admitted_at` and unchanged revision unless another queue fact independently requires revision movement.
- After that transaction commits, the skip has no future gating effect. The skipped entry is again the FIFO head for the next ordinary `call_next` unless a recall hold or another state transition makes it ineligible.
- If no second eligible entry exists, `skip` records the defer and returns no called entry; the skipped entry remains immediately eligible for the next selection attempt.

Protocol:

```text
acquire idempotency
lock ServiceQueue
select+lock current eligible FIFO head
record skip fact for that head
select+lock next eligible waiting entry excluding only the just-skipped entry for this transaction
if present: transition next entry to called and emit queue.entry_called.v1
append audit/outbox for skip
commit
```

`skip` is therefore count-bounded by definition: one command can bypass exactly one head for exactly one selection attempt.

## 3. Automatic `call_next` eligibility

The degenerate path with no active holds is unchanged semantically and must return the same QueueEntry as the pre-F7e implementation.

Automatic eligibility becomes:

```text
QueueEntry.status = waiting
AND no active recall hold at database transaction time
```

An `until_time` row with `release_at <= clock_timestamp()` is not active and does not require a release write before selection.

`call_next` does not consume or rewrite expired hold history.

## 4. Durable facts

Use a Queue-owned append-oriented `queue_selection_facts` relation for operator selection and skip history, and a Queue-owned append-oriented `queue_recall_holds` relation for hold history/current gating.

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

- tenant-composite FKs to ServiceQueue and QueueEntry;
- QueueEntry must belong to the referenced ServiceQueue;
- one current non-released hold row per QueueEntry via partial unique index;
- `until_time` requires `release_at`; `until_customer_initiates` forbids it;
- history rows are identity/meaning immutable; only the release transition may populate release fields once.

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

Selection facts never become ordering authority.

## 5. Reads and projections

Staff read and the front-desk day board may expose only current hold truth plus the latest relevant selection annotation; they must not compute a stored position.

A held entry is `waiting` but `callable=false` with:

```text
recall_hold_kind
recall_hold_release_at?
recall_hold_reason?
```

Customer-facing `entries_ahead` remains based on authoritative FIFO membership, not on speculative future hold expiry. F7e v1 must not promise a reduced numeric position merely because someone ahead is held. If live-capacity projection cannot truthfully determine imminent order because holds exist, it degrades to partial/indeterminate rather than guessing.

## 6. Capabilities and authority

Operator-only capabilities:

```text
queue.operator_select
queue.recall_hold
queue.release_recall_hold
queue.skip
```

All are `source_kind=operator` mutations. Bot relay uses the existing acting-operator boundary and does not grant these capabilities directly to customer principals.

Idempotency is scoped to the effective operator principal; audit retains the authenticated relay identity where applicable.

## 7. Required PostgreSQL 18 proofs

1. Degenerate equivalence: with no active holds/facts, F7e `call_next` chooses the exact same FIFO row as the pre-F7e rule.
2. `until_time` hold blocks selection before `release_at` and stops blocking after DB clock passes it without a release worker.
3. `until_customer_initiates` remains blocking until explicit release.
4. `skip` never changes `admitted_at`, never stores position, bypasses exactly one head for one selection attempt, and the skipped head is eligible again afterward.
5. `operator_select` calls the requested waiting row while bypassed rows remain waiting and ordered unchanged.
6. Concurrent `call_next` vs `operator_select`: one coherent selection outcome under the ServiceQueue lock, no double-call.
7. Concurrent `call_next` vs `recall_hold`: whichever owns the ServiceQueue lock first defines the result; no lost hold and no call through an already-committed hold.
8. Concurrent `skip` vs `call_next`: no duplicate called QueueEntry and no permanent reorder.
9. Cross-tenant rows remain opaque under forced RLS/runtime roles.
10. Every out-of-order operator action has an audit record and append-oriented selection fact.

## 8. Explicit non-goals

- no clinical triage scoring;
- no tenant-configurable priority policy;
- no generic condition/event DSL;
- no arbitrary reorder endpoint;
- no mutable position counter;
- no automatic dispatch from a hold expiry;
- no customer/bot direct `operator_select` or `skip` authority;
- no `until_event` implementation until its authoritative event vocabulary is separately closed.
