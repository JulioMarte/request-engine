# Request Engine — agent map

These instructions apply repository-wide. A nearer `AGENTS.md` may add stricter path-specific rules.

## Start here

Before editing, identify the primary owner and read only the canonical material needed for the task:

1. `docs/README.md` — documentation map and precedence.
2. `docs/10-module-ownership-map.md` — where business changes belong.
3. owning `src/request_engine/modules/<module>/README.md` — local scope/boundary.
4. `docs/02-pre-sql-domain-contract.md` — invariants, serialization roots, lock protocols.
5. `docs/07-database-access-contract.md` — Python ↔ PostgreSQL ownership and UoW rules.
6. `docs/09-python-module-architecture.md` — physical Python layout/import rules.
7. `docs/adr/README.md` — accepted architectural decisions and their rationale.

Read `docs/00-product-definition.md` or `docs/01-architecture-v2.md` when the task changes product/domain/system behavior rather than merely implementing an already-decided contract.

`docs/legacy/**` is historical and non-authoritative.

## Non-negotiable architecture

- Modular monolith: **module first, layer second**.
- Business modules: `tenancy`, `catalog`, `requests`, `booking`, `delivery`, `payments`, `dispatch`.
- Cross-module imports use the target module's supported `contracts` surface; never import another module's `domain`, `application`, `adapters`, or `api` internals.
- `platform` contains technical cross-cutting mechanics only. Business vocabulary/policy belongs to a business module.
- `bootstrap` is the composition root. Business code must not use it as a service locator.
- Domain code does not import FastAPI, SQLAlchemy, provider SDKs, or bootstrap/runtime configuration.
- Authoritative state changes are semantic commands, not generic CRUD.
- PostgreSQL owns structural truth, locks, atomic consistency backstops and durable facts. Python owns command semantics, policy orchestration and transaction framing.
- One authoritative command normally uses one Session/AsyncSession and one explicit DB transaction.
- Never perform external network I/O while holding authoritative DB locks.
- `request_read.*` is a read contract, never mutation authority. `request_cmd.*` contains narrow consistency primitives, never workflow-sized stored procedures.

## File/abstraction discipline

Prefer the smallest structure that keeps ownership obvious. Do not create ceremonial empty Clean Architecture trees.

Avoid generic dumping grounds such as `utils.py`, `helpers.py`, `common.py`, `services.py`, `managers.py`, global `repositories.py`, or shared business `models.py`. Split by cohesive capability/use case when code actually grows.

Do not infer `table → entity → repository → endpoint`. Database structures may be serialization identities, append-only facts, links, or integrity mechanisms rather than public domain/API objects.

## Correctness-sensitive changes

For scheduling/capacity, payments, fulfillment, authority, completion, idempotency, outbox, or any concurrent mutation:

- identify affected invariant IDs in `docs/02-pre-sql-domain-contract.md`;
- preserve `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` ordering where specified;
- plan the full lock set and canonical lock order before acquisition when required;
- use real PostgreSQL tests for constraints, range overlap, locks, isolation, `SKIP LOCKED`, privilege behavior and races;
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
