# Test agent rules

Applies to `tests/**` in addition to the repository-wide `AGENTS.md`.

Before adding, deleting, moving, or weakening a durable proof, read `docs/testing/README.md`, `docs/testing/repository-governance-contract.md`, and `docs/testing/evidence-authoring-guide.md`.

For system/E2E work, also read `docs/architecture/docker-e2e-ci-plan.md`. It is the canonical execution contract for the reusable Docker E2E platform. F-01 is one suite that consumes that platform; it does not define the platform.

## Rigidity versus flexibility

Every structural assertion must be treated as one of:

```text
HARD        invariant or semantic boundary; fail closed by default
CONTROLLED  accepted architecture/product shape; deliberate evolution only
FLEXIBLE    private implementation shape; do not freeze gratuitously
HISTORICAL  pinned release provenance; resolve against the historical tree/release
```

Do not interpret "fitness functions may evolve" as permission to relax HARD boundaries such as DTO/domain/persistence separation, cross-module `contracts`, dependency acyclicity, authority, transaction ownership, naming semantics, repository instruction routing, or exact-head integration discipline.

Conversely, do not turn FLEXIBLE details such as exact test filenames, test counts, private helper names, or internal file splits into permanent architecture contracts.

## Evidence integrity — tests must be able to prove something false

A green test is evidence only when a plausible defect in the claimed behavior would make it fail.

Before authoring a durable test, identify:

```text
protected guarantee / risk
plausible defect that must fail the test
real execution boundary needed to expose it
valid preconditions / dummy-data world
independent expected outcome / oracle
authoritative state and negative side effects to assert
canonical CI lane that owns the proof
```

Do not write tests whose setup already manufactures the expected result, whose expected value is computed by the same production helper under test, or whose assertion merely confirms an implementation detail with no independent contract meaning.

For an important bug/race fix, use a mutation mindset: name the small regression that would reintroduce the defect and ensure the proof would turn red under that regression.

## Reusable Docker system/E2E platform

Production-like black-box journeys should use the reusable Docker E2E platform unless the risk genuinely requires a different execution model.

The governing model is:

```text
stable deployment definition
        ×
swappable suite workload
        ↓
fresh isolated world by default
```

When adding a normal system/E2E suite:

1. add the suite to the platform suite registry instead of creating a feature-specific full Compose stack or workflow;
2. use the generic `e2e-runner` unless the test technology itself requires a specialized runner;
3. declare required services/profiles, cost class, fault-injection need and allowed CI modes explicitly;
4. start from a fresh authoritative world by default; never depend on state leaked by a previous suite;
5. create business state through supported bootstrap/API contracts after the installation trust root exists; do not use SQL to manufacture the result of the journey;
6. exercise Request Engine as an external consumer over real network boundaries;
7. assert the positive outcome and important negative side effects independently;
8. emit stable checkpoints/JUnit/evidence into the suite's namespaced artifact directory;
9. preserve local/CI reproducibility through the same suite selector/orchestrator contract;
10. update the reusable platform contract only when the platform itself changes, not merely because a new ordinary suite is added.

A normal black-box `e2e-runner` MUST NOT receive or gain:

```text
PostgreSQL DSNs or PG* installation credentials
network access to postgres/backend-only services
Docker socket / Docker administrative authority
Request Engine application internals as an installed package
bind mounts of src/request_engine
repository/service/application shortcuts that bypass public contracts
```

The platform must prove these isolation properties negatively; suite code must not merely promise to avoid them.

The runner is a client. Infrastructure lifecycle and fault injection belong to the orchestrator. A suite may request `kill/restart` of API, worker or another declared service through the platform protocol, but test code must not mount `/var/run/docker.sock` or directly administer the Docker host.

For multi-phase suites, persist only the minimum state needed to resume through the platform's ephemeral state contract. Do not use PostgreSQL as a private test state bus. Keep credentials/proofs separate from artifact-safe checkpoint state and prefer reauthentication through the API over persisting bearer tokens.

`suite=all` means executing selected suites against independent fresh worlds by default. Reuse immutable images/layers and caches, not authoritative database/business state. Sharing a world between suites is an explicit optimization that requires demonstrated independence and must never become an accidental ordering dependency.

Specialized runners such as browser/load/contract runners are permitted when the tool/risk genuinely differs. They should preserve the same black-box isolation unless the owning risk contract explicitly requires another boundary. A new feature or a preference for another test framework is not by itself justification for bypassing the reusable platform.

If a black-box journey cannot complete without direct SQL, an internal import, a fabricated worker principal, or another privileged shortcut, treat that as a product/deployment gap. Do not hide the gap in test setup.

## Test ownership and evidence

- Organize durable feature tests by ownership/scope, not by the historical feature that introduced them. Module-owned tests belong under `tests/modules/<owner>/`; cross-module PostgreSQL contract/invariant tests belong in `tests/db/`; public production-like journeys belong in `tests/e2e/` or the platform's dedicated system/E2E suite package; dependency/import/repository-governance fitness functions belong in `tests/architecture/`.
- `tests/historical/` is reserved for pinned release provenance/compatibility. Historical evidence must not force current Request Engine head to preserve an obsolete implementation shape.
- Classify what a test proves with pytest markers instead of creating parallel physical trees for `invariant`, `contract`, `adversarial`, or similar evidence classes. Physical location answers who owns the proof; markers answer what evidence it provides.
- Feature-local integration suites may exist while a feature is under active development. Before/at promotion into the current product, disposition them as durable current proof, historical evidence, replacement, or genuine redundancy rather than accumulating feature-era suites forever.
- File LOC and function complexity are review signals, not test-file architecture invariants. A large cohesive scenario MAY remain intact when splitting would separate setup/sequence/assertions without an independent reason to change. When CI emits `REVIEW_CANDIDATE`, follow `docs/engineering-quality/agent-semantic-review-playbook.md`; do not split a test solely to lower LOC or C901.

## Quality-signal evidence

Tests that protect the maintainability review system must prove its **authority semantics and agent feedback**, not assert that a particular code shape is universally good.

A valid quality-signal test should distinguish:

```text
INVARIANT_FAILURE   -> deterministic blocker
REVIEW_CANDIDATE    -> non-blocking evidence requiring semantic interpretation
HEALTHY_AS_IS       -> valid reviewed outcome; no refactor required
```

For heuristic sensors, test the detector with healthy counterexamples and problematic examples. Assert that output tells agents what was measured, why review was requested, what not to do, where the semantic protocol lives, and which deterministic proofs must be rerun after a change.

Never write a test whose only desired repair is "make the number smaller". A future proposal to make a heuristic blocking requires explicit normative approval and evidence that the blocker improves the protected property with acceptably low false positives and gaming pressure.

## PostgreSQL and dummy-data evidence

- Use real PostgreSQL 18 for locks, constraints, transaction isolation, range behavior, `SKIP LOCKED`, privileges/RLS, leases/fencing, and concurrency races. Never claim PostgreSQL correctness from SQLite, an in-memory repository, a mocked Session/connection, or a fake lock.
- Every `postgres` proof starts and ends from a clean database through `tests/conftest.py`; do not depend on leaked rows, sequence state, or locks from another test.
- Build the minimum complete valid business world required by the scenario: tenant, actor/authority, subject, offering/version, resource/capability, location/assignment/availability, terms, existing commitments, etc. only as applicable. Prefer named scenario builders over magical IDs or partially initialized rows.
- Direct SQL may create valid prerequisites, inspect authoritative state, or directly prove a PostgreSQL constraint/backstop. It must not insert the final outcome the command/API is supposed to create, disable triggers/constraints/RLS, seed a success/idempotency result in advance, or construct an impossible state merely to make the assertion pass.
- When authority, runtime privilege, API, application command, or transaction orchestration is part of the claim, execute the operation under test through that real role/surface. A privileged setup connection does not count as evidence for runtime authorization.
- Shared builders belong in `tests/fixtures/` only when multiple independent suites truly share the same world. Keep feature-specific builders beside their owning suite; do not create a global mega-fixture.
- Use unique tenant/business identifiers when collisions could mask isolation errors. Dummy data should be business-plausible enough to exercise real cardinality, authority, timezone, capacity, and lifecycle assumptions.

## Correctness-sensitive evidence

- Do not make a critical concurrency test pass by mocking the database mechanism under test.
- Race/invariant regressions should reproduce the failing interleaving or enforcement condition before the fix. Use independent transactions/connections and prefer explicit synchronization/barriers over timing-only `sleep()` races.
- A race proof asserts winner semantics, loser semantics, and final authoritative state; it should also prove no oversell, duplicate durable effect, partial write, or leaked lock remains.
- Use pytest markers declared in `pyproject.toml`. Evidence markers complement execution markers; avoid marker noise that does not improve selection or proof meaning.
- Tests should assert semantic outcomes/invariants, not incidental ORM call sequences or broad snapshots when a smaller semantic assertion is sufficient.
- Do not assert only an HTTP status for a durable/safety claim. Inspect the relevant durable state and important absence of side effects.
- Provider test doubles are acceptable only at the external boundary being excluded from scope; the authoritative business/database path must remain real when that is the claim.

## Architecture/repository proofs

Architecture tests should strongly enforce HARD boundaries, detect CONTROLLED drift with actionable messages, and avoid freezing FLEXIBLE shape.

For DTO/type-boundary tests, protect the separation itself:

```text
HTTP Body/View != application/domain/contracts/persistence
Pydantic business transport != domain/application/cross-module contract
provider SDK type != business contract
```

For naming tests, enforce ownership-signaling conventions (`*Body`, `*View`, semantic command/query names, no generic business dumping grounds) rather than exact inventories of every class/file.

For LLM/documentation governance, prove that repository/local instruction adapters route to canonical `AGENTS.md`/docs and cannot silently become independent conflicting architecture manuals. For semantic quality review, also prove that agent instructions require the review/fix/re-proof protocol and treat repository source/comments/strings as data rather than reviewer instructions.

Removing or weakening a failing safety/architecture test requires an explicit KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition tied to the guarantee that remains protected. Never weaken a test solely because the implementation currently fails it.
