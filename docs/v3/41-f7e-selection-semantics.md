# F7e Same-Day Selection Semantics

## Status

Prepared on `tmp/f7e-same-day-selection-semantics` as a normative + implementation scratch tranche layered on the F7 front-desk branch. It is not integrated product truth until the serialized F7 lane is merged and the exact-head CI of the resulting F7e branch is green.

This decision record closes the operational semantics for same-day queue exceptions without replacing FIFO with a mutable priority list.

## 1. Problem

F3 deliberately made `QueueEntry` ordering deterministic:

```text
(admitted_at, id)
```

That is the correct default substrate, but front-desk operation has legitimate same-day exceptions that are not equivalent to permanently reordering a queue:

- a known booked customer is operationally due before a walk-in that arrived moments earlier;
- an operator must call one specific waiting person for an explicit operational reason;
- the current head stepped away and should remain in the queue without blocking everybody behind them;
- the current head did not respond and should be skipped for this selection attempt only;
- a temporarily unavailable customer may later become callable again without losing their original arrival order.

Encoding all of these as changes to `admitted_at`, mutable rank numbers, delete/reinsert, or free-text “priority” would destroy auditability and make concurrency semantics ambiguous.

F7e therefore keeps FIFO as durable history and introduces explicit **selection facts** and **recall holds** around it.

## 2. Governing invariant

The normal queue order remains immutable:

```text
FIFO identity = (admitted_at, id)
```

F7e may change **who is eligible for one selection** or **who the operator explicitly selects**, but it does not rewrite the historical FIFO key.

Every mutation that can interact with `call_next` serializes through the owning `ServiceQueue` row lock.

Consequently:

```text
Queue = durable waiting order
RecallHold = temporary callability gate
Skip = one-selection exception against current eligible FIFO head
OperatorSelect = explicit selection of one waiting, callable entry
```

None of these become a generic ranking engine.

## 3. Closed vocabularies

### OperatorSelectReason

```text
urgent_operational_need
booked_time_due
operator_override
```

These are operational facts/reasons, not clinical diagnoses or triage scores.

### SkipReason

```text
temporarily_unavailable
no_response
operator_override
```

### RecallHoldKind

```text
until_time
until_customer_initiates
```

### RecallHoldReason

```text
stepped_away
temporarily_unavailable
operator_override
```

`reason` is optional but, when present, must use this vocabulary. Free text is intentionally forbidden in both the application model and PostgreSQL so Queue cannot become a shadow clinical-notes surface.

### Recall hold release reason

Durable release history is also closed:

```text
replaced
operator_release
```

The application owns these transitions. Arbitrary SQL/adapters cannot write new historical explanations without changing the contract and migration backstop.

## 4. Recall hold model

A recall hold is a durable append-preserving fact with mutable **release metadata only**.

Identity fields are immutable:

```text
organization_id
id
service_queue_id
queue_entry_id
hold_kind
release_at
reason
created_by_principal_id
created_at
```

A hold is physically current while:

```text
released_at IS NULL
```

At most one physically current hold may exist for one `(organization_id, queue_entry_id)`.

### until_time

Requires a non-null `release_at` strictly later than the PostgreSQL database clock when created.

It blocks callability only while:

```text
released_at IS NULL
AND release_at > observed_at
```

When database time passes `release_at`, the hold becomes **derived inactive**. No worker is required and no fake release event is written.

The historical row can remain physically unreleased until an operator replaces or explicitly releases it. Replacement closes the prior row atomically before inserting the next one, so the one-current-hold unique constraint cannot strand the queue after derived expiry.

### until_customer_initiates

Requires `release_at IS NULL` and remains blocking until an explicit release command succeeds.

No inferred phone call, message, UI refresh, or passage of time clears it.

## 5. Revision and stale intent

Recall-hold creation/replacement and explicit release are operational changes to the `QueueEntry` and therefore advance its revision.

Derived time expiry does **not** change QueueEntry revision because no durable mutation occurred.

Commands requiring an observed entry use `expected_revision`:

```text
operator_select
recall_hold
release_recall_hold
```

`skip` is server-selected under the ServiceQueue lock and therefore has no client-provided QueueEntry revision.

### Exact hold release

`release_recall_hold` carries both:

```text
queue_entry_id
hold_id
expected_revision
```

After the ServiceQueue and waiting entry are locked:

1. stale QueueEntry revision fails;
2. no current hold is a durable no-op;
3. if a current hold exists but its ID differs from the supplied `hold_id`, the command fails with typed `RecallHoldConflict`;
4. only the exact current hold may transition to released.

This prevents a client that refreshed the QueueEntry revision but retained a stale hold identity from believing it released a newer operator intent.

The conflict transaction must leave the current hold, QueueEntry revision, idempotency row, audit and outbox unchanged.

## 6. Selection semantics

### call_next

Unchanged default behavior:

```text
first waiting + callable entry by (admitted_at, id)
```

Entries with an active recall hold are excluded from callability.

### operator_select

An operator may select one exact waiting QueueEntry for a closed operational reason.

The command:

1. acquires the active ServiceQueue lock;
2. locks the target waiting entry;
3. verifies expected revision;
4. refuses an active recall hold with typed `QueueEntryRecallHeld`;
5. transitions only that QueueEntry to `called`;
6. appends an immutable `operator_select` selection fact;
7. records audit/outbox/idempotency in the same transaction.

It does not rewrite any bypassed QueueEntry or FIFO key.

### skip

`skip` means:

> Ignore the current eligible FIFO head for this selection attempt only; if a second eligible entry exists, call that second entry.

Under one ServiceQueue lock it reads at most two eligible FIFO entries.

If no eligible entry exists, it is a durable no-op.

If one exists:

- that first ID is recorded as the skipped entry;
- it remains waiting and unchanged;
- if a second eligible entry exists, the second is called;
- the immutable selection fact records both the skipped target and, when present, the actual called entry.

A later `call_next` starts again from normal FIFO/callability. Skip does not create a persistent rank penalty.

## 7. Concurrency authority

All commands that choose or change callability of QueueEntries use the same ServiceQueue serialization lock as `call_next`.

Required race outcomes are therefore serializable, not “best effort.”

### call_next vs operator_select

Only serialized outcomes are valid. Two commands cannot independently call the same target.

### call_next vs recall hold creation

Valid outcomes:

```text
call_next wins first
→ target called
→ hold creation cannot create a hold on that non-waiting entry
```

or:

```text
hold wins first
→ target remains waiting + held
→ call_next excludes it
```

Never:

```text
called + active hold
```

### release vs call_next

Valid outcomes:

```text
release wins first
→ hold released
→ call_next may call that entry
```

or:

```text
call_next observes hold first
→ held entry excluded
→ selection proceeds coherently
→ release later operates only if entry remains valid for release semantics
```

Again, no final `called + active hold` state is permitted.

### concurrent hold creation

Both attempts serialize under the ServiceQueue lock and expected revision. One may succeed; the later stale intent cannot silently replace the newer hold.

## 8. Durable selection facts

`queue_selection_facts` is an append-only operational ledger.

```text
selection_kind = operator_select | skip
```

Facts are immutable at PostgreSQL level; runtime app receives `SELECT+INSERT`, not UPDATE/DELETE.

The database verifies:

- target QueueEntry belongs to referenced ServiceQueue;
- operator-select target is already `called` in the same transaction;
- skip target remains `waiting`;
- any called QueueEntry recorded by skip belongs to the same queue and is `called`;
- reason is valid for the selection kind.

The ledger records exceptions without mutating the historical queue order.

## 9. F4 projection boundary

A recall hold does not remove workload. It changes **when** that workload can be sequenced.

F7e distinguishes sequencing uncertainty from capacity uncertainty.

An active recall hold therefore yields:

```text
ProjectionState.PARTIAL
ProjectionReason.ACTIVE_RECALL_HOLD
```

not `INDETERMINATE`.

When workload durations and effective operating seconds remain known:

- `projected_remaining_workload_seconds` remains known;
- algebraic `live_headroom_seconds` may remain known;
- projected per-entry start/end times are withheld;
- customer ETA is withheld;
- `live_intake_headroom_seconds` is withheld because temporal admissibility cannot be asserted.

A time hold whose `release_at <= observed_at` is ignored by F4 even if its historical row has not yet been explicitly released.

A hold attached to an entry that is no longer `waiting` is also ignored defensively.

No customer sees another subject's hold reason or identity.

### Intake evaluation

A positive algebraic workload budget is not enough to claim another workload fits while sequencing is uncertain. Under an active recall hold:

```text
fits_within_effective_availability = null
estimated_start = null
estimated_end = null
state = partial
reason includes active_recall_hold
```

F4 remains advisory and makes no intake mutation.

## 10. F5 recovery boundary

A recall hold alone is **not** a material recovery incident.

F5 already treats `ProjectionState.INDETERMINATE` as severe material uncertainty. Therefore F7e must not encode ordinary recall sequencing as `INDETERMINATE` merely to suppress ETA.

With `PARTIAL + ACTIVE_RECALL_HOLD` and no numeric shortfall:

```text
material = false
resolve = true
escalation_level = 0
```

If the preserved workload still creates a real scheduled/live shortfall, normal F5 recovery classification continues to apply. F7e therefore suppresses false severity without hiding genuine capacity pressure.

## 11. Capabilities and HTTP authority

Operator-only capabilities:

```text
queue.operator_select          revision = required
queue.recall_hold              revision = required
queue.release_recall_hold      revision = required
queue.skip                     revision = server_selected
```

All are idempotent mutations executed as the authenticated operator principal. F7e grants no customer capability and performs no clinical-priority inference.

HTTP routers depend on application `Executor` Protocols only. `PostgresSameDaySelectionCommands` is instantiated only at the Queue HTTP composition surface and is not imported into route modules.

The four routes are registered through the existing `add_capability_route` and canonical capability registry; no parallel authorization mechanism is introduced.

The F7 HTTP security matrix exercises every F7 operation for unauthenticated and missing-capability rejection without durable mutation. A positive F7e PostgreSQL HTTP journey additionally proves that the public composition path reaches the Queue owner for:

```text
queue.join
→ queue.skip
→ queue.recall_hold
→ queue.release_recall_hold
→ queue.operator_select
```

## 12. Tenant isolation and privileges

Both F7e relations use tenant-bound RLS with `FORCE ROW LEVEL SECURITY`.

Evidence must prove both catalog policy shape and actual row opacity:

- application runtime under tenant A can see tenant-A hold/selection facts only;
- tenant-B rows remain invisible;
- a tenant-A runtime connection attempting a direct tenant-B insert fails with RLS;
- worker role receives no direct authoritative table privileges;
- the immutable selection ledger keeps its narrower `SELECT+INSERT` app privilege shape.

## 13. Required PostgreSQL / contract proofs

Prepared on the scratch branch; **none may be claimed passed until executed on the exact F7e head**.

1. No-hold `call_next` preserves `(admitted_at,id)` FIFO behavior.
2. `until_time` blocks before `release_at` and stops blocking after database time passes it without a release worker.
3. Derived expiry does not fabricate release history.
4. `until_customer_initiates` remains blocking until exact explicit release.
5. Hold create/replacement/release advance QueueEntry revision as specified; derived expiry does not.
6. Stale revision cannot replace or release newer intent.
7. Stale `hold_id` combined with current revision returns typed conflict, preserves the current hold and revision, and leaves no idempotency/audit/outbox partials.
8. PostgreSQL rejects free-text hold reasons and unregistered release reasons.
9. `skip` bypasses one eligible head once without changing admitted time/revision/order.
10. `operator_select` calls the requested waiting row without reordering bypassed rows.
11. `operator_select` refuses an active held target with no call/selection side effects.
12. `call_next` vs `operator_select` serializes without double-calling a target.
13. `call_next` vs recall-hold create serializes to coherent called/no-hold or waiting/held outcomes.
14. concurrent hold-create attempts with the same revision leave one winner/current hold.
15. `skip` vs `call_next` records the exact head/called pair observed under the ServiceQueue lock.
16. release vs `call_next` yields only serialized valid outcomes and never leaves a called entry held.
17. staff read exposes and clears current hold kind/time/reason.
18. F4 ignores unreleased historical hold rows once the QueueEntry leaves `waiting`.
19. recall sequencing yields partial F4 timeline, preserves known workload/headroom, withholds live-intake fit and customer ETA.
20. recall sequencing without shortfall does not create F5 recovery severity.
21. F7e tables enforce real runtime tenant opacity under forced RLS.
22. canonical HTTP surface and tenant-isolation matrices cover capability metadata, idempotency classification and foreign-tenant opacity.
23. the F7 HTTP security matrix covers 401/403 rejection without mutation for all F7 operations.
24. the positive F7e HTTP journey reaches PostgreSQL through the real app composition for skip/hold/release/operator-select.

The current-product PostgreSQL gate explicitly executes `tests/db/test_f7e_*.py`, while the existing `tests/e2e` block executes the HTTP security, isolation, surface-contract and positive-journey proofs. Merely adding feature-local tests is not sufficient evidence.

## 14. Explicit non-goals

- no clinical triage scoring or diagnosis semantics;
- no free-text clinical/reason-for-visit field in Queue recall holds;
- no tenant-configurable priority policy;
- no generic condition/event DSL;
- no arbitrary reorder endpoint;
- no mutable position counter;
- no automatic dispatch merely because a hold expires;
- no direct customer/bot `operator_select` or `skip` authority;
- no `until_event` until its event vocabulary/authority is separately closed;
- no Booking-owned duplicate of recall-hold truth;
- no claim that this scratch tranche is integrated or green before exact-head CI executes after the serialized F7g lane is merged.
