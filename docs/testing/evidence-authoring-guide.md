# Request Engine — Test Evidence Authoring Guide

Status: **normative test-evidence authoring guidance**.

This guide defines how contributors and coding agents turn a product, architecture, security, or database claim into credible test evidence. It complements `docs/testing/repository-governance-contract.md` and `tests/AGENTS.md`.

The governing principle is simple:

> A green test is useful only when the test was capable of failing for the defect it claims to detect.

Do not add a test merely to demonstrate that the implementation returns the value the test arranged for it to return. A test is evidence only when its setup, execution path, oracle, and failure mode are independent enough to expose a plausible broken implementation.

## 1. Authoring workflow

Before writing or modifying a durable test:

1. identify the current guarantee, contract, invariant, race, failure mode, or architecture rule being protected;
2. classify the protected detail as HARD, CONTROLLED, FLEXIBLE, or HISTORICAL;
3. state the plausible defect that should make the test fail;
4. choose the smallest execution boundary that can actually expose that defect;
5. create realistic preconditions without manufacturing the expected outcome;
6. exercise the real mechanism under test;
7. assert the authoritative outcome and the important negative/side-effect conditions;
8. run the narrow proof first, then the canonical CI lane that owns it.

If step 3 cannot be answered, the proposed test is probably checking implementation shape rather than behavior or safety.

## 2. Falsifiability and independent oracles

Prefer assertions that observe externally meaningful or authoritative state:

- returned business result plus durable database facts when persistence is part of the claim;
- the rejected outcome plus proof that no partial write, capacity consumption, or outbox effect escaped;
- the winning and losing transactions for a race, not merely that both calls returned;
- tenant-visible behavior through the runtime role when isolation/privilege is the claim;
- emitted durable intent plus reconciliation state when an asynchronous boundary is the claim.

Do not calculate the expected result by calling the same production helper that produced the actual result. Do not copy implementation constants or branch logic into the test when the contract provides an independent expected value.

For important fixes, use a mutation mindset: ask what one-line or one-condition regression would reintroduce the defect, and make sure the proof would fail if that regression existed.

## 3. PostgreSQL evidence must use PostgreSQL

When the behavior depends on PostgreSQL semantics, the proof must run against real PostgreSQL 18 in the repository CI environment. This includes constraints, RLS/privileges, transaction isolation, lock ordering, range/exclusion behavior, `SKIP LOCKED`, advisory/row locks, leases/fencing, and concurrency races.

Do not replace the mechanism under test with SQLite, an in-memory repository, a mocked Session/connection, or a fake lock implementation and then claim PostgreSQL correctness.

`tests/conftest.py` gives every `postgres`-marked proof a clean database before and after the test. Tests must not depend on rows or locks leaked by another test.

## 4. Build realistic dummy worlds

A database test should create the minimum **complete and valid business world** required for the scenario. Dummy data is preferred to magical IDs or partially initialized rows because it exercises the same cardinalities and relationships the product depends on.

A realistic booking/capacity scenario may need, as applicable:

```text
tenant / organization
principal + represented party + authority scope
subject/customer
location and timezone/hours
offering + immutable offering version + terms
resource + capability
resource/location assignment + availability
contextual terms or other configuration
existing hold/reservation/work item when the scenario requires one
```

The exact entities depend on the capability; do not create unrelated ceremonial data. The rule is **minimal but complete**, not maximal.

Prefer named scenario builders that return typed identifiers/context. A feature-local builder such as `tests/integration/f1_operational_profile/dummy_data.py` is appropriate while the scenario belongs to that suite. Move a builder to `tests/fixtures/` only when multiple independent suites genuinely share the same test world; do not create a global mega-fixture.

Use unique keys/UUIDs where collision would hide isolation defects. Keep scenario data business-plausible enough that timezone, authority, capacity, lifecycle, and cardinality assumptions are exercised rather than silently bypassed.

## 5. Direct SQL: allowed for setup, never as a shortcut around the claim

Direct SQL is legitimate when it is the clearest way to establish valid preconditions, inspect authoritative state, or directly prove a PostgreSQL backstop. It is especially appropriate for constraint/privilege/catalog tests and for constructing precise race preconditions.

Direct SQL is **not** permission to manufacture the result being tested.

Do not:

- insert the final Reservation/CapacityClaim/outbox row and then assert the application command would have created it;
- disable triggers, constraints, RLS, or security-definer boundaries to make fixture creation easier;
- write impossible cross-tenant or lifecycle states unless the test explicitly proves the database rejects that state;
- seed a successful idempotency/result record when the behavior under test is creation of that record;
- update derived/authoritative state behind the command's back and then use the resulting green assertion as command evidence.

When the capability/API/application path itself is part of the contract, execute the action under test through that supported path. A privileged setup connection may establish valid prerequisites, but the operation whose authority or runtime privilege is being proved must use the relevant runtime principal/role/surface.

## 6. Concurrency and transaction proofs

A concurrency proof must create a real contested condition:

- use independent connections/Sessions/transactions for independent actors;
- coordinate the intended interleaving with barriers, events, locks, or other deterministic synchronization;
- assert both the winner and loser semantics plus final authoritative database state;
- verify no oversell, duplicate durable effect, partial write, or leaked lock remains.

Do not use one transaction to simulate two contenders. Do not rely on `sleep()` alone to guess scheduling. Do not mock the lock or transaction mechanism whose behavior is being claimed.

## 7. Common false-positive shortcuts

Reject a test design when it does any of the following without a specific documented reason:

- asserts only HTTP 200/accepted status while ignoring durable state;
- mocks the component that owns the invariant being tested;
- seeds the expected output before executing the operation;
- creates rows that normal constraints/authority would never allow;
- bypasses the runtime role for a privilege/isolation claim;
- uses the implementation under test to compute its own expected answer;
- tests only the happy path for a safety claim that is about rejection, races, retries, or failure;
- shares mutable fixture state between tests;
- depends on execution order;
- converts a known failing proof into a weaker assertion just to make CI green.

If an unavoidable test double is used at an external provider boundary, keep the authoritative business/database path real and make the double model only the remote system behavior being excluded from the test scope.

## 8. Test placement and evidence metadata

Physical location answers who owns/runs the proof; pytest markers answer what evidence it provides.

Use the repository conventions in `tests/AGENTS.md`:

```text
tests/unit/          isolated logic
tests/modules/       module-owned behavior
tests/architecture/  repository/dependency/fitness rules
tests/db/            PostgreSQL invariants/backstops
tests/e2e/           production-like public journeys
tests/integration/   component/capability integration
tests/historical/    pinned release provenance only
```

Use declared evidence/risk markers such as `invariant`, `contract`, `fitness`, `adversarial`, `historical`, `concurrency`, `security`, `capacity`, `provenance`, and `temporal`. Do not create marker noise that does not improve selection or explain the proof.

## 9. Review checklist

Before accepting a new or changed test, be able to answer:

```text
What guarantee/risk does this prove?
What plausible defect makes it fail?
Is the setup a valid product/database state?
Does dummy data include every prerequisite that matters?
Did setup accidentally pre-create the expected result?
Is the real mechanism under test being exercised?
If PostgreSQL semantics matter, is real PostgreSQL used?
If authority/privilege matters, is the real runtime role/surface used?
If concurrency matters, are there independent transactions and deterministic coordination?
Does the assertion inspect authoritative outcome and important absence-of-side-effects?
Would a broken implementation still pass because of a shortcut?
```

A test that cannot answer these questions is not yet reliable evidence, even if it is green.

## 10. Validation sequence

Run the narrowest relevant test while iterating. Before completion, run the canonical lane that owns the proof. For ordinary Python/architecture/unit/module work that is `scripts/ci/ci_jobs.py python-quality`; PostgreSQL/current-product changes additionally require the appropriate PostgreSQL 18 lane. Exact-head CI remains required before merge.

Never report a proof as passed unless it actually ran against the intended execution environment.