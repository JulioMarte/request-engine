# V3 worker runtime hardening

Status: normative for Phase 4 worker execution.

## Scope

Phase 4 makes existing durable work primitives operational. It does not add a universal workflow engine.

The runtime operates three technical work families:

```text
ScheduledAction
OutboxMessage
ProviderEvent
```

Business state remains owned by the module that created or consumes the work.

## Claim and fencing protocol

All cross-tenant discovery uses narrow `SECURITY DEFINER` functions.

The worker claim transaction performs only:

```text
find due/reclaimable work
FOR UPDATE SKIP LOCKED
assign a fresh claim_token
set leased + lease_until
increment lifetime attempt_count
COMMIT
```

Business work and provider/network I/O occur after that commit.

Completion, retry, dead-letter and lease renewal require the current `claim_token`.
A stale worker cannot finalize a row after another worker reclaimed it.

Lease renewal is valid only while the current lease is still unexpired. A late heartbeat cannot resurrect ownership after the fencing boundary passed.

## Bounded concurrency and backpressure

A runtime never claims more work than it can execute concurrently.

`claim_batch_size` is capped by `max_concurrency`. This avoids creating leased backlog inside one process while other workers could execute it.

Every claimed item also has a finite `processing_timeout`. A live task cannot renew one lease indefinitely merely because its handler or an external dependency stopped making progress. Timeout cancellation is classified as retryable `processing_timeout` work.

Processors must be cancellation-safe. Provider and network client timeouts must be shorter than the worker processing timeout so cancellation can complete at the runtime boundary.

The baseline runtime uses bounded exponential retry backoff with deterministic jitter derived from work identity and attempt count. The same work attempt receives the same delay, while unrelated work is distributed across the retry window to avoid synchronized retry storms.

Retry instants are materialized by PostgreSQL from `clock_timestamp()`, not from a worker host clock.

## Tenant fairness

Cross-tenant claim functions rank due work by tenant before applying the global batch limit:

```text
tenant_rank 1 across tenants
then tenant_rank 2
then tenant_rank 3
...
```

Within each tenant rank, older due work remains first.

This is bounded-batch fairness, not a weighted scheduling or SLA system.

The ranking query must be benchmarked against production-scale due backlogs before the V3 release freeze. Correctness does not imply acceptable query cost at high cardinality.

## Crash recovery

A worker crash before finalization leaves a leased row. After `lease_until`, another worker can reclaim it with a new claim token.

Re-execution is expected. Therefore semantic handlers must be idempotent at their business boundary.

Examples:

- SlotOffer expiry uses ScheduledAction identity as command idempotency.
- Reservation lifecycle uses OutboxMessage identity as source-event identity.
- communication provider sends use deterministic provider idempotency keys and reconciliation after ambiguity.

Exactly-once execution outside PostgreSQL is not promised.

## Outbox pipeline

One OutboxMessage represents one durable fact and one configured delivery pipeline.

The baseline pipeline order is:

```text
optional idempotent internal consequence
then configured external publisher
then fenced Outbox completion
```

If the process crashes after the internal consequence but before publish, the internal handler runs again. It must use the OutboxMessage id as its idempotency/source-event identity.

An OutboxMessage is not marked delivered merely because an internal handler ran. The configured publisher must also succeed.

The runtime does not silently discard events. A deployment must provide an explicit publisher implementation, even when that publisher targets an in-process or self-hosted transport.

## ProviderEvent

Provider callbacks are persisted before business interpretation.

The dedupe identity is:

```text
organization + provider_key + connection_key + provider_event_id
```

The canonical payload hash is retained. Reusing the same provider event identity with a different payload is a conflict.

ProviderEvent terminal states distinguish:

```text
processed  = handler completed
rejected   = explicit semantic/provider payload rejection
dead       = worker/infrastructure retries exhausted or permanent handler failure
```

Provider payload is never business authority by itself.

## Manual replay

Dead ScheduledActions and OutboxMessages, and dead/rejected ProviderEvents, can be replayed only through `request_admin` functions.

Replay requires organization, operator Principal, non-empty reason, and an explicit additional attempt budget.

Replay never resets `attempt_count`. It increases `max_attempts`, increments `replay_count`, stores `last_replayed_at`, and appends an audit record.

The ordinary `request_engine_worker` role cannot invoke replay functions.

The current Phase 4 replay contract treats `actor_principal_id` as an authenticated operator assertion supplied by the trusted admin boundary. The database validates tenant identity and referential integrity, but database credentials alone do not prove which human operator supplied that assertion. The authenticated actor-binding contract must be completed with the Phase 5 API/authentication boundary before the V3 release freeze.

## Operational visibility

`request_admin.worker_dead_letters_v1` exposes terminal work with organization, work identity, attempt budget, replay count, last error and update time.

This is an operator projection, not business state.

## ScheduledAction routing

The runtime routes only explicit `(owner_module, action_type, action_version)` registrations.

The Phase 4 registry covers:

```text
booking / evaluate_no_show
queue / waitlist.expire_slot_offer
communications / reminder occurrence
communications / dispatch_task
communications / reconcile_delivery
```

Unknown action types are permanent configuration errors and become dead letters instead of retrying forever.

## Database roles

`request_engine_worker` remains `NOBYPASSRLS` and receives cross-tenant visibility only through claim/finalization functions.

After claim, business handlers open ordinary tenant-scoped transactions and set tenant context for RLS.

`request_engine_admin` owns explicit replay/health operations. Production workers do not connect as schema owner or superuser.
