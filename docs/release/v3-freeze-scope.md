# Request Engine V3 freeze scope

Status: Phase 6 release contract.

This document defines what Phase 6 may prove and harden before the V3 release freeze. It does not replace the canonical V3 domain contract in `docs/v3/02-pre-sql-contract.md`, the product/API contract in `docs/v3/11-product-api-contract.md`, or accepted ADRs.

## Baseline

Phase 6 starts from commit `5f05c14cf559b29f936262b2be991631b01801ac` on `phase-6-v3-freeze-release-proof`. At that baseline the branch is identical to `development`.

The V3 candidate is the ordered SQL chain under `migrations/sql/v3_candidate/`. It is still a candidate construction history. It is not the final production `0001_initial`.

## In V3

Phase 6 freezes only behavior already present in the normative V3 baseline:

- tenant and authority boundaries;
- structured catalog/business reads;
- durable generic Requests;
- appointment booking and local resource capacity;
- CapacityHold and CapacityClaim semantics;
- Reservation lifecycle and attendance response;
- FIFO ServiceQueue;
- Waitlist, SlotOpportunity and SlotOffer released-slot recovery;
- transactional CommunicationTask/Delivery intent;
- ReminderPlan materialization already published by the V3 contract;
- durable ScheduledAction, OutboxMessage and ProviderEvent processing;
- idempotency and optimistic concurrency;
- trusted audit provenance and durable correlation;
- capability discovery and the Phase 5 public HTTP contract;
- worker fencing, bounded retries, crash recovery and existing fairness policy.

The canonical invariant vocabulary remains `V3-I01` through `V3-I61` in `docs/v3/02-pre-sql-contract.md`.

## Out of V3

Phase 6 must not introduce product scope merely to make release engineering convenient. The following remain out unless an existing V3 guarantee cannot be made correct without a narrowly scoped fix:

- new domain entities or public product workflows;
- universal Workflow or generic workflow-runtime semantics;
- OutcomeScope or generalized fulfillment accounting;
- advanced payments or reconciliation;
- CapacityPool or external capacity commitments;
- dispatch, PlanningRevision, route or workforce optimization;
- new booking modes or compound Reservation semantics;
- broadcast/non-exclusive SlotOffer semantics;
- new waitlist preference languages;
- new public ReminderPlan operations not already frozen by Phase 5;
- new communications feature families;
- exactly-once guarantees across PostgreSQL and external providers.

Deferred `delivery`, `payments`, and `dispatch` modules remain deferred baseline modules unless an accepted architecture change explicitly promotes them.

## Allowed Phase 6 changes

Phase 6 may change implementation when evidence exposes a release correctness gap. Allowed changes include:

- bug fixes;
- stronger relational invariants and constraints;
- lock ordering or transaction-boundary corrections;
- idempotency and optimistic-concurrency fixes;
- worker fencing, lease, retry and crash-recovery fixes;
- RLS, role and privilege hardening;
- indexes supported by measured query plans;
- audit/correlation fixes needed to reconstruct material operations;
- test, failure-injection, benchmark and release-proof infrastructure;
- stable error/OpenAPI contract corrections where current behavior contradicts the frozen V3 contract;
- bootstrap and migration-collapse tooling after candidate correctness is proven.

A Phase 6 change must not weaken a database invariant merely to simplify Python code or make a test green.

## Release guarantees

V3 freeze requires executable evidence for all of these guarantees:

1. A supported PostgreSQL 18 environment can construct V3 from an empty database.
2. Repeated fresh construction is deterministic.
3. Critical tenant-owned relationships cannot cross Organization boundaries.
4. RLS and runtime roles provide defense-in-depth for tenant-owned runtime access.
5. Capacity, Reservation, queue and released-slot invariants survive real concurrent PostgreSQL transactions.
6. Idempotent retries cannot duplicate already committed business effects.
7. Stale optimistic-concurrency writers fail deterministically.
8. Durable work has one current fenced owner and can recover after worker death.
9. Poison work has bounded retries and a visible terminal state.
10. Tenant fairness/backpressure behavior is bounded and does not permit unbounded starvation by design.
11. Provider events and communications tolerate duplicate, delayed, ambiguous and retried delivery without becoming business authority.
12. External I/O does not occur while authoritative business locks are held.
13. Hot-path indexes are justified by representative `EXPLAIN (ANALYZE, BUFFERS)` evidence.
14. Public capabilities, OpenAPI metadata and machine-readable errors remain consistent.
15. The final `0001_initial` is structurally and behaviorally equivalent to the proven candidate.
16. A fresh release environment passes the final release CI using only the release migration path.

## Evidence rule

A release guarantee is not `PASS` because code or documentation appears to implement it. `PASS` requires current-branch executable evidence from one or more of:

- automated test;
- SQL/catalog assertion;
- deterministic release script;
- CI gate;
- benchmark/query-plan artifact where performance is the guarantee.

Manual assumption is never sufficient for a release gate.

## Change-sequencing rule

Do not create or bless `0001_initial` before the candidate passes the correctness, concurrency, worker, security, contract and query-plan gates.

Do not freeze indexes before representative query plans are measured.

Do not remove the V3 candidate chain until candidate-versus-initial structural and behavioral equivalence passes.

## Definition of Done

V3 is eligible for freeze only when all conditions are true:

- G01 through G20 in `v3-release-gates.md` are `PASS`;
- every `V3-I01..V3-I61` has a mapped enforcement owner and executable proof;
- every release-critical race in `v3-race-matrix.md` has a deterministic PostgreSQL proof;
- no open P0 or P1 release blocker remains;
- schema fingerprint equivalence passes for candidate versus `0001_initial`;
- the full behavioral suite passes against `0001_initial` from an empty database;
- the final API/OpenAPI snapshot and machine-readable error contract are frozen;
- production runtime roles pass negative privilege tests;
- representative hot paths pass the query-plan/index review;
- runbooks and production worker/database configuration are explicit;
- the release candidate completes the defined soak/failure exercise without invariant violation;
- the release manifest records PostgreSQL, Python, schema, OpenAPI and schema fingerprints.

After the first V3 release, `0001_initial` is immutable history. Future schema changes use new migrations.