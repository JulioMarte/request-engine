# Worker platform capability

Phase 4 provides the process-level runtime for durable Request Engine work.

The platform runs three independent durable streams:

```text
ScheduledAction
OutboxMessage
ProviderEvent
```

Each stream owns its persistence and claim protocol. The generic worker runtime owns bounded concurrency, heartbeat behavior, retry classification and stale-worker handling.

## Generic runtime

`FencedWorkerRuntime` never claims more work than it can execute concurrently. It starts a heartbeat for each claimed lease and finalizes work only while ownership remains provable.

Processing outcomes are:

```text
completed
retry
dead
stale
```

`stale` is not a business failure. It means this process can no longer prove that it owns the work. The runtime leaves durable state for the current or next authoritative worker.

Unexpected processor exceptions are retryable by default. Explicit `PermanentWorkError` moves the current lease to dead-letter state. Explicit `LeaseLostWorkError` prevents any lease mutation.

Every processor also has a finite `processing_timeout`. Timeout cancellation becomes a retryable `processing_timeout` failure instead of allowing a live but hung task to renew one lease forever. Processors must be cancellation-safe. Provider and network client timeouts must be shorter than the worker processing timeout.

Retries use bounded exponential backoff plus deterministic jitter derived from work identity and attempt count. The same work attempt receives the same delay, while unrelated work is spread across the retry window. This avoids synchronized retry storms after a shared dependency outage.

## Process supervision

`WorkerSupervisor` runs independent worker loops inside one `asyncio.TaskGroup`.

All loops share one shutdown event. Normal shutdown lets each loop stop cooperatively. If any loop raises unexpectedly, structured concurrency cancels sibling loops and propagates the failure. The process must not continue in a partially alive state where, for example, ScheduledAction work is running but Outbox processing has silently died.

## Outbox

Outbox processing runs idempotent local consequences before publishing the durable event. The OutboxMessage is completed only after both stages succeed.

A crash between the local consequence and external publication replays the local consequence. Local handlers therefore use the OutboxMessage ID as a stable source/idempotency identity.

External publication is at-least-once. Consumers must deduplicate by stable event identity when exactly-once business interpretation is required.

## Provider events

Inbound provider events are persisted before business interpretation.

Identity is scoped by organization, provider, connection and provider event ID. A replay with the same canonical payload is accepted as a replay. Reusing that identity with a different payload is a conflict.

`rejected` and `dead` are intentionally distinct:

- `rejected` means the event was semantically invalid or unsupported.
- `dead` means processing exhausted operational recovery or was explicitly dead-lettered.

## Composition boundary

Concrete module worker adapters are composed in `request_engine.bootstrap.worker`.

Worker entrypoints remain generic transport/runtime surfaces and do not import business-module adapters directly. This preserves the same module boundary rule used by HTTP entrypoints and prevents worker composition from becoming a back door around the modular-monolith dependency policy.

## Operational guarantees

Phase 4 guarantees:

```text
fair tenant claiming
bounded in-process concurrency
bounded processor execution
lease heartbeat and renewal
PostgreSQL-clock ownership fencing
expired-token rejection
post-provider-I/O finalization fencing
bounded retries with deterministic jitter
terminal dead-letter state
privileged audited replay
structured process supervision
safe reclaim after worker death
```

These guarantees reduce duplicate effects but do not redefine external systems as transactional participants. Provider calls and event publication remain outside Request Engine database transactions and rely on stable idempotency identities plus reconciliation after uncertainty.
