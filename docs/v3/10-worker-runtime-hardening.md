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

Authoritative business writes made after provider/network I/O must not rely on lease renewal alone. The tenant-scoped transaction that persists the business result must also lock and validate the same current `claim_token` before changing authoritative state. This closes the renewal-to-write race in which another worker could reclaim the action after renewal but before the domain write commits.

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

Replay requires organization-scoped trusted actor context, a non-empty reason, and an explicit additional attempt budget. The current V3 admin functions do **not** accept an arbitrary actor Principal as a replay argument. They obtain the authenticated operator from the trusted execution context established for the transaction, including `request_engine.organization_id`, `request_engine.authenticated_principal_id`, principal kind, authentication method, and correlation identity.

The database validates that the trusted actor context is present and tenant-consistent before the admin mutation and records that actor plus correlation provenance in the audit row. Callers must establish this context transaction-locally; pooled connections must not retain actor or tenant context after the transaction ends.

Replay never resets `attempt_count`. It increases `max_attempts`, increments `replay_count`, stores `last_replayed_at`, and appends an audit record.

The ordinary `request_engine_worker` role cannot invoke replay functions.

A deployment authentication adapter still owns credential validation before establishing trusted actor context. Database credentials alone do not prove issuer, audience, signature, expiry, rotation, or the human identity behind a credential; those properties remain part of the deployment/API authentication proof.

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

Unknown action types are permanent configuration errors and become dead letters instead of retrying forever. When poison communications work has a tenant-bound `CommunicationTask` subject, the handler first fences the current lease and terminalizes that task as `failed` only when no other executable dispatch intent remains.

For this decision, a sibling dispatch is executable only when its owner/type/version/subject match the communications dispatch contract, its payload contains the same semantically valid UUID identity, its state is `pending` or `leased`, and `attempt_count < max_attempts`. Malformed, stale-version, exhausted, dead, completed, or unrelated ScheduledActions cannot keep a poisoned task artificially non-terminal.

The same executable-work rule applies when Communications decides whether a future retry or reconciliation already exists. A malformed or exhausted action must not suppress creation or execution of valid recovery work.

## Database roles

`request_engine_worker` remains `NOBYPASSRLS`, has no direct authoritative-table privileges, and receives cross-tenant visibility only through claim/finalization functions.

After claim, business handlers use a separate `request_engine_app` credential to open ordinary tenant-scoped transactions and set tenant context for RLS. Authoritative handler writes first lock and validate the current action claim through the narrow fencing function. A worker-control credential must never be reused as the domain session merely because it can set the tenant GUC.

Production assembly must therefore receive independent worker-control and tenant-domain database factories or pools. A worker process constructor that accepts one database `SessionFactory` and reuses it both for `PostgresScheduledActionWorker` and authoritative module handlers violates this boundary: the worker credential is intentionally unable to perform those domain writes, while the app credential must not receive cross-tenant worker authority.

`request_engine_admin` owns explicit replay/health operations. Production workers do not connect as schema owner or superuser.