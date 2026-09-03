# End-to-End Evidence Framework

## Purpose

Request Engine treats E2E as executable architectural evidence, not a set of happy-path examples. A feature is covered only when tests can falsify its authentication, authority, tenancy, transaction, idempotency, concurrency, retry, lease, and crash-recovery contracts using the same runtime boundaries as production.

The framework lives in `tests/e2e/` and runs inside the existing PostgreSQL V3 CI job. Do not create another ordinary PR workflow for it.

## Principles

1. **Production-equivalent identities.** HTTP tests run through an ephemeral LOGIN inheriting `request_engine_app`; worker tests use a separate LOGIN inheriting `request_engine_worker`. Admin credentials only seed and inspect fixtures.
2. **PostgreSQL is real.** RLS, constraints, row locks, `SKIP LOCKED`, `SECURITY DEFINER`, transactions, idempotency, leases, and fencing are not mocked.
3. **Only external providers are doubled.** The scheduler, outbox, delivery store, application services, and database stay real.
4. **Negative evidence includes non-mutation.** `401`, `403`, `404`, conflicts, stale tokens, poison work, and duplicate callbacks are incomplete unless relevant durable state is unchanged.
5. **Replay is normal behavior.** Same-key replay, fingerprint conflict, lease reclaim, callback replay, and crash recovery are first-class distributed-system cases.
6. **Ambiguous external I/O reconciles before resend.** Unknown provider outcomes never justify an immediate blind resend.
7. **Composition is the authority.** The E2E registry represents what the current production app actually composes, not historical Markdown or planned routes.
8. **Caller journeys are product evidence.** A database proof or direct adapter call cannot substitute for a realistic public-API journey when a human UI, bot, agent, or automation is expected to operate the capability.

## Executable registry

`tests/e2e/http_surface.py` is the test-side registry for every public `/v1` operation. The Phase-5 development composition currently exposes 24 operations across capability discovery, catalog/business, appointments/attendance, queues/waitlist, public Request operations, and ReminderPlans.

Each entry declares:

- stable behavioral name;
- HTTP method and route template;
- capability requirement, or `None` for an intentionally authenticated discovery route;
- mutation and idempotency semantics;
- tenant-isolation classification;
- a syntactically valid probe.

`test_public_surface_contract.py` compares generated OpenAPI with the registry exactly. A new or removed endpoint therefore breaks CI until its evidence classification is updated. It also proves that every operation marked idempotent exposes a required `Idempotency-Key` header.

`/v1/capabilities` is intentionally special: it requires authentication but not a pre-existing capability grant. Do not force the general `403` rule onto discovery endpoints whose purpose is to describe available capabilities.

## Required HTTP evidence

A new public operation normally requires, in the same feature PR:

1. unauthenticated `401` and unchanged durable state;
2. capability `403` and unchanged durable state when the operation is capability-gated;
3. explicit treatment for authenticated discovery routes that intentionally have no capability gate;
4. tenant/Party isolation using data that genuinely exists in another organization;
5. precise rejection semantics: filtered/contextual `200`, Party-authority `403`, or non-disclosure `404` as appropriate;
6. success-path journey through the public adapter;
7. command replay: same key/same fingerprint returns the same logical result without another mutation;
8. same key/different fingerprint conflict where meaningful;
9. stale revision/terminal-state negatives where the aggregate is revisioned;
10. a real concurrency race when callers can contend for the same logical resource;
11. exact durable rows/outbox evidence rather than response-only assertions.

Internal commands are not made public just to obtain E2E coverage. For example, the current public Request composition exposes submit/read/cancel while result/complete/fail remain trusted processing surfaces and belong in integration evidence.

## Caller-realistic journeys

When a capability is consumed through HTTP by product software, acceptance must include journeys that exercise the public API in the order and failure modes a real caller would experience. Seed SQL may establish tenant/configuration prerequisites and administrative inspection may verify durable aftermath; business actions in the journey must use the composed API unless the test is specifically proving that no public operation exists.

Choose caller perspectives from the actual product surface rather than creating personas mechanically. Relevant perspectives include:

- **human/operator UI:** load a read model, act on the revision shown, refresh after mutation, and recover from stale state;
- **customer/self-service UI:** discover, submit, retry after an uncertain response, and observe only subject-safe state;
- **bot/agent/automation:** use typed public operations, replay the same intent safely, reject conflicting retries, and operate with only its granted capabilities;
- **two concurrent operators or clients:** contend through HTTP where the same operational fact may be changed concurrently;
- **reconnect/partial-connectivity caller:** repeat an operation after response loss or reload authoritative reads before continuing.

A feature does not need every perspective. It needs the perspectives that can materially falsify its real usage contract. At minimum, an externally operated semantic change requires one realistic end-to-end API journey plus the negative/retry/concurrency cases implied by its risks. A collection of isolated endpoint probes is not equivalent to a user journey.

A journey should assert both what the caller sees and what the system made durable. For rejected/stale/unauthorized attempts, status codes alone are insufficient: prove relevant durable state did not change. For successful multi-step operations, verify that subsequent API reads expose a coherent result rather than inspecting only the mutation response.

## Durable non-mutation snapshot

`evidence.py` centralizes broad negative-evidence counts. It currently covers:

- reservations;
- capacity claims and holds;
- queue entries;
- waitlist entries and slot offers;
- generic requests;
- ReminderPlans;
- outbox messages;
- ScheduledActions;
- CommunicationTasks and CommunicationDeliveries;
- ProviderEvents.

Whenever a new subsystem adds a durable table that rejected HTTP or worker work could mutate, extend `DurableSnapshot` in the same PR. Successful scenarios still require targeted row/status/revision/event assertions; the snapshot is not a substitute for them.

## Worker contract

Every asynchronous worker must prove:

- due work is claimable and future work is not;
- multiple workers claim disjoint sets with `SKIP LOCKED` or equivalent;
- claim tokens fence stale owners;
- lease expiry makes abandoned work reclaimable;
- retry increments attempts and clears lease state correctly;
- max-attempt exhaustion/dead-letter is terminal;
- poison work is classified deterministically instead of being recycled forever;
- runtime roles cannot bypass lifecycle semantics with direct destructive SQL.

## External-side-effect crash matrix

For any provider-backed side effect use this canonical timeline:

1. claim durable work;
2. prepare local intent/delivery identity;
3. perform or reconcile external I/O;
4. finalize provider result durably;
5. acknowledge the ScheduledAction/outbox work.

Test crashes at least at these windows:

- after claim, before prepare;
- after prepare, before known provider result;
- after external I/O, before local finalization;
- after local finalization, before action acknowledgement;
- after acknowledgement/replay.

The critical invariant for unknown external outcomes is **reconcile before resend**. For crash-after-finalize-before-ack, reclaim must produce a new token, the stale token must fail, the replay must perform zero second sends, there must be one logical delivery, and terminal outbox effects must remain exactly once.

## Provider callbacks/webhooks

When inbound provider processing is composed, add:

- exact duplicate event;
- same identity with conflicting payload/hash;
- out-of-order distinct events;
- unknown provider-message identity;
- callback after terminal delivery;
- callback racing reconciliation;
- two callback workers contending;
- crash after event persistence but before domain transition/outbox acknowledgement.

Provider-event identity must remain scoped by the database contract, including tenant/provider/connection identity.

## Time-bound behavior

For holds, offers, reminders, and leases test immediately before, exactly at, and immediately after expiry. Test not-due work, timezone conversion, and DST gaps/folds where local recurrence policy owns wall-clock time. Prefer PostgreSQL clock semantics for DB-owned leases and expiry.

## Adding a feature: Definition of Done

- [ ] Production composition exists.
- [ ] Every new public route is registered in `PUBLIC_HTTP_OPERATIONS`.
- [ ] OpenAPI equality remains exact.
- [ ] Authentication/capability/discovery behavior is classified.
- [ ] Tenant/Party boundary is tested with a real foreign object.
- [ ] Rejected operations prove durable non-mutation.
- [ ] At least one caller-realistic API journey proves the externally operated semantic change.
- [ ] Success journey asserts durable business state and coherent follow-up reads.
- [ ] Mutating operations prove idempotent replay and conflict semantics.
- [ ] Revisioned aggregates prove stale-revision behavior.
- [ ] Relevant contention runs concurrently.
- [ ] New worker proves claim disjointness, fencing, retry/dead-letter, and reclaim.
- [ ] New external side effect proves the applicable crash windows.
- [ ] New callback proves dedupe/out-of-order behavior.
- [ ] `DurableSnapshot` includes every new rejection-sensitive table.
- [ ] `tests/e2e/README.md` is updated.
- [ ] Existing V3 CI remains the single deterministic PR gate.

## CI tiers

**PR gate:** deterministic security, isolation, state-machine, replay, concurrency, crash, and caller-journey tests.

**Manual/nightly stress:** hundreds or thousands of contention iterations, fairness distributions, long-running lease recovery, and load envelopes.

**Release proof:** production-role bootstrap, schema/candidate equivalence, crash recovery, security, and performance evidence.

Do not put expensive probabilistic loops into every PR. CI should reject deterministic architectural failures quickly instead of producing noise.

## Completeness rule

A suite is complete only relative to the production-composed capabilities at that commit. The architecture must be designed to become incomplete **loudly** when production grows. OpenAPI equality, explicit operation metadata, durable snapshots, worker/callback checklists, and caller-realistic journeys exist specifically so adding a capability creates an immediate testing obligation rather than silently reducing coverage.
