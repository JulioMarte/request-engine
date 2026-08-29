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

F5 recovery reassessment applies the same rule to computation performed before the final write transaction. A worker may calculate a candidate F4 recovery assessment outside the transaction, but the tenant-scoped transaction that mutates `OperationalRecoveryIncident` must first lock the exact ScheduledAction claim and the current `recovery_source_revision`. It may persist the assessment only when both the queued target revision and the assessment checkpoint still equal that locked current revision. A superseded revision is a successful stale no-op; it cannot overwrite fresher recovery truth. Before recomputing F4, the handler also short-circuits a superseded revision with one cheap advisory revision read so a change storm costs O(1) per stale no-op, while the commit fence above remains the only authority for staleness.

## Bounded concurrency and backpressure

A runtime never claims more work than it can execute concurrently.

`claim_batch_size` is capped by `max_concurrency`. This avoids creating leased backlog inside one process while other workers could execute it. Both `claim_batch_size` and `max_concurrency` are bounded to at most 500. Continuous-loop `idle_sleep` must be strictly positive and at most 60 seconds, preventing accidental unbounded fan-out and zero-delay empty-queue spinning.

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
- ReservationAccess provider artifacts use a stable `(reservation, access_key, reservation revision)` materialization key. A later claimant reuses recorded provider evidence or performs a non-creating provider lookup before deciding whether provisioning or revocation is still required.
- F5 recovery source changes append immutable reassessment work keyed by `(ServiceQueue, recovery_source_revision)`. Replaying an old row cannot regress the incident because the authoritative write revalidates the current revision under lock.

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

A technical Outbox `claim_token` is capability material and is not part of the integration event. `OutboxPipelineProcessor` therefore supports an explicit fenced-internal-handler surface that receives `(OutboxEvent, claim_token)` while the publisher receives only the capability-token-free `OutboxEvent`. Event types registered on the fenced surface cannot also be registered on the generic internal-handler surface.

Reservation lifecycle events are reserved for composition through `reservation_lifecycle_factory`. The production composition root supplies only `domain_session_factory` to that factory. This prevents a deployment from accidentally constructing ReservationAccess or another reservation-lifecycle authoritative adapter with `request_engine_worker` credentials.

For ReservationAccess, provider I/O remains outside authoritative transactions. Provider evidence may be recorded on a non-authoritative `pending` row after lease loss so crash recovery can converge without blind duplicate provisioning. Publishing `ready` or `revoked` must instead validate and lock the exact current Outbox claim inside the same `request_engine_app` transaction as the authoritative state transition.

Reservation reschedule recovery has an additional historical-fact requirement. `reservation.rescheduled.v1` carries the released slot coordinates (`old_location_id`, `old_start_at`, `old_end_at`) in the durable Outbox fact. A delayed consumer must recover capacity from those event-time coordinates rather than infer the old slot from mutable current Reservation/CapacityClaim state. Current schedule, communications and access reconciliation still converges against the latest Reservation snapshot; only the released-slot recovery consequence is tied to the historical coordinates of the event that caused it.

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

Provider payload is never business authority by itself. ProviderEvent handlers raise `RejectedWorkError` for semantic rejection; only the ProviderEvent runtime receives the fenced reject capability. Rejection requested on another runtime is a configuration failure rather than a silent conversion to dead-letter state.

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

The registry covers:

```text
booking / evaluate_no_show
queue / waitlist.expire_slot_offer
communications / reminder occurrence
communications / dispatch_task
communications / reconcile_delivery
operational_recovery / reassess_recovery_scope
```

`operational_recovery / reassess_recovery_scope` uses `ServiceQueue` as its subject and carries the target `recovery_source_revision`. The business mutation that advances that revision must durably insert the corresponding ScheduledAction in the same database transaction, so commit cannot publish new recovery truth while losing its wake-up request. The per-revision dedupe identity is immutable and deterministic.

This per-revision durable enqueue is the event-driven delivery primitive for F5; by itself it is **not** the F5 change-storm coalescing guarantee, which remains a separate recovery requirement with its own acceptance evidence. The bounded fallback sweep now exists as a periodic `recovery_sweep` worker stream (same supervisor and shared graceful shutdown): cross-tenant discovery uses the `SECURITY DEFINER` `request_cmd.find_recovery_sweep_scopes(p_limit)` function, which reads only the RLS-free `scheduled_actions` reassessment history, and each discovered scope is repaired in a tenant-scoped `request_engine_app` transaction that reads the current `recovery_source_revisions` revision under tenant policy and inserts the identical per-revision dedupe identity when no live `pending`/`leased`/`completed` action exists. The sweep never resurrects `dead` or `cancelled` actions — that remains explicit operator replay through `request_admin` — and it never evaluates F4 or commits recovery truth; the existing fenced handler with its freshness pre-check performs the evaluation. Defaults are a 300s tick interval (bounds 60s–1h) and 200 scopes per tick (cap 500) with a rotating cursor; a scope whose entire reassessment action history was manually deleted is an honestly declared residual gap because discovery enumerates from `scheduled_actions` only.

Unknown action types are permanent configuration errors and become dead letters instead of retrying forever. When poison communications work has a tenant-bound `CommunicationTask` subject, the handler first fences the current lease and terminalizes that task as `failed` only when no other executable dispatch intent remains.

For this decision, a sibling dispatch is executable only when its owner/type/version/subject match the communications dispatch contract, its payload contains the same semantically valid UUID identity, its state is `pending` or `leased`, and `attempt_count < max_attempts`. Malformed, stale-version, exhausted, dead, completed, or unrelated ScheduledActions cannot keep a poisoned task artificially non-terminal.

The same executable-work rule applies when Communications decides whether a future retry or reconciliation already exists. A malformed or exhausted action must not suppress creation or execution of valid recovery work.

## Database roles

`request_engine_worker` remains `NOBYPASSRLS`, has no direct authoritative-table privileges, and receives cross-tenant visibility only through claim/finalization functions.

After claim, business handlers use a separate `request_engine_app` credential to open ordinary tenant-scoped transactions and set tenant context for RLS. Authoritative handler writes first lock and validate the current action claim through the narrow fencing function. A worker-control credential must never be reused as the domain session merely because it can set the tenant GUC.

The F5 reassessment handler follows this boundary explicitly: the ScheduledAction is claimed/finalized through `worker_session_factory`; F4 reads and the final incident mutation use `domain_session_factory`. The final domain transaction calls the narrow ScheduledAction claim fence and revalidates the locked recovery source revision before any incident insert/update. Production composition constructs the F5 handler automatically from domain-side F4 sources; a deployment cannot satisfy the handler by passing the worker-control factory as its domain authority.

The same rule applies to Outbox-derived authoritative writes. When an app transaction must validate a worker-control fact, it uses a narrow `SECURITY DEFINER` fence rather than granting the app broad Outbox access or granting the worker business-table DML. `request_cmd.lock_outbox_message_claim(...)` requires tenant-context equality plus the exact current, unexpired Outbox token and locks that row for the duration of the app transaction. `PUBLIC` cannot execute it and its `search_path` is pinned.

Production assembly receives independent `worker_session_factory` and `domain_session_factory` objects. `ScheduledAction`, `OutboxMessage`, and `ProviderEvent` control stores are constructed only with `worker_session_factory`. Booking and Queue scheduled handler factories receive only `domain_session_factory`, and Communications reminder/delivery authoritative adapters are also constructed with `domain_session_factory`. Reservation lifecycle composition also receives only `domain_session_factory`; reserved lifecycle event names cannot bypass that factory through generic Outbox handler registration. The F5 recovery reassessment adapter is likewise constructed only with `domain_session_factory`. The composition root rejects reuse of the same factory object for both roles.

The factory-identity check is a guardrail, not the entire security proof. PostgreSQL integration evidence must also demonstrate that the worker factory authenticates through the `request_engine_worker` role boundary and the domain factory through `request_engine_app`; distinct Python wrappers around one privileged credential do not satisfy this contract.

`request_engine_admin` owns explicit replay/health operations. Production workers do not connect as schema owner or superuser.

## Process assembly and deployment

`request_engine.bootstrap.worker.build_worker_process` is the production composition surface. It creates independent fenced runtimes for ScheduledAction, OutboxMessage, and ProviderEvent under a single `WorkerProcess`/`WorkerSupervisor` failure boundary. An unexpected stream failure cancels siblings; graceful shutdown shares one stop event across all streams.

The ScheduledAction router is assembled in a dedicated bootstrap component so adding a module handler does not grow the process supervisor itself. F5 recovery reassessment is part of the standard registry rather than an optional deployment hook; once F5 source freshness enqueues work, a normally assembled worker knows how to route it.

`WorkerProcess.run_once()` is a bounded operational probe and returns per-stream `WorkerItemOutcome` evidence. `WorkerProcess.run(stop_event)` is the long-lived process boundary.

The installed `request-engine-worker` command loads one trusted zero-argument deployment factory from `--factory module:attribute` or `REQUEST_ENGINE_WORKER_FACTORY`. Provider selection, publisher configuration, and credentials remain explicit deployment concerns; the launcher does not infer transports or install silent no-op adapters. `SIGINT` and `SIGTERM` set the shared graceful-shutdown event.
