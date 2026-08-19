# Scheduling platform capability

Provides generic durable scheduled-work mechanics shared by business modules.

Owns technical concerns such as:

```text
clock abstraction
ScheduledAction persistence contract
claim batching
lease/fencing
retry/dead-letter mechanics
manual replay plumbing
scheduling lag telemetry
```

It does **not** decide why a reminder, SlotOffer expiry, request deadline or other future action exists. Business modules create/cancel/reschedule actions through narrow scheduling contracts and retain ownership of policy and payload semantics.

## Phase 4 lease contract

PostgreSQL is authoritative for worker time and ownership.

- A `claim_token` is authoritative only while its database `lease_until` is live.
- Completion, retry and dead-letter operations reject an expired lease even if no replacement worker has reclaimed the row yet.
- Lease renewal is fenced by both work identity and the current claim token.
- Retry paths validate a live lease with `SELECT ... FOR UPDATE`. That row lock is their linearization point. Once acquired, a reclaimer cannot become owner until the retry transition commits.
- Retry delays use the PostgreSQL clock. Worker host clocks do not determine durable retry timestamps.
- `attempt_count` is lifetime history. Administrative replay does not reset it; replay adds an explicit bounded attempt allowance instead.
- Manual replay is a privileged administrative operation and emits an audit record.

Claiming is fair across tenants. Claim queries rank eligible work inside each organization before interleaving tenant ranks, so one hot tenant cannot monopolize every batch.

Workers must bound claimed work to available concurrency. A worker does not pre-lease a large backlog that it cannot execute before lease expiry.

## External I/O and stale-worker fencing

Provider/network I/O remains outside database transactions.

A worker that performs external I/O must prove that it still owns the durable work before persisting the external result. Communication delivery does this with a claim-token lease renewal immediately before result finalization.

If heartbeat renewal fails or the database cannot prove ownership, the runtime treats ownership as uncertain. It records the in-memory outcome as `stale` and does not complete, retry or dead-letter that lease.

A stale worker can therefore finish an idempotent external request, but it cannot authoritatively write the result after another worker owns the ScheduledAction. The replacement worker must reconcile durable provider state before deciding whether another external request is safe.

## Reliability semantics

Required properties are:

```text
bounded concurrency
fair cross-tenant claiming
database-clock lease authority
heartbeat renewal
stale-worker fencing
bounded retry with dead-letter state
history-preserving administrative replay
safe recovery after process death
observable lag and terminal failures
```

The platform does not promise exactly-once external side effects. It provides at-least-once durable work processing with deterministic idempotency identities, fencing and reconciliation after uncertainty.
