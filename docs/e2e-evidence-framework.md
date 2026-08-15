# End-to-End Evidence Framework

## Purpose

Request Engine does not treat end-to-end tests as a collection of happy-path examples. The E2E suite is an executable evidence system whose purpose is to falsify the production architecture under the same authority, tenancy, transaction, idempotency, lease, retry, and crash boundaries that runtime code uses.

A feature is not considered covered because one API call returned `200`. It is covered only when the suite demonstrates the relevant positive and negative contracts and proves that rejected, duplicated, concurrent, or interrupted work cannot corrupt durable state.

The framework lives under `tests/e2e/` and is part of the existing PostgreSQL V3 CI gate. Do not create a second E2E workflow for ordinary PRs.

## Core principles

1. **Production-equivalent database identities.** HTTP/application tests execute as a LOGIN role inheriting from `request_engine_app`; worker tests execute as a LOGIN role inheriting from `request_engine_worker`. Bootstrap and fixture seeding may use the administrative test connection, but runtime behavior must not.
2. **PostgreSQL is not mocked.** RLS, constraints, row locks, `SKIP LOCKED`, `SECURITY DEFINER` functions, transaction rollback, idempotency, leases, and fencing must be exercised against PostgreSQL.
3. **Only external side effects are doubled.** A provider double may stand in for email/SMS/WhatsApp/payment/etc. The database, scheduler, outbox, and application services remain real.
4. **Negative evidence includes non-mutation.** A `401`, `403`, `404`, stale token, duplicate callback, invalid transition, or conflict is incomplete evidence unless durable state is also shown not to have changed unexpectedly.
5. **Replays are first-class behavior.** Same-key/same-fingerprint replay, same-key/different-fingerprint conflict, stale lease replay, callback replay, and crash recovery are normal distributed-systems cases, not edge cases.
6. **External ambiguity never becomes blind resend.** If the system cannot know whether an external provider accepted a side effect, the next action must reconcile using provider identity/idempotency before attempting another send.
7. **The test classification grows with production composition.** Tests must not pretend an HTTP or worker surface exists before production composes it. Once a surface is composed, the executable registry must be extended in the same change.

## Framework layout

- `http_surface.py` — executable registry for every public `/v1` operation. It records method, route template, required capability, mutation/idempotency classification, tenant-isolation policy, and a syntactically valid security probe.
- `test_public_surface_contract.py` — compares generated OpenAPI with the registry. A new or removed public operation breaks CI until its E2E classification is updated.
- `test_http_security_matrix.py` — automatically executes every registry entry unauthenticated and authenticated-without-capability. It requires `401`/`403` and an unchanged durable-state snapshot.
- `tenant_sandbox.py` — reusable two-tenant fixture substrate containing real principals, parties, catalog, availability, queue, and request definitions.
- `test_http_tenant_isolation_matrix.py` — targets resources that actually exist in another tenant. Collection operations must filter; direct-resource operations must not disclose the resource and are expected to return `404`. Durable state must remain unchanged.
- `evidence.py` — shared durable-state snapshots used to prove non-mutation.
- `operational_support.py` — reusable runtime-role and worker fixture primitives.
- `test_worker_scheduling_semantics.py` — scheduler ownership, lease, fencing, retry/dead-letter, and worker-role evidence.
- `test_outbox_semantics.py` — outbox claim/fencing/retry/dead-letter evidence.
- `test_delivery_persistence_semantics.py` — communication/provider/reminder persistence invariants and dedupe evidence.
- `test_communication_worker_resilience.py` — real communication worker execution, provider ambiguity, crash windows, poison work, and multi-worker contention.
- `test_multi_user_journeys.py` — multi-user business journeys such as booking contention, capacity recovery, FIFO queues, and request lifecycle.

## Public HTTP operation contract

Every public operation must have exactly one `PublicHttpOperation` entry in `tests/e2e/http_surface.py`.

The entry must answer these questions:

- What stable test name identifies the operation?
- What method and OpenAPI route template expose it?
- Which capability is mandatory?
- Does it mutate durable state?
- Is an idempotency key mandatory?
- Is cross-tenant behavior `FILTERED` or `NOT_FOUND`?
- What syntactically valid request can exercise authentication/authorization before business logic?

The OpenAPI guard intentionally fails when the public surface changes. Do not "fix" that failure by weakening the equality assertion. Add or remove the registry classification and the corresponding evidence.

### Required HTTP evidence

For a newly added HTTP operation, the same PR must normally contain:

1. **Authentication:** unauthenticated request returns `401`; durable snapshot unchanged.
2. **Capability authorization:** authenticated actor without the declared capability returns `403`; durable snapshot unchanged.
3. **Tenant isolation:** use an object that genuinely exists in tenant B while calling as tenant A. Collections must exclude B; direct references must not disclose B and should use the module's non-disclosure `404` contract.
4. **Success journey:** valid actor and valid tenant-scoped data produce the documented result.
5. **Idempotency for commands:** same key + same fingerprint replays the original result without another domain mutation; same key + different fingerprint conflicts. If a command genuinely cannot vary its fingerprint, document why.
6. **State-machine negatives:** stale revision, terminal state, invalid transition, or incompatible resource state where applicable.
7. **Concurrency:** if two callers can contend for the same logical resource, execute a real race and assert the allowed winner/loser set plus final DB invariants.
8. **Durability:** assert the durable rows/outbox messages that constitute the business result, not only the HTTP response.

## Worker and external-side-effect contract

Any worker capable of producing an external side effect must be tested as a state machine across crash boundaries.

Use this canonical timeline:

1. claim durable work;
2. prepare/lock/update local intent;
3. issue or reconcile external side effect;
4. finalize provider result in the database;
5. acknowledge/complete durable work.

At minimum consider crashes at these boundaries:

- **after claim, before prepare** — lease expiry must make work reclaimable; stale claim token must lose authority;
- **after prepare, before known provider result** — a persisted `attempting`/ambiguous attempt must be reconciled before resend;
- **after external I/O, before local finalization** — provider idempotency/reconciliation must prevent duplicate effects;
- **after local finalization, before action acknowledgement** — reclaimed work must detect the terminal/local result, complete the old action, and perform zero second external side effects;
- **after acknowledgement** — replay must be a no-op or deterministic replay.

For each crash-recovery scenario assert:

- the original lease token is fenced after reclaim;
- there is no duplicate delivery/business row;
- the provider idempotency identity is stable;
- terminal outbox events occur exactly once;
- no blind resend occurs when the prior external outcome is uncertain;
- final domain state and scheduled-action state agree.

## Multi-worker contention

Worker tests should use multiple `PostgresScheduledActionWorker`/outbox consumers sharing the real database. Test disjoint claiming, not just sequential processing.

A contention test should assert:

- the union of claimed IDs equals the due work set;
- no work ID is owned by two live claim tokens;
- all stale tokens fail after reclaim;
- each external idempotency key is used at most once for a definitive send path;
- terminal domain/outbox results are exact, not merely "at least one";
- future/not-due work is not stolen.

High-iteration load/fairness tests should eventually run as a manual or scheduled evidence tier rather than on every PR. Ordinary deterministic races belong in the existing V3 PR gate.

## Durable non-mutation evidence

`durable_snapshot()` intentionally covers the main durable mutation surfaces: reservations, capacity claims, queue entries, generic requests, outbox messages, scheduled actions, communication tasks/deliveries, and provider events.

When a new subsystem introduces another durable table that can be mutated by rejected HTTP/worker work, extend the snapshot in the same PR. A security test that omits the new durable surface is incomplete.

Do not use a snapshot as a replacement for targeted assertions. Successful scenarios still need exact rows, statuses, revisions, dedupe keys, and event counts.

## Idempotency evidence template

For every command surface:

1. execute request A with key K and fingerprint F1;
2. record response and exact relevant durable state;
3. execute A again with K/F1;
4. require deterministic replay and unchanged business state;
5. execute semantically different request B with K/F2;
6. require idempotency conflict;
7. where useful, execute K/F1 concurrently from two clients and prove one logical mutation.

Provider idempotency is separate from API command idempotency. Both may be required in the same workflow.

## Provider callback/webhook evidence

When inbound provider-event processing is composed, add these cases before declaring the integration complete:

- exact duplicate event ID and payload;
- same event ID with conflicting payload/hash;
- events arriving out of order;
- callback for unknown provider message identity;
- callback for a terminal delivery;
- callback after a worker reconciliation already finalized the same result;
- two callback workers claiming/processing simultaneously;
- crash after provider event persisted but before domain transition/outbox acknowledgement.

Provider-event identity must remain tenant-scoped and connection/provider-scoped according to the database contract.

## Time-bound behavior

For holds, offers, reminders, leases, and other time-bound workflows, test boundaries around `now`, not only normal timestamps:

- immediately before expiry;
- exactly at expiry according to database-clock semantics;
- immediately after expiry;
- retry scheduled in the future is not claimable early;
- DST gaps/folds for local recurrence rules;
- organization timezone versus UTC storage.

Prefer the database clock for database-owned expiry/lease semantics. Introduce an application clock abstraction only where application policy genuinely owns time.

## Adding a new feature

Use this checklist in the implementation PR:

- [ ] Production composition exists for the new surface.
- [ ] Public HTTP operation added to `PUBLIC_HTTP_OPERATIONS`, if applicable.
- [ ] Valid auth/authz probe added.
- [ ] Tenant isolation mode declared and tested with an existing foreign object.
- [ ] Success journey added.
- [ ] Durable result/outbox asserted exactly.
- [ ] Same-key replay tested for commands.
- [ ] Different-fingerprint conflict tested where meaningful.
- [ ] Relevant stale revision/terminal transition tested.
- [ ] Relevant concurrency race tested.
- [ ] Worker lease and stale-token fencing tested, if asynchronous.
- [ ] External side-effect crash windows tested, if applicable.
- [ ] Provider callback dedupe/out-of-order behavior tested, if applicable.
- [ ] `durable_snapshot()` extended for any new mutation tables.
- [ ] README/current coverage matrix updated.
- [ ] Existing V3 PostgreSQL CI gate remains green; do not add a redundant PR workflow.

## Naming and organization

Use behavioral names, not implementation names. A test such as
`test_crash_after_provider_finalize_before_action_ack_reclaims_without_second_send`
communicates the invariant being proven and the failure window being simulated.

Prefer one file per evidence domain rather than one file per class:

- HTTP surface/security/isolation/idempotency;
- scheduling/outbox;
- provider delivery and callback processing;
- business concurrency journeys;
- persistence invariants.

Shared fixture code belongs in support modules that do not start with `test_`.

## CI strategy

The default PR gate must remain bounded and deterministic. The current E2E tests run inside `PostgreSQL 18 V3 candidate and verticals`; this is intentional so one push does not fan out into multiple redundant workflows.

Future tiers may include:

- **PR gate:** deterministic invariant, race, security, tenant, replay, and crash tests;
- **manual/nightly stress:** hundreds/thousands of race iterations, fairness distributions, long lease recovery, and performance envelopes;
- **release proof:** schema/bootstrap equivalence, candidate migrations, production privileges, recovery, and performance evidence.

Do not make expensive probabilistic stress loops mandatory on every commit. They create CI noise and can hide deterministic architectural failures behind flakiness.

## What counts as complete

A suite is "complete" only relative to the production-composed capabilities that exist at that commit. It must be designed to become incomplete loudly when the architecture grows.

That is why the OpenAPI registry, durable snapshot, and explicit worker/callback checklists are part of the framework: adding a capability should create an obvious test obligation instead of silently reducing coverage percentage.
