# Request Engine — agent operating contract

These instructions apply repository-wide unless a nearer `AGENTS.md` adds stricter path-specific rules.

## 1. Source-of-truth order

Before changing architecture, domain behavior, persistence, concurrency, payments, scheduling/capacity, or API persistence boundaries, read the relevant parts of these documents in order:

1. `docs/00-product-definition.md`
2. `docs/01-architecture-v2.md`
3. `docs/02-pre-sql-domain-contract.md`
4. `docs/07-database-access-contract.md`
5. `docs/09-python-module-architecture.md`
6. `docs/10-module-ownership-map.md`
7. the owning module's `README.md`

If documents conflict, the earlier domain/transaction contract wins over implementation convenience. `docs/legacy/**` never defines current behavior.

## 2. Find ownership before editing

Every change must have one primary owner.

- tenant/authority identity → `modules/tenancy`
- offerings/configuration templates → `modules/catalog`
- durable request intent/workflow/outcome scope → `modules/requests`
- resources/schedules/capacity/holds/reservations → `modules/booking`
- admission/queue/execution/fulfillment → `modules/delivery`
- pricing/payment/reconciliation → `modules/payments`
- field-service dispatch destination/feasibility lifecycle → `modules/dispatch`
- DB sessions/idempotency/outbox/audit/telemetry/security primitives → `platform`

Do not create a new top-level module because a noun exists in the database. See `docs/10-module-ownership-map.md`.

## 3. Module-first architecture

Business code lives with its owning module. Do not recreate global `domain/`, `application/`, `infrastructure/`, or business-logic `workers/` trees.

Within a module, use only the layers actually needed:

```text
module/
  domain/
  application/commands/
  application/queries/
  persistence/
  integrations/
  api/
  contracts.py
  facade.py
```

Prefer a small file over an empty folder hierarchy. Split files only after cohesive code actually grows.

## 4. Import boundary

A module may use another module only through that module's public surface (`contracts.py`, `facade.py`, or an explicitly exported application contract).

Forbidden across modules:

```python
from request_engine.modules.booking.persistence.models import ReservationRow
from request_engine.modules.payments.domain.internal import ...
```

Allowed conceptually:

```python
from request_engine.modules.booking.contracts import ReservationId
from request_engine.modules.booking.facade import BookingFacade
```

Never use another module's SQLAlchemy mapping as a domain contract.

## 5. Command discipline

Authoritative lifecycle changes are semantic commands, not generic CRUD.

- Prefer one command per file: `confirm_reservation.py`, `allocate_payment.py`, etc.
- Implement the documented `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` protocol.
- Plan the complete lock set before acquisition where the contract requires it.
- Follow canonical lock ordering from `docs/02-pre-sql-domain-contract.md`.
- Keep one SQLAlchemy Session / one DB transaction per authoritative command unless the protocol explicitly says otherwise.
- External I/O happens before the authoritative transaction or after commit via outbox/compensation. Never await network calls while holding authoritative locks.

## 6. Persistence discipline

PostgreSQL is authoritative, but it is not a stored-procedure application backend.

Do not introduce:

- `BaseRepository.save(entity)` style generic repositories for authoritative transitions;
- arbitrary `update(fields=...)` APIs over business rows;
- table == API resource mapping;
- Pydantic == SQLAlchemy == domain model classes;
- writable business views;
- workflow-sized stored procedures;
- untyped `(entity_type, entity_id)` authority references;
- correctness that depends on ORM lazy-loading order.

Prefer semantic persistence operations such as `lock_request`, `lock_capacity_authorities`, `append_financial_observation`, and explicit SQL/Core for concurrency-sensitive work.

## 7. Database invariants are part of the feature

For changes touching critical state, identify the invariant ID(s) in `docs/02-pre-sql-domain-contract.md` and preserve the enforcement strategy:

- structural truth → FK/UNIQUE/CHECK/EXCLUDE;
- stable authority → row lock / revision;
- multi-root policy → command transaction protocol;
- append-only facts → immutable historical rows + correction lineage.

Do not weaken a database invariant because it is inconvenient in Python.

## 8. Tests expected with changes

Put tests under the owning module in `tests/modules/<module>/` unless the test is truly DB-wide, architecture-wide, or end-to-end.

Critical concurrency behavior requires real PostgreSQL tests; mocks are insufficient for lock ordering, range overlap, transaction isolation, constraints, `SKIP LOCKED`, or privilege behavior.

Useful markers:

- `unit`
- `postgres`
- `integration`
- `concurrency`
- `slow`

Every bug involving a race or invariant should gain a regression test that can fail before the fix.

## 9. Before finishing a change

Run the narrowest relevant checks, then the repository checks when feasible:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

For SQL changes, also follow `migrations/AGENTS.md` and validate against PostgreSQL 18.

Do not claim validation that was not actually run. Report skipped checks and why.

## 10. Documentation expectations

Update documentation when ownership, public module contracts, command protocols, DB surfaces, or invariants change. Do not duplicate the entire architecture in comments or agent files; link to the canonical document and keep local instructions operational.

## 11. Historical archive

`docs/legacy/**` is immutable unless the user explicitly requests an archive edit. Never modernize, move, delete, or implement directly from it.
