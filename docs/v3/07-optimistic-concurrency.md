# V3 optimistic concurrency contract

## Purpose

Revision-managed aggregates expose a monotonically increasing `revision` so callers can prevent lost updates. A mutation of an existing aggregate must not silently overwrite state derived from an older read.

## Public API rule

For every public mutation that targets an existing caller-selected revision-managed aggregate, the caller must provide a positive `expected_revision` obtained from the latest representation it read.

Creation commands do not carry `expected_revision` because there is no pre-existing aggregate revision to compare.

Commands that select work rather than mutate a caller-selected aggregate, such as FIFO `queue.call_next`, are not forced into this protocol merely because the selected row has a revision. Their concurrency semantics are determined by authoritative locking and selection rules.

## Authoritative validation

The revision comparison belongs inside the same database transaction and after the aggregate row has been locked. A preflight read performed by the HTTP layer is not sufficient because another transaction could commit between the check and the mutation.

The sequence is:

1. acquire idempotency scope;
2. lock the targeted aggregate;
3. establish subject Party authority when the operation requires it;
4. compare the locked row revision with `expected_revision`;
5. reject on mismatch without releasing dependent capacity or changing children;
6. validate state transition and remaining invariants;
7. perform the mutation;
8. advance revision exactly one step;
9. append audit/outbox state and commit.

Authority precedes revision disclosure so an unauthorized actor cannot use `revision_conflict` as an oracle for another Party's aggregate.

This is consistent with the V3 command protocol and the database invariant that revision-managed updates advance exactly one revision step.

## Idempotency relation

`expected_revision` is part of the semantic command fingerprint for revision-managed mutations.

Therefore:

- the same idempotency key plus the same normalized command and revision may replay its completed result;
- the same idempotency key with a different expected revision is an idempotency conflict;
- a new idempotency key carrying a stale revision reaches the aggregate lock and returns `revision_conflict`.

## HTTP conflict shape

A stale mutation returns HTTP `409` with the common machine-readable code `revision_conflict`.

The error details are:

- `aggregate_kind`: canonical aggregate type, for example `Request`, `Reservation`, or `QueueEntry`;
- `aggregate_id`: aggregate UUID as a string;
- `expected_revision`: revision supplied by the caller;
- `current_revision`: revision observed under the authoritative lock.

Clients should refresh the aggregate, decide whether the intended mutation is still valid, and issue a new command with a new idempotency key or an idempotency key whose fingerprint matches the retried command according to the idempotency contract.

## Request baseline

`requests.record_result`, `requests.complete`, `requests.cancel`, and `requests.fail` mutate an existing Request and require `expected_revision` at the HTTP boundary.

The PostgreSQL Request command path locks the Request with `FOR UPDATE` and evaluates the expected revision against that locked row before applying the transition.

## Appointment baseline

`appointments.cancel` and `appointments.reschedule` require positive `expected_revision` values.

Both commands compare against the locked Reservation after subject authority is established and before capacity claims are released/replaced or new Resource work is performed. A stale appointment mutation must therefore have no dependent capacity side effects.

## QueueEntry identity and the ABA rule

`queue.leave` is a caller-selected QueueEntry mutation. The stable target is the exact pair:

```text
queue_entry_id + expected_revision
```

Targeting only `(queue_id, subject_party_id)` is insufficient. A Party may leave Entry A and later join again as Entry B; both entries may independently have revision 1. A stale command that only names the Party could therefore cancel a newer entry it never observed.

The public leave route targets the concrete QueueEntry ID. PostgreSQL locks that exact row, derives `subject_party_id` from the authoritative row for Party authorization, compares its revision, and only then performs the transition.

`queue.call_next` remains outside this caller-selected compare-and-set protocol because PostgreSQL itself deterministically selects the next FIFO entry under the queue serialization lock.

## CapacityHold follow-on

CapacityHold is revision-managed but remains an internal/incomplete surface in the current baseline. Hold confirmation will converge on this same protocol in the dedicated CapacityHold hardening tranche before any public Hold capability is exposed.
