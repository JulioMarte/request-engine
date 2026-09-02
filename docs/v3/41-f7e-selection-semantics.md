# F7e Same-Day Selection Semantics — normative amendment draft

Status: **scratch-branch decision record** for F7e. The implementation and proofs described here are prepared on `tmp/f7e-same-day-selection-semantics` but are **not CI-validated, merged or normative product state yet**. This closes the semantic gate in `36-front-desk-operations-contract.md` §7 and must be folded into the canonical F7 contract only after the serialized integration lane is available.

## 1. Preserved invariants

F7e does not create a priority queue or mutable queue position.

- Default selection remains FIFO by `(admitted_at, id)`.
- Queue position remains derived.
- `ServiceQueue` is the selection serialization root and is locked before selected/target `QueueEntry` rows.
- `waiting`, `called`, `serving`, `completed`, `cancelled`, `no_show` remain QueueEntry lifecycle states. Hold/skip are selection facts, not lifecycle states.
- One active QueueEntry per `(ServiceQueue, subject Party)` remains unchanged.
- Terminal lifecycle state supersedes a recall gate. An unreleased historical hold on an entry that is no longer `waiting` is not an active gate.
- Terminal exits remain terminal; F7e cannot resurrect them.
- F7e records operational selection semantics only. It does not admit diagnosis, symptoms, clinical notes or clinical triage scores.

## 2. `queue.operator_select`

Calls one specific `waiting` QueueEntry now without rewriting FIFO order.

Closed reason set:

```text
urgent_operational_need
booked_time_due
operator_override
```

`urgent_operational_need` is an operational dispatch annotation only. It is not a clinical-priority score and must not carry clinical text.

The command requires `expected_revision`. A stale directed click must not act on a newer QueueEntry state.

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock target QueueEntry
validate target belongs to queue and is waiting
validate expected_revision
validate target has no active recall hold
transition target to called
append selection fact + audit + queue.entry_called.v1
commit
```

A held target fails with a typed `queue_entry_recall_held` conflict. A non-waiting or revision-stale target loses cleanly. No failed selection may leave a selection fact or `queue.entry_called.v1` event.

## 3. `queue.recall_hold`

Creates or replaces the current recall gate for one `waiting` QueueEntry. The QueueEntry remains `waiting`; `admitted_at` and FIFO truth do not change.

Closed hold kinds:

```text
until_time
until_customer_initiates
```

`until_event` remains reserved in the broader F7 vocabulary but is **not implementable in v1** until a closed authoritative event-source contract exists. F7e does not invent event matching or a condition DSL.

Closed operational reason set:

```text
stepped_away
temporarily_unavailable
operator_override
```

The reason is optional but, when present, is an enum — never free text. PostgreSQL independently enforces the same vocabulary so Queue cannot accidentally become a store for clinical/reason-for-visit prose.

### `until_time`

- requires an offset-aware `release_at` strictly after the database clock at command time;
- is active while `release_at > observed database time`;
- expires derivatively from PostgreSQL time; no ScheduledAction is required for correctness;
- expiry does not fabricate `released_at`; the append-preserved row simply ceases to be a gate.

### `until_customer_initiates`

- has no timestamp expiry;
- remains active until explicit release;
- F7e v1 exposes operator release only. No inbound customer/bot release is inferred here.

At most one unreleased hold row exists per QueueEntry. A replacement closes the previous row with closed release reason `replaced`, advances `QueueEntry.revision`, and appends a new hold row.

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock QueueEntry
validate waiting + expected_revision
validate hold shape / database-time rule
close current unreleased hold if present
increment QueueEntry revision
append new hold fact
append audit/outbox
commit
```

## 4. `queue.release_recall_hold`

Explicitly releases the **exact current hold the operator observed**.

Required intent fence:

```text
queue_entry_id
hold_id
expected_revision
```

Protocol:

```text
acquire idempotency
lock ServiceQueue
lock QueueEntry
validate waiting + expected_revision
lock the current active hold for the QueueEntry
if no active hold exists -> deterministic no-op
if current hold id != requested hold_id -> 409 recall_hold_conflict
otherwise release that hold
increment QueueEntry revision
append audit/outbox
commit
```

This distinction is intentional. If hold A was replaced by hold B, a refreshed QueueEntry revision combined with stale `hold_id=A` must **not** report success while B remains active and must never release B. The command fails closed with the active/requested identities so the client can refresh.

A successful release records closed release reason `operator_release`. PostgreSQL allows only:

```text
replaced
operator_release
```

Derived `until_time` expiry does not advance QueueEntry revision and does not write release metadata.

## 5. `queue.skip`

A skip is a **single-selection defer**, never a reorder.

- It applies to the current **eligible** FIFO head under the ServiceQueue lock.
- It records that head as intentionally bypassed for one selection attempt.
- In the same transaction it calls the next eligible waiting entry, if one exists.
- The skipped entry stays `waiting`; `admitted_at` and revision remain unchanged.
- The skip has no future gating effect after commit.
- If no second eligible row exists, the skip fact is still recorded and no row is called.

Protocol:

```text
acquire idempotency
lock ServiceQueue
select+lock up to two eligible FIFO entries
record first as skipped
if second exists: transition second to called and emit queue.entry_called.v1
append selection fact + audit/outbox for skip
commit
```

One skip command can bypass exactly one head for exactly one selection attempt.

## 6. Automatic `call_next` eligibility

Ordinary `call_next` and `queue.skip` share one Queue-owned eligible-FIFO selector:

```text
QueueEntry.status = waiting
AND no active recall hold at database selection time
ORDER BY admitted_at, id
```

The degenerate path with no active holds is semantically identical to the pre-F7e FIFO rule.

An `until_time` row with `release_at <= clock_timestamp()` is not active and does not require a release write before selection. Expired history is not rewritten merely to make the row callable.

All F7e selection/release commands and ordinary `call_next` serialize through the same ServiceQueue lock.

## 7. Durable relations and backstops

### `queue_recall_holds`

Queue-owned append-preserving hold history/current-gate relation.

Minimum facts:

```text
organization_id
id
service_queue_id
queue_entry_id
hold_kind
release_at?
reason?                    # closed operational enum
created_by_principal_id
created_at
released_at?
released_by_principal_id?
release_reason?            # replaced | operator_release
```

Backstops:

- tenant-composite FKs to ServiceQueue, QueueEntry and principals;
- insert target must belong to the queue and be `waiting`;
- at most one unreleased row per QueueEntry via partial unique index;
- hold-kind/release-at shape enforced in SQL;
- hold reason and release reason are closed SQL vocabularies;
- identity/meaning fields are immutable;
- only one release transition may populate release metadata;
- RLS and FORCE RLS are enabled.

The application role may `SELECT`, `INSERT`, and `UPDATE` this relation because release is a guarded transition. DELETE is not granted.

### `queue_selection_facts`

Queue-owned immutable ledger for `operator_select` and `skip`.

```text
organization_id
id
service_queue_id
queue_entry_id
selection_kind = operator_select | skip
reason
selected_by_principal_id
selected_at
called_queue_entry_id?     # skip only
```

Database backstops verify:

- operator-select reasons and skip reasons are closed vocabularies;
- an `operator_select` fact points to a QueueEntry actually in `called` state;
- a `skip` fact points to the skipped QueueEntry still in `waiting`;
- `called_queue_entry_id`, when present, belongs to the same queue and is actually called;
- UPDATE/DELETE are rejected.

The runtime privilege contract intentionally grants the application role only `SELECT+INSERT` on this immutable ledger. This narrower shape is registered in the repository privilege exception set.

## 8. Staff read

Queue remains the authority for live recall-hold truth. Existing `queue.staff_read` exposes current active hold information:

```text
recall_hold_kind?
recall_hold_release_at?
recall_hold_reason?
```

`recall_hold_reason` is the same closed operational vocabulary stored in Queue; no free-text clinical annotation is introduced.

The live read does not store queue position. `queue.staff_history_read` does not reconstruct a live hold into terminal history; these fields are null for history rows that do not have a current gate.

The Booking-owned F7g day board is not changed to join Queue internals. Any future one-screen composition across Reservation and Queue facts requires an explicit owner-backed composition contract; F7e does not duplicate hold truth in Booking.

## 9. F4 projection semantics

A recall hold changes **sequencing certainty**, not workload identity or planning authority.

Held work remains in the Queue projection snapshot and remains counted as remaining workload. It is not deleted from capacity merely because the subject is temporarily non-callable.

A projection snapshot carries `has_active_recall_hold` only when an unreleased/non-expired gate belongs to a QueueEntry that is still `waiting`.

### Capacity vs timeline

A recall hold by itself produces:

```text
state = partial
reason includes active_recall_hold
projected remaining workload = known when durations are known
live_headroom_seconds = algebraically available when durations are known
per-item estimated start/end = unavailable
projected end-of-day = unavailable
live_intake_headroom_seconds = unavailable
```

This is deliberately different from an open interruption/resource activity, which can make capacity itself `indeterminate`.

The distinction prevents two opposite errors:

1. pretending a held patient's workload disappeared;
2. treating an ordinary “stepped away” fact as a severe capacity outage.

### Customer projection

Customer `entries_ahead` remains the derived FIFO-membership count. It is not rewritten into a speculative callable rank.

While recall sequencing is partial:

```text
estimated_wait_seconds = null
estimated_start = null
```

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

## 12. Tenant isolation and privileges

Both F7e relations use tenant-bound RLS with `FORCE ROW LEVEL SECURITY`.

Evidence must prove both catalog policy shape and actual row opacity:

- application runtime under tenant A can see tenant-A hold/selection facts only;
- tenant-B rows remain invisible;
- a tenant-A runtime connection attempting a direct tenant-B insert fails with RLS;
- worker role receives no direct authoritative table privileges;
- the immutable selection ledger keeps its narrower `SELECT+INSERT` app privilege shape.

## 13. Required PostgreSQL / contract proofs

Prepared on the scratch branch; **none may be claimed passed until executed**.

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
22. canonical HTTP probes cover capability, idempotency and tenant-isolation behavior.

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
