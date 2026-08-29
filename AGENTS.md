# Request Engine — agent map

These instructions apply repository-wide. A nearer `AGENTS.md` may add stricter path-specific rules.

## Reporting discipline — mandatory

When reporting changes to the repository owner, write in plain operational language, not implementation jargon:

1. explain what changed in production terms — what a doctor, operator, or API consumer would experience;
2. state explicitly what was NOT changed and any pre-existing issues discovered along the way;
3. surface decisions made on the owner's behalf and pending decisions as explicit, answerable questions;
4. never report a check as passed unless it actually ran against the intended environment.

## Branch workflow — mandatory

`development` is the canonical integration branch. `main` is release-only. Request Engine uses **one serialized ordinary development integration lane**.

For ordinary feature, fix, refactor, test, documentation, release-proof, or agent work:

1. fetch the remote and resolve the current `origin/development` HEAD;
2. do not start a second merge-ready sibling workstream while another ordinary integration branch is still active;
3. create/rebuild the work branch from the current `development` state;
4. set `.github/development-integration-lane` to exactly the work branch name;
5. open the pull request against `development`;
6. finish the complete coherent feature/gate on that branch;
7. if `development` changes before merge, reconcile/rebuild the branch onto the new integrated state and reclaim the lane with the same actual branch name;
8. require exact-head CI/evidence before merge;
9. merge into `development` and delete the merged work branch;
10. only then start the next ordinary work branch from the new `development` HEAD.

`tmp/*` branches are scratch/reconciliation space only and MUST NOT become ordinary PR heads.

The only normal pull request allowed to target `main` is the release promotion `development -> main` after the integrated `development` state has passed the required release proof again.

Do not avoid conflicts by targeting a feature branch at `main`, silently stacking it on another unmerged feature branch, or keeping sibling branches from an older `development` snapshot and treating them as independently merge-ready. Exploratory parallel work may exist provisionally, but after the current integration owner merges it must reconcile with the new `development`, claim the lane, and rerun required checks before review.

`tests/architecture/test_branch_workflow_contract.py` enforces this topology. A **Development integration lane mismatch** is an integration-state error: fetch/reconcile with current `origin/development`, set `.github/development-integration-lane` to the actual PR head, and rerun CI. Do not weaken or bypass the test.

See `docs/architecture/branch-integration-contract.md` for the canonical policy and `CONTRIBUTING.md` for contributor steps. Never infer the development base from GitHub's default branch.

## Start here

Before editing, identify the primary owner and read only the canonical material needed for the task:

1. `docs/README.md` — documentation map, precedence and current post-V3-baseline status.
2. `docs/11-capability-first-v3.md` — current product thesis and V3 baseline.
3. `docs/v3/01-capability-contracts.md` — public/application capability semantics.
4. `docs/v3/02-pre-sql-contract.md` — V3 cardinalities, serialization roots, locks, transactions, invariants and race matrix.
5. `docs/10-module-ownership-map.md` — where business changes belong.
6. owning `src/request_engine/modules/<module>/README.md` — local scope/boundary.
7. `docs/07-database-access-contract.md` — Python ↔ PostgreSQL ownership and UoW rules.
8. `docs/09-python-module-architecture.md` — physical Python layout/import rules.
9. `docs/13-connection-surfaces.md` — mandatory boundary/adapter design between layers, modules, DB, workers and providers.
10. `docs/14-architecture-fitness-functions.md` — executable dependency/surface rules enforced by CI.
11. `docs/testing/repository-governance-contract.md` — HARD / CONTROLLED / FLEXIBLE / HISTORICAL rules for architecture shape, DTO/type boundaries, naming, docs, tests and LLM instruction routing.
12. `docs/testing/README.md` — current test architecture, guarantee registry and proof-map entry point.
13. `docs/testing/evidence-authoring-guide.md` — falsifiable-test workflow, realistic dummy data, PostgreSQL proof boundaries and false-positive avoidance when changing tests.
14. `migrations/README.md` — immutable V3 baseline and append-only post-release migration policy when touching schema.
15. `docs/12-v3-transition-plan.md` and `docs/v3/sql-disposition.md` — historical migration/disposition context when touching transitional V2 concepts.
16. `docs/adr/README.md` — accepted architectural decisions and rationale.

Use `docs/00-product-definition.md`, `docs/01-architecture-v2.md` and `docs/02-pre-sql-domain-contract.md` only as V2 source material according to `docs/README.md`. Do not reintroduce a V2 concept V3 explicitly removed/deferred merely because it exists in old docs or SQL.

`docs/legacy/**` is historical and non-authoritative.

## Non-negotiable architecture

- Modular monolith: **module first, capability-local, layer-conscious, explicit connection surfaces**.
- V3 baseline business modules: `tenancy`, `catalog`, `requests`, `booking`, `queue`, `communications`.
- `delivery` is narrowly reactivated/incubating for `ReservationAccess`; advanced fulfillment/execution remains deferred. Baseline modules must not import Delivery internals; current composition occurs through published contracts at the worker composition boundary.
- `payments` and `dispatch` remain deferred/incubating. Baseline modules must not depend on them without an accepted architecture change and concrete use case.
- Cross-module imports use the target module's supported `contracts` surface; never import another module's `domain`, `application`, `adapters`, or `api` internals.
- Business HTTP routers/models/error mappings belong to the owning module's `api` package. `entrypoints/http` is composition/trust-boundary code, not a parallel business taxonomy.
- API/Pydantic transport DTOs, application Command/Query types, domain values, cross-module contracts and persistence mappings are distinct boundaries even when fields currently match.
- Business-module `domain`, `application`, and `contracts` remain Pydantic-free; map transport types at the API boundary.
- Entrypoints compose modules through published module surfaces and must not reach directly into module DB/provider adapters.
- Module HTTP routers depend on application `Protocol` surfaces. Concrete DB/provider construction belongs in the module-owned install/composition surface.
- `platform` contains technical cross-cutting mechanics only. `platform/scheduling` owns durable lease/retry/clock mechanics, not reminder/booking/queue policy.
- `bootstrap` is a composition root. Business code must not use it as a service locator.
- Domain code does not import FastAPI, SQLAlchemy, provider SDKs, or bootstrap/runtime configuration.
- Public operations are explicit `Query`, semantic `Command`, durable business `Request`, or `ScheduledAction`; do not collapse them behind a generic workflow/service abstraction.
- Authoritative state changes are semantic commands, not generic CRUD.
- PostgreSQL owns structural truth, locks, atomic consistency backstops and durable facts. Python owns command semantics, policy orchestration and transaction framing.
- One authoritative command normally uses one Session/AsyncSession and one explicit DB transaction.
- Never perform external network I/O while holding authoritative DB locks.
- n8n/providers are adapters/extensions, not owners of booking/request/queue authority. Their callbacks use authenticated idempotent semantic commands.
- `request_read.*` is a read contract, never mutation authority. `request_cmd.*` contains narrow consistency primitives, never workflow-sized stored procedures.

## Repository governance classification

When a test or architecture rule appears to block a legitimate change, classify the protected detail before editing the rule:

```text
HARD        semantic/invariant boundary; fail closed by default
CONTROLLED  accepted architecture/product shape; explicit evolution decision required
FLEXIBLE    private implementation detail; do not freeze gratuitously
HISTORICAL  pinned release provenance; resolve against the historical tree/release
```

Do not use pre-production flexibility to weaken a HARD boundary. Do not use architecture fitness to freeze FLEXIBLE filenames, counts, private helper names, or internal file splits. `docs/testing/repository-governance-contract.md` is authoritative for this classification.

## Connection-surface design gate

Before implementing a new capability, layer, module integration or provider connection, explicitly identify:

```text
Business owner:
Capability:
Inbound caller and contract:
Authentication/authorization boundary:
Application Command/Query:
Transaction and idempotency boundary:
Domain invariants:
Database surface:
Cross-module contract surface:
Provider/event/scheduled surface:
Failure, retry and reconciliation semantics:
```

A component is not designed until its inbound and outbound `|-|` surfaces are designed. Do not create a new box and improvise its connectors afterward.

For every boundary ask: **what crosses it, who owns it, what guarantees it, and what happens when it fails or is repeated?**

For PostgreSQL write surfaces also identify `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT`, lock roots/order, constraints relied upon, tenant context and concurrent-loser semantics.

For provider surfaces identify timeout, idempotency, retryability, ambiguous outcomes and reconciliation. Never blind-retry an externally ambiguous operation.

## Architecture fitness failures

Architecture tests are executable design constraints, not style suggestions. If a fitness test fails:

1. identify the boundary and dependency edge the change introduced;
2. verify ownership and whether the connection must be synchronous;
3. use an existing supported `contracts`/application port surface when one exists;
4. design a new explicit surface only when the capability genuinely requires it;
5. update canonical architecture docs when accepting a new dependency direction.

Do **not** make CI green by automatically widening dependency allowlists, moving business code into `platform`/`common`/`shared`, re-exporting domain/adapters through `contracts`, suppressing the test, or replacing a required atomic transaction with events solely for architectural aesthetics.

## Test evidence discipline

A green test is not automatically evidence. When adding or changing a durable proof, follow `docs/testing/evidence-authoring-guide.md` and the nearest `tests/AGENTS.md`.

Before writing the assertion, identify:

```text
protected guarantee/risk
plausible defect that must make the test fail
real execution boundary needed to expose it
valid preconditions / realistic dummy-data world
independent expected outcome / oracle
authoritative state and important absence of side effects
canonical CI lane that owns the proof
```

Do not seed the result that the operation under test is supposed to create. Do not compute the expected answer by calling the same production helper. Do not weaken a proof solely because the current implementation fails it.

When PostgreSQL semantics are part of the claim, use real PostgreSQL 18. Build the minimum complete business-plausible world needed by the scenario rather than magical IDs or impossible partial rows. Direct SQL may establish valid prerequisites, inspect authoritative state, or directly prove a DB constraint/backstop; it must not bypass the authority, RLS, constraint, transaction, lock, or application surface whose behavior is being claimed.

Concurrency evidence uses independent transactions/connections and deterministic synchronization. Do not simulate two contenders inside one transaction or claim a race proof from timing-only sleeps.

## V3 product-language discipline

- `Request` is new durable business demand needing later processing; cancel/reschedule are Commands by default.
- `1 Reservation = 1 OfferingVersion + 1 subject + 1 interval` in baseline; no universal ReservationItem/cart.
- concrete `Resource` is the V3 capacity serialization root; do not recreate a one-to-one `CapacityAuthority` table without a new proven source type.
- `CapacityClaim` is the common Hold/Reservation capacity truth; do not recreate V2 `ResourceAllocation` one-to-one duplication.
- `ServiceQueue` is current FIFO service flow; `Waitlist` is future capacity interest.
- `SlotOpportunity` coordinates one released-slot recovery chain; `SlotOffer` is one candidate offer backed by a short CapacityHold in baseline.
- Reservation confirmation is distinct from attendance confirmation.
- Communications/reminders are durable transactional intent; provider transport remains external.
- `ReservationAccess` is the narrowly admitted Delivery capability; advanced Fulfillment remains out of baseline scope.
- `Workflow`, `OutcomeScope`, advanced Fulfillment, CapacityPool, PlanningRevision, dispatch and advanced payments are not baseline dependencies.
- Prefer stable capabilities such as `appointments.book`, `queue.join`, `waitlist.accept_offer`, `requests.submit` over table-shaped endpoints/tools.

## File/abstraction discipline

Prefer the smallest structure that keeps ownership obvious. Do not create ceremonial empty Clean Architecture trees.

Avoid generic dumping grounds such as `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, global `repositories.py`, or shared business `models.py`. Split by cohesive capability/use case when code actually grows.

Do not infer `table → entity → repository → endpoint`. Database structures may be serialization identities, append-only facts, links, or integrity mechanisms rather than public domain/API objects.

## Correctness-sensitive changes

For booking/capacity, queue selection, waitlist offers, scheduling, communications, authority, idempotency, outbox, delivery access, or any concurrent mutation:

- identify the exact `V3-Ixx` invariants in `docs/v3/02-pre-sql-contract.md` and any narrower accepted contract for the capability;
- preserve the documented `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` protocol;
- follow canonical lock order and serialization roots before choosing SQL shape;
- use real PostgreSQL tests for constraints, range overlap, locks, isolation, `SKIP LOCKED`, lease/fencing, RLS/privilege behavior and races;
- add a regression test for every fixed invariant/race bug;
- treat `migrations/versions/0001_initial.py` as immutable release history;
- implement post-release schema changes as new append-only Alembic revisions rather than editing `0001_initial` or the frozen 43-file V3 candidate.

## Validation before completion

Run the narrowest relevant checks first. Then run the canonical lane that owns the changed proof rather than inventing a parallel validation path.

For Python/architecture/unit/module work, the reusable canonical job is:

```bash
python scripts/ci/ci_jobs.py python-quality
```

It owns the effective-line budget, dependency/environment consistency, Ruff, Pyright, security/dependency checks, architecture tests, unit tests and module tests. PostgreSQL/current-product changes additionally run the appropriate PostgreSQL 18 runner described by `docs/testing/README.md` and the relevant module/migration instructions.

Exact-head CI remains the merge evidence. Never claim a check passed unless it actually ran against the intended execution environment; report skipped or unavailable checks explicitly.

## Documentation rule

The repository documentation is the system of record. Agent files are maps and operational guardrails, not duplicated architecture manuals. If a durable design decision changes, update its canonical doc/ADR and keep agent instructions short enough to remain useful.

Historical transition/release-proof documents may retain the tense and status of the checkpoint they document, but current maps/READMEs must not describe the released V3 baseline as if it were still pre-baseline or awaiting `0001_initial`/promotion.
