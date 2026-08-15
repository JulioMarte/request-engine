# Request Engine — agent map

These instructions apply repository-wide. A nearer `AGENTS.md` may add stricter path-specific rules.

## Branch workflow — mandatory

`development` is the canonical integration branch. `main` is release-only.

For ordinary feature, fix, refactor, test, documentation, or agent work:

1. fetch the remote and resolve the current `origin/development` HEAD;
2. create the work branch from that current `development` HEAD;
3. open the pull request against `development`;
4. reconcile long-lived work with the latest `development` before declaring it merge-ready;
5. never infer the development base from GitHub's default branch.

The only normal pull request allowed to target `main` is the release promotion `development -> main` after the integrated `development` state has passed the required release proof again.

Do not avoid conflicts by targeting a feature branch at `main` or by silently stacking it on another unmerged feature branch. If work genuinely depends on unmerged work, keep that dependency explicit and rebuild/rebase it onto `development` after the dependency is integrated before treating it as independently merge-ready.

See `CONTRIBUTING.md` for the canonical contributor workflow. The architecture tests enforce this PR topology in GitHub Actions.

## Start here

Before editing, identify the primary owner and read only the canonical material needed for the task:

1. `docs/README.md` — documentation map and precedence.
2. `docs/11-capability-first-v3.md` — current product thesis and V3 baseline.
3. `docs/v3/01-capability-contracts.md` — public/application capability semantics.
4. `docs/v3/02-pre-sql-contract.md` — V3 cardinalities, serialization roots, locks, transactions, invariants and race matrix.
5. `docs/10-module-ownership-map.md` — where business changes belong.
6. owning `src/request_engine/modules/<module>/README.md` — local scope/boundary.
7. `docs/07-database-access-contract.md` — Python ↔ PostgreSQL ownership and UoW rules.
8. `docs/09-python-module-architecture.md` — physical Python layout/import rules.
9. `docs/13-connection-surfaces.md` — mandatory boundary/adapter design between layers, modules, DB, workers and providers.
10. `docs/14-architecture-fitness-functions.md` — executable dependency/surface rules enforced by CI.
11. `docs/12-v3-transition-plan.md` and `docs/v3/sql-disposition.md` — migration/disposition context when touching transitional V2 concepts.
12. `docs/adr/README.md` — accepted architectural decisions and rationale.

Use `docs/00-product-definition.md`, `docs/01-architecture-v2.md` and `docs/02-pre-sql-domain-contract.md` only as V2 source material according to `docs/README.md`. Do not reintroduce a V2 concept V3 explicitly removed/deferred merely because it exists in old docs or SQL.

`docs/legacy/**` is historical and non-authoritative.

## Non-negotiable architecture

- Modular monolith: **module first, capability-local, layer-conscious, explicit connection surfaces**.
- V3 baseline business modules: `tenancy`, `catalog`, `requests`, `booking`, `queue`, `communications`.
- Transitional deferred modules: `delivery`, `payments`, `dispatch`. Baseline modules must not depend on them without an accepted architecture change and concrete use case.
- Cross-module imports use the target module's supported `contracts` surface; never import another module's `domain`, `application`, `adapters`, or `api` internals.
- Business HTTP routers/models/error mappings belong to the owning module's `api` package. `entrypoints/http` is composition/trust-boundary code, not a parallel business taxonomy.
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

## V3 product-language discipline

- `Request` is new durable business demand needing later processing; cancel/reschedule are Commands by default.
- `1 Reservation = 1 OfferingVersion + 1 subject + 1 interval` in baseline; no universal ReservationItem/cart.
- concrete `Resource` is the V3 capacity serialization root; do not recreate a one-to-one `CapacityAuthority` table without a new proven source type.
- `CapacityClaim` is the common Hold/Reservation capacity truth; do not recreate V2 `ResourceAllocation` one-to-one duplication.
- `ServiceQueue` is current FIFO service flow; `Waitlist` is future capacity interest.
- `SlotOpportunity` coordinates one released-slot recovery chain; `SlotOffer` is one candidate offer backed by a short CapacityHold in baseline.
- Reservation confirmation is distinct from attendance confirmation.
- Communications/reminders are durable transactional intent; provider transport remains external.
- `Workflow`, `OutcomeScope`, advanced Fulfillment, CapacityPool, PlanningRevision, dispatch and advanced payments are not baseline dependencies.
- Prefer stable capabilities such as `appointments.book`, `queue.join`, `waitlist.accept_offer`, `requests.submit` over table-shaped endpoints/tools.

## File/abstraction discipline

Prefer the smallest structure that keeps ownership obvious. Do not create ceremonial empty Clean Architecture trees.

Avoid generic dumping grounds such as `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, global `repositories.py`, or shared business `models.py`. Split by cohesive capability/use case when code actually grows.

Do not infer `table → entity → repository → endpoint`. Database structures may be serialization identities, append-only facts, links, or integrity mechanisms rather than public domain/API objects.

## Correctness-sensitive changes

For booking/capacity, queue selection, waitlist offers, scheduling, communications, authority, idempotency, outbox, or any concurrent mutation:

- identify the exact `V3-Ixx` invariants in `docs/v3/02-pre-sql-contract.md`;
- preserve the documented `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` protocol;
- follow canonical lock order and serialization roots before choosing SQL shape;
- use real PostgreSQL tests for constraints, range overlap, locks, isolation, `SKIP LOCKED`, lease/fencing, RLS/privilege behavior and races;
- add a regression test for every fixed invariant/race bug;
- do not claim `0001_initial` readiness until the V3 schema construction gate passes.

## Validation before completion

Run the narrowest relevant checks first, then repository checks when feasible:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

SQL changes also follow `migrations/AGENTS.md` and are validated against PostgreSQL 18.

Never claim a check passed unless it actually ran. Report skipped or unavailable checks explicitly.

## Documentation rule

The repository documentation is the system of record. Agent files are maps and operational guardrails, not duplicated architecture manuals. If a durable design decision changes, update its canonical doc/ADR and keep agent instructions short enough to remain useful.
