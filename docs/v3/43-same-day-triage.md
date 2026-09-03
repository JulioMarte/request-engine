# F7e Same-Day Triage — Queue Selection Contract

Status: **S5 selection truth and S5b recall-state read surfaces implemented; exact-head PostgreSQL acceptance remains the merge gate for this branch.**

This document narrows `docs/v3/36-front-desk-operations-contract.md` §7 and the implementation handoff in `docs/handoff/03-same-day-triage.md` into the executable Queue contract.

## 1. Scope

S5 adds four operator-only commands to Queue:

- `queue.operator_select`: call one specific waiting entry now for a closed reason;
- `queue.recall_hold`: make one waiting entry temporarily ineligible behind a closed condition;
- `queue.skip`: defer the current eligible FIFO head for one subsequent automatic selection;
- `queue.release_recall_hold`: release one active hold and return the entry to its original derived FIFO position without calling it.

This slice does not add scoring, mutable positions, tenant policy DSLs, generic priority values, or a new terminal QueueEntry state.

## 2. Preserved FIFO truth

The default selector remains `(admitted_at, id)` ascending. `admitted_at` is never rewritten to express triage. With no active S5 facts, `queue.call_next` selects exactly the same entry as before S5.

A skip is an ordered fact, not a reorder. While active, the skipped entry is excluded from automatic selection. When another entry is selected, active skips in that queue are consumed atomically and those entries become eligible again at their original derived position. If no other entry can be selected, no skip is consumed.

## 3. Recall holds

The closed condition kinds are:

- `until_time`: requires a timezone-aware future instant. Queue materializes expiry under the queue lock before automatic selection;
- `until_event`: currently accepts only the closed event key `external_step_completed`;
- `until_customer_initiates`: carries no caller-defined condition payload.

Only one active hold may exist per queue entry. Hold identity, condition, creator, reason, and creation time are immutable. Release is a one-way transition.

`queue.release_recall_hold` is the operator release path for all hold kinds. It requires the active `hold_id` plus the entry's current revision, releases the hold with `release_kind=operator_release`, and bumps the entry revision. The entry stays `waiting` and re-enters automatic selection at its original `(admitted_at, id)` position; `admitted_at` is never rewritten and no call event is emitted. Releasing a hold whose entry is no longer `waiting` fails closed with `queue_entry_not_waiting`; releasing when no hold is active fails with `queue_hold_not_active` (an expired `until_time` hold is expiry-stamped by the next successful queue command, and a failed command rolls back atomically without stamping); releasing a stale `hold_id` fails with `recall_hold_conflict`.

S4 condition producers for `until_event`/`until_customer_initiates` remain future work: today the condition-aware exits are the operator paths (`operator_select` to call the entry, `release_recall_hold` to return it to the plain FIFO). This is an implementation limitation, not an implied event engine.

## 4. Skip semantics

`queue.skip` is valid only for the current eligible FIFO head and only while the entry is `waiting`. Reasons are closed:

- `temporarily_unavailable`;
- `no_response`;
- `operator_override`.

A skip is non-terminal. It neither changes `status` nor rewrites arrival/admission timestamps. Creating and consuming the skip advance QueueEntry revision so stale operator state cannot silently cross a change in callability.

## 5. Operator selection

`queue.operator_select` is valid only for a waiting entry and is revision fenced. Reasons are closed:

- `urgent`;
- `scheduled_commitment`;
- `operator_override`.

The command may select around FIFO, an active hold, or the entry's own active skip. It records an immutable operator-selection fact, releases the selected entry's hold/skip if present, performs the same waiting-to-called transition as `call_next`, and emits the same `queue.entry_called.v1` durable event. It does not reorder the remaining queue.

## 6. Serialization and authority

Every S5 mutation follows the existing Queue lock order:

1. resolve the owning ServiceQueue;
2. lock the ServiceQueue row;
3. lock or select QueueEntry rows;
4. write S5 facts and QueueEntry transition;
5. write audit/outbox/idempotency state;
6. commit.

This ordering is shared with `queue.call_next`. It is required to avoid double selection, lost holds, and inverted-lock deadlocks.

All four capabilities are operator exposure and require idempotency plus `expected_revision`. Facts are tenant-scoped, FORCE-RLS protected, and append-preserving at PostgreSQL level.

## 7. Evidence required for S5

S5 is acceptable only when PostgreSQL 18 evidence proves:

- no-fact selection preserves FIFO;
- skip defers exactly one automatic selection without changing `admitted_at`;
- a hold excludes its entry from automatic selection;
- elapsed `until_time` is released before selection;
- operator select emits exactly one call event and is replay-idempotent;
- concurrent `call_next` versus hold, skip, and operator-select produces only valid serializable outcomes on the real ServiceQueue lock path;
- concurrent release versus release, release versus `call_next`, and release versus operator-select produce only valid serializable outcomes; releasing an entry that left `waiting` fails closed;
- released entries rejoin automatic selection at their original `(admitted_at, id)` position without emitting a call event;
- staff live Queue reads expose whether a waiting entry is currently recall-eligible and the active hold/skip fact that prevents normal recall;
- Booking Day Board projects a unique active Queue recall gate without acquiring Queue mutation authority, and exposes cardinality instead of arbitrarily choosing when multiple active QueueEntries correlate to one Reservation;
- customer `entries_ahead` counts only waiting entries that are eligible for the next normal recall snapshot;
- public HTTP metadata and tenant-isolation classification cover every new route.

## 8. Read-surface semantics

S5b does not create a second mutable readiness model. The authoritative mutation facts remain Queue recall holds and skips.

`queue.staff_read` projects those facts as:

```text
recall_eligible
recall_hold_id?
recall_hold_kind?
recall_hold_until_at?
recall_hold_event_key?
recall_hold_reason?
active_skip_reason?
```

`recall_eligible=true` means exactly that the QueueEntry is `waiting` and has no effective active recall hold or unconsumed skip at the read snapshot. `called`, `serving`, and terminal entries are not recall-eligible even when no gate exists.

The Booking-owned Day Board remains a read-only composition. It projects Queue correlation and recall-gate facts through `request_read.reservation_day_v1`; Booking does not write, release, or reinterpret Queue facts. `active_queue_entry_count=0` means no active QueueEntry is correlated. With exactly one active QueueEntry, the Day Board may expose its identity, status and recall gate. With more than one active QueueEntry, the count remains visible but `queue_entry_id`, `queue_entry_status`, `recall_eligible` and gate details are null: the read surface must not silently choose a "latest" QueueEntry and fabricate a single-stage truth. Multiple active QueueEntries are therefore explicit evidence requiring a future lineage/handoff contract, not an implicit workflow interpretation.

Customer `entries_ahead` is likewise a snapshot of immediate normal recall order. Held or skipped waiting entries are not counted as imminent while their gate is effective. This does not promise a stable future position: a one-shot skip may be consumed and a hold may be released after the read.

These fields must not be reinterpreted as clinical triage severity, insurance authorization, a generic workflow stage, or an external authority's decision. External prerequisites may cause Queue to be held, but their domain truth remains outside Queue.
