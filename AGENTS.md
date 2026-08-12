# Request Engine — agent map

These instructions apply repository-wide. A nearer `AGENTS.md` may add stricter path-specific rules.

## Start here

Before editing, identify the primary owner and read only the canonical material needed for the task:

1. `docs/README.md` — documentation map and precedence.
2. `docs/11-capability-first-v3.md` — current product thesis and V3 baseline.
3. `docs/10-module-ownership-map.md` — where business changes belong.
4. owning `src/request_engine/modules/<module>/README.md` — local scope/boundary.
5. `docs/12-v3-transition-plan.md` — V2 disposition and baseline migration plan when touching transitional concepts/SQL.
6. `docs/07-database-access-contract.md` — Python ↔ PostgreSQL ownership and UoW rules.
7. `docs/09-python-module-architecture.md` — physical Python layout/import rules.
8. `docs/adr/README.md` — accepted architectural decisions and their rationale.

Use `docs/00-product-definition.md`, `docs/01-architecture-v2.md` and `docs/02-pre-sql-domain-contract.md` as V2 safety/design source material only according to the precedence in `docs/README.md`. Do not reintroduce a V2 concept that V3 explicitly deferred merely because it exists in those files or the design-chain SQL.

`docs/legacy/**` is historical and non-authoritative.

## Non-negotiable architecture

- Modular monolith: **module first, layer second**.
- V3 baseline business modules: `tenancy`, `catalog`, `requests`, `booking`, `queue`, `communications`.
- Transitional deferred modules: `delivery`, `payments`, `dispatch`. Baseline modules must not depend on them without an accepted architecture change and concrete use case.
- Cross-module imports use the target module's supported `contracts` surface; never import another module's `domain`, `application`, `adapters`, or `api` internals.
- `platform` contains technical cross-cutting mechanics only. `platform/scheduling` owns durable lease/retry/clock mechanics, not reminder/booking/queue policy.
- `bootstrap` is the composition root. Business code must not use it as a service locator.
- Domain code does not import FastAPI, SQLAlchemy, provider SDKs, or bootstrap/runtime configuration.
- Public operations are explicit `Query`, semantic `Command`, durable business `Request`, or `ScheduledAction`; do not collapse them behind a generic workflow/service abstraction.
- Authoritative state changes are semantic commands, not generic CRUD.
- PostgreSQL owns structural truth, locks, atomic consistency backstops and durable facts. Python owns command semantics, policy orchestration and transaction framing.
- One authoritative command normally uses one Session/AsyncSession and one explicit DB transaction.
- Never perform external network I/O while holding authoritative DB locks.
- n8n/providers are adapters/extensions, not owners of booking/request/queue authority. Their callbacks use authenticated idempotent semantic commands.
- `request_read.*` is a read contract, never mutation authority. `request_cmd.*` contains narrow consistency primitives, never workflow-sized stored procedures.

## Product-language discipline

Do not recreate the universal-model drift V3 is correcting.

- `Request` is new durable business demand needing later processing; cancel/reschedule are Commands by default.
- `ServiceQueue` is current FIFO service flow; `Waitlist` is future capacity interest. They are not synonyms.
- Reservation confirmation is distinct from attendance confirmation.
- Communications/recordatorios are durable transactional intent; provider transport remains external.
- `Workflow`, `OutcomeScope`, advanced Fulfillment, CapacityPool, PlanningRevision, dispatch and advanced payments are not baseline dependencies unless a later accepted decision reactivates them.
- Prefer stable capability names such as `appointments.book`, `queue.join`, `quotes.request` over table-shaped endpoints/tools.

## File/abstraction discipline

Prefer the smallest structure that keeps ownership obvious. Do not create ceremonial empty Clean Architecture trees.

Avoid generic dumping grounds such as `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, global `repositories.py`, or shared business `models.py`. Split by cohesive capability/use case when code actually grows.

Do not infer `table → entity → repository → endpoint`. Database structures may be serialization identities, append-only facts, links, or integrity mechanisms rather than public domain/API objects.

## Correctness-sensitive changes

For booking/capacity, queue selection, waitlist offers, scheduling, communications, authority, idempotency, outbox, or any concurrent mutation:

- identify the V3 promise/invariant being protected; during transition, consult relevant V2 invariant/race material only where the concept survives;
- preserve `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` ordering where specified;
- plan the full lock set and canonical lock order before acquisition when required;
- use real PostgreSQL tests for constraints, range overlap, locks, isolation, `SKIP LOCKED`, lease/fencing, privilege behavior and races;
- add a regression test for every fixed invariant/race bug.

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
