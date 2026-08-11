# Request Engine — Python module architecture

> **Estado:** normativo para la organización física del backend Python.
>
> Complementa `01-architecture-v2.md` y `07-database-access-contract.md`. No redefine invariantes de dominio ni protocolos de locking.

## 1. Decision

Request Engine remains a modular monolith, but Python is organized **module first, layer second**:

```text
src/request_engine/
├── bootstrap/
├── entrypoints/
├── platform/
└── modules/
    ├── tenancy/
    ├── catalog/
    ├── requests/
    ├── booking/
    ├── delivery/
    ├── payments/
    └── dispatch/
```

The former global horizontal `domain/`, `application/`, `infrastructure/`, `api/`, and business-logic `workers/` trees are not the target physical layout because they scatter one feature across the repository.

This is an ownership/navigation change, not a microservice split. Modules may share one process, one PostgreSQL database, and one authoritative transaction when the command contract requires it.

## 2. Initial module ownership

- `tenancy`: Organization, Principal, Party, Representation.
- `catalog`: Offering, OfferingVersion, reusable offering configuration and ResourceRequirementTemplate definition.
- `requests`: Request, participants/targets/correlations, OfferingSelection, OutcomeScope, workflow selection/version and completion coordination.
- `booking`: resources/capabilities, schedules/location eligibility, pools, capacity authorities/claims, holds, reservations, commitment requirements, allocations and external commitment dependencies.
- `delivery`: admission/queue/waitlist, ServiceSession, Fulfillment and FulfillmentCorrection.
- `payments`: pricing, requirements, transactions, observations/corrections/reversals, allocations/adjustments, refunds, disputes and reconciliation.
- `dispatch`: field-service Dispatch lifecycle, destination lineage and dispatch-specific feasibility semantics. Shared capacity/planning authority remains in booking.

See `10-module-ownership-map.md` for the detailed map.

## 3. Internal module shape

A module may grow this shape **only as real code requires it**:

```text
modules/<module>/
├── domain/
├── application/
│   ├── commands/
│   └── queries/
├── persistence/
├── integrations/
├── api/
├── contracts.py
├── facade.py
└── README.md
```

Do not generate ceremonial empty Clean Architecture directories. Prefer a cohesive `domain/entities.py` until real growth justifies splitting it.

## 4. Command-oriented application layer

Authoritative lifecycle changes are semantic commands. Prefer one obvious command file per use case:

```text
booking/application/commands/confirm_reservation.py
delivery/application/commands/correct_fulfillment.py
payments/application/commands/allocate_payment.py
```

Each critical command implements the documented `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` protocol and canonical lock order.

Avoid catch-all `services.py`, `managers.py`, `helpers.py`, `utils.py`, or giant `commands.py` files.

## 5. Cross-module imports

A module may use another module only through a supported public surface such as `contracts.py`, `facade.py`, or an explicitly exported application contract.

Allowed conceptually:

```python
from request_engine.modules.booking.contracts import ReservationId
```

Forbidden across modules:

```python
from request_engine.modules.booking.persistence.models import ReservationRow
```

SQLAlchemy mappings are never cross-module domain contracts. If two modules need each other's internals, reconsider ownership instead of creating circular imports.

## 6. Internal dependency direction

Conceptually:

```text
api / integration / process adapter
              ↓
         application
              ↓
            domain
```

Persistence implements explicit ports required by application/domain and is wired by the composition root. Domain does not import FastAPI, SQLAlchemy, provider SDKs, or bootstrap.

API/Pydantic DTOs, domain objects, and persistence mappings remain separate concepts.

## 7. Platform boundary

`platform/` is only for genuinely cross-cutting technical capabilities:

```text
platform/db
platform/idempotency
platform/outbox
platform/audit
platform/events
platform/observability
platform/security
```

If a capability contains business vocabulary/rules from one module, it belongs to that module. `platform`, `common`, `shared`, `utils`, and `helpers` are not dumping grounds.

## 8. Entrypoints and bootstrap

- `entrypoints/http`: FastAPI process adapter, middleware, dependency extraction, error translation and router registration; no business commands.
- `entrypoints/worker`: worker process startup/runtime; job semantics remain with the owning module/platform capability.
- `entrypoints/cli`: explicit operational/developer commands when introduced.
- `bootstrap`: composition root and dependency wiring. Business code never imports bootstrap as a service locator.

## 9. Persistence

Keep the decisions in `07-database-access-contract.md`:

Use ORM for ordinary row loading/inserts/typed relationships. Prefer SQLAlchemy Core or explicit SQL for `FOR UPDATE`, canonical multi-row locks, range operators, `SKIP LOCKED`, aggregate concurrency checks, bulk worker operations, and `request_cmd.*` primitives.

Do not hide correctness-sensitive SQL behind a generic repository abstraction.

Each authoritative command gets a task-local Session/AsyncSession and one explicit transaction unless its protocol says otherwise. Do not share AsyncSession across concurrent tasks. Critical command paths should use explicit transaction framing and may disable autobegin to prevent accidental DB work outside the UoW.

## 10. Queries

Query Services belong to the owner of the read concept and prefer `request_read.*` when a stable read contract exists:

```text
request_read.request_summary_v1 → requests
request_read.reservation_summary_v1 → booking
request_read.external_commitment_status_v1 → booking
request_read.queue_entry_status_v1 → delivery
request_read.payment_requirement_status_v1 → payments
request_read.payment_transaction_status_v1 → payments
```

Read DTOs are optimized for the use case and need not mirror tables or aggregates.

## 11. `request_cmd` Python ownership

PostgreSQL functions remain physically centralized but wrappers live with the logical owner:

```text
lock_capacity_authorities / advance_planning_revision → booking
acquire_idempotency / complete_idempotency → platform/idempotency
claim_outbox_batch / mark_outbox_delivered / release_outbox_claim → platform/outbox
```

Do not create a global `db_commands.py` that erases semantic ownership.

## 12. Tests

Tests are organized first by capability:

```text
tests/modules/<module>/
tests/db/
tests/architecture/
tests/e2e/
tests/fixtures/
```

Test type is expressed with pytest markers (`unit`, `postgres`, `integration`, `concurrency`, `slow`). Critical lock/constraint/race tests use real PostgreSQL.

Architecture tests should eventually enforce module import boundaries and prevent domain → framework imports.

## 13. Cross-module atomicity

A cross-module use case still has one primary command owner. It may coordinate public contracts/ports of other modules inside the same DB transaction when required by the domain contract.

Do not split a correct authoritative transaction into asynchronous events merely to make module boundaries look cleaner.

## 14. New-module gate

A new top-level module requires meaningful independent language/policy/lifecycle, a stable public boundary, and enough independent change to justify separate ownership. A table, noun, endpoint, or provider integration alone is insufficient.

Material module-boundary changes update `10-module-ownership-map.md`, module READMEs, architecture tests, and preferably an ADR.

## 15. Goal

A human or coding agent should be able to locate a business capability and find nearby its commands, rules, persistence, integration adapters, API adapter, tests, and ownership documentation without traversing unrelated global layer trees.
