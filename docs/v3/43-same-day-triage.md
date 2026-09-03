# F7e Same-Day Triage — Queue Selection Contract

Status: **S5a selection truth implemented on the front-door completion branch; S5 remains incomplete until S5b projection truth lands.**

This document narrows `docs/v3/36-front-desk-operations-contract.md` §7 and the implementation handoff in `docs/handoff/03-same-day-triage.md` into the executable Queue contract.

## 1. Scope

S5 adds three operator-only commands to Queue:

- `queue.operator_select`: call one specific waiting entry now for a closed reason;
- `queue.recall_hold`: make one waiting entry temporarily ineligible behind a closed condition;
- `queue.skip`: defer the current eligible FIFO head for one subsequent automatic selection.

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

`until_event` and `until_customer_initiates` deliberately have no public release command. Their authoritative condition producers belong to later inbound composition (S4). Until that wiring exists, those holds remain active unless an operator explicitly uses `operator_select`, which records `release_kind=operator_select`. This is an implementation limitation, not an implied event engine.

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

All three capabilities are operator exposure and require idempotency plus `expected_revision`. Facts are tenant-scoped, FORCE-RLS protected, and append-preserving at PostgreSQL level.

## 7. Evidence required for S5a

S5a is acceptable only when PostgreSQL 18 evidence proves:

- no-fact selection preserves FIFO;
- skip defers exactly one automatic selection without changing `admitted_at`;
- a hold excludes its entry from automatic selection;
- elapsed `until_time` is released before selection;
- operator select emits exactly one call event and is replay-idempotent;
- concurrent `call_next` versus hold, skip, and operator-select produces only valid serializable outcomes on the real ServiceQueue lock path;
- public HTTP metadata and tenant-isolation classification cover every new route.

## 8. What S5a does not complete

S5a only establishes **selection truth**. S5 is not complete until S5b updates the staff queue read, Day Board and F4/live-capacity projection so active holds and skips are visible and held entries are not projected as imminent. Until S5b is green, the product has correct mutation/selection semantics but an incomplete receptionist read surface.
