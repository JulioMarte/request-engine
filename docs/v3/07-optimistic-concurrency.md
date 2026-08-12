# V3 optimistic concurrency contract

## Purpose

Revision-managed aggregates expose a monotonically increasing `revision` so callers can prevent lost updates. A mutation of an existing aggregate must not silently overwrite state derived from an older read.

## Public API rule

For every public mutation that targets an existing revision-managed aggregate, the caller must provide a positive `expected_revision` obtained from the latest representation it read.

Creation commands do not carry `expected_revision` because there is no pre-existing aggregate revision to compare.

Commands that select work rather than mutate a caller-selected aggregate, such as FIFO `queue.call_next`, are not forced into this protocol merely because the selected row has a revision. Their concurrency semantics are determined by authoritative locking and selection rules.

## Authoritative validation

The revision comparison belongs inside the same database transaction and after the aggregate row has been locked. A preflight read performed by the HTTP layer is not sufficient because another transaction could commit between the check and the mutation.

The sequence is:

1. acquire idempotency scope;
2. lock the targeted aggregate;
3. compare the locked row revision with `expected_revision`;
4. reject on mismatch without releasing dependent capacity or changing children;
5. validate state transition and remaining invariants;
6. perform the mutation;
7. advance revision exactly one step;
8. append audit/outbox state and commit.

This is consistent with the V3 command protocol and the database invariant that revision-managed updates advance exactly one revision step.

## HTTP conflict shape

A stale mutation returns HTTP `409` with the common machine-readable code `revision_conflict`.

The error details are:

- `aggregate_kind`: canonical aggregate type, for example `Request` or `Reservation`;
- `aggregate_id`: aggregate UUID as a string;
- `expected_revision`: revision supplied by the caller;
- `current_revision`: revision observed under the authoritative lock.

Clients should refresh the aggregate, decide whether the intended mutation is still valid, and issue a new command with a new idempotency key or an idempotency key whose fingerprint matches the retried command according to the idempotency contract.

## Request baseline

`requests.record_result`, `requests.complete`, `requests.cancel`, and `requests.fail` mutate an existing Request and therefore require `expected_revision` at the HTTP boundary.

The PostgreSQL Request command path already locks the Request with `FOR UPDATE` and evaluates the expected revision against that locked row before applying the transition. The public contract no longer permits omitting the token and thereby disabling optimistic concurrency.

## Follow-on convergence

Appointments and caller-selected QueueEntry mutations must converge on the same external error shape, but their comparison must be introduced inside their existing authoritative lock paths. The V3 contract explicitly rejects implementing those checks as HTTP-layer preflight reads.
