# Request Engine V3 freeze scope

Status: **active Phase 6 release contract**.

Current operational roadmap: `v3-current-release-roadmap.md`.
Canonical gate registry: `v3-release-gates.md`.

This document defines what Phase 6 may prove and harden before the V3 release freeze. It does not replace the canonical V3 domain contract in `docs/v3/02-pre-sql-contract.md`, the product/API contract in `docs/v3/11-product-api-contract.md`, or accepted ADRs.

## Current baseline

The original Phase 6 branch baseline is historical. The current integrated release-proof baseline is:

- `development@3281075bdc5e19997a3ba8120fa6a275e7ee5ab1`;
- tree `6788623d107ea89ee5a422cfbacfe21c67368b0e`;
- G01–G16 integrated `PASS`;
- G17 `MISSING`;
- G18 `MISSING`;
- G19 `PARTIAL`;
- G20 `MISSING`;
- global `release_status: NOT_READY`.

The V3 candidate is the ordered SQL chain under `migrations/sql/v3_candidate/`. It remains candidate construction history. It is not the final production `0001_initial`.

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
- capability discovery and the frozen V3 public HTTP contract;
- worker fencing, bounded retries, crash recovery and existing fairness policy;
- ReservationAccess/Delivery behavior already integrated into the V3 candidate;
- explicitly accepted cross-tenant shared-capacity serialization already integrated into the V3 candidate.

The canonical release invariant vocabulary is `V3-I01` through `V3-I66`, reconciled by `v3-invariant-matrix.md` and `v3-invariant-proof-registry.json`. Older documents that mention a shorter I01–I61 range are historical and must not be used to truncate the current release registry.

## Out of V3

Phase 6 must not introduce product scope merely to make release engineering convenient. The following remain out unless an existing V3 guarantee cannot be made correct without a narrowly scoped fix:

- new domain entities or public product workflows;
- universal Workflow or generic workflow-runtime semantics;
- OutcomeScope or generalized fulfillment accounting;
- advanced payments or reconciliation;
- CapacityPool or generalized external capacity commitments;
- generalized dispatch, PlanningRevision, route or workforce optimization;
- new booking modes or compound Reservation semantics;
- broadcast/non-exclusive SlotOffer semantics;
- new waitlist preference languages;
- new public ReminderPlan operations not already frozen by V3;
- new communications feature families;
- provider federation or federated booking;
- generalized identity-resolution/deduplication or CRM contact-management semantics;
- exactly-once guarantees across PostgreSQL and external providers.

Existing deferred `payments`, generalized `dispatch`, and other non-baseline scaffolds remain deferred unless an accepted architecture change explicitly promotes them. This statement does not demote the already integrated ReservationAccess/Delivery feature; that concrete V3 behavior is part of the current candidate.

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
- stable error/OpenAPI contract corrections only when current behavior contradicts the frozen V3 contract and the compatibility impact is explicitly reviewed;
- bootstrap and migration-collapse tooling after candidate correctness is proven.

A Phase 6 change must not weaken a database invariant, tenant boundary, fencing rule, idempotency rule or terminal-state guarantee merely to simplify Python code or make a test green.

After G16, any public API/capability/error change is release-visible drift and requires intentional review of the frozen baseline rather than an incidental update.

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
14. Public capabilities, OpenAPI metadata and machine-readable errors remain consistent with the frozen G16 contract.
15. The complete release-critical attack/race/crash/retry/order/mutation envelope is executed as one mandatory G18 release proof.
16. A fresh production-like environment constructs the candidate with production-style roles and successfully runs representative app/worker behavior.
17. The final `0001_initial` is structurally and behaviorally equivalent to the frozen proven candidate.
18. The exact final release tree has a complete, valid evidence manifest with every G01–G20 gate `PASS`.

## Evidence rule

A release guarantee is not `PASS` because code or documentation appears to implement it. `PASS` requires current-branch executable evidence from one or more of:

- automated test;
- SQL/catalog assertion;
- deterministic release script;
- CI gate;
- benchmark/query-plan artifact where performance is the guarantee;
- machine-readable evidence artifact semantically validated by the release manifest.

Manual assumption is never sufficient for a release gate. A historical green workflow is supporting evidence only for the exact commit/tree it tested.

## Change-sequencing rule

The current required sequence is:

```text
G18 unified adversarial/failure proof
        ↓
G19 fresh production-like bootstrap
        ↓
candidate freeze
        ↓
G17 final 0001_initial + equivalence
        ↓
rerun affected frozen proofs
        ↓
G20 exact-head final manifest
```

Do not create or bless `0001_initial` before G18 and G19 prove the release failure/bootstrap envelope and the candidate is explicitly frozen.

Do not freeze indexes before representative query plans are measured. G15 already satisfies that requirement for the current candidate; any later schema/query change that invalidates those plans requires G15 regeneration.

Do not remove the V3 candidate chain until candidate-versus-initial structural and behavioral equivalence passes.

A blocker fix after candidate freeze invalidates every gate/fingerprint materially affected by that change and those proofs must be regenerated.

## Definition of Done

V3 is eligible for release only when all conditions are true:

- G01 through G20 in `v3-release-gates.md` are `PASS`;
- every `V3-I01..V3-I66` has a mapped enforcement owner and executable proof;
- every release-critical race in `v3-race-matrix.md` has deterministic executable proof;
- G18 composes the attack/race/crash/retry/order/mutation families into one mandatory validated release artifact;
- no open P0 or P1 release blocker remains;
- schema fingerprint equivalence passes for frozen candidate versus final `0001_initial`;
- the behavioral suite passes against the final initial migration path from an empty database;
- the G16 API/OpenAPI/capability/error contract remains frozen or any intentional versioned change is re-proven;
- production runtime roles pass negative privilege tests;
- representative hot paths pass the query-plan/index review on the final executable schema;
- runbooks and production worker/database configuration are explicit enough for G19;
- the fresh production-like release environment starts representative app and worker paths under real runtime roles;
- the release candidate completes the defined adversarial/failure exercise without invariant violation;
- the final release manifest records exact commit/tree identities, PostgreSQL/Python environment, schema/migration fingerprints, public-contract fingerprints and all mandatory evidence digests;
- `release_status` is `READY` only for the exact tree that is promoted.

After the first V3 release, the released `0001_initial` is immutable history. Future schema changes use new migrations.
