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

`01-architecture-v2.md` describes logical dependency direction. This document is authoritative for Python physical organization.

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

A module grows structure only as real code requires it. The target vocabulary is:

```text
modules/<module>/
├── domain/
├── application/
│   ├── commands/
│   ├── queries/
│   └── ports/
├── adapters/
│   ├── db/
│   └── providers/
├── api/
├── contracts/
└── README.md
```

This is a growth shape, not scaffolding to generate eagerly. A young module may remain a handful of cohesive files. Do not create ceremonial empty Clean Architecture directories.

Use these names consistently:

- `domain`: framework-independent business rules/types/events/policies owned by the module;
- `application`: use-case orchestration, commands, queries and the ports those use cases require;
- `adapters/db`: SQLAlchemy mappings, PostgreSQL repositories/query adapters and explicit SQL owned by the module;
- `adapters/providers`: external provider implementations/SDK boundaries;
- `api`: module-owned transport DTOs/router composition for HTTP exposure;
- `contracts`: intentionally supported cross-module types/query/command contracts.

`persistence/` is not the target module bucket. Database persistence is one adapter family and lives under `adapters/db/` once the split is useful.

Avoid giant generic files such as `services.py`, `managers.py`, `helpers.py`, `utils.py`, `common.py`, or one global `repositories.py`. Prefer cohesion by use case/capability and split only when a file becomes meaningfully multi-purpose.

## 4. Command-oriented application layer

Authoritative lifecycle changes are semantic commands. Prefer one obvious command file per use case:

```text
booking/application/commands/confirm_reservation.py
delivery/application/commands/correct_fulfillment.py
payments/application/commands/allocate_payment.py
```

Each critical command implements the documented `READ / PLAN / LOCK / VALIDATE / WRITE / EMIT` protocol and canonical lock order.

The implementation may be a typed function or a small handler object. Do not introduce `Service`/`Manager`/`Coordinator` layers merely to imitate enterprise OO patterns.

## 5. Ports and adapters

Application/domain code defines the capability it requires; technical implementations live in adapters.

Conceptually:

```text
api / provider adapter
        ↓
application
        ↓
domain + application ports
        ↑
adapters/db + adapters/providers
```

A repository port should be semantic, not generic CRUD. Do not create abstraction layers whose only purpose is to wrap SQLAlchemy method-for-method.

SQLAlchemy `Session`/`AsyncSession` already provides the technical Unit of Work. Do not add a universal abstract UoW hierarchy until a demonstrated need exists beyond explicit transaction/session framing.

## 6. Cross-module imports

A module may use another module only through the target module's supported `contracts` package or another surface explicitly documented as public during migration.

Preferred:

```python
from request_engine.modules.booking.contracts import ReservationId
```

Forbidden across modules:

```python
from request_engine.modules.booking.domain.reservation import Reservation
from request_engine.modules.booking.application.commands.confirm_reservation import handle
from request_engine.modules.booking.adapters.db.models import ReservationRow
from request_engine.modules.booking.api.responses import ReservationResponse
```

SQLAlchemy mappings, API/Pydantic DTOs and internal domain entities are never cross-module contracts. If two modules repeatedly require each other's internals, reconsider ownership instead of creating circular imports.

`contracts/` must remain intentional and small; it is not a shared-model dumping ground.

## 7. Internal dependency direction

Domain does not import FastAPI, SQLAlchemy, provider SDKs, bootstrap, runtime settings or API DTOs.

Application does not depend on FastAPI or concrete provider/DB adapters. Adapter implementations may depend inward on application ports/contracts and domain types.

API/Pydantic DTOs, domain objects and persistence mappings remain separate concepts even when fields currently look identical.

## 8. Platform boundary

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

If a capability contains business vocabulary/rules from one module, it belongs to that module. `platform`, `common`, `shared`, `utils` and `helpers` are not dumping grounds.

Examples:

- `AsyncSessionFactory`, PostgreSQL error classification and technical transaction plumbing → `platform/db`;
- reservation-specific lock planning → `modules/booking`;
- authentication/token parsing → `platform/security`;
- Representation/delegation/revocation policy → `modules/tenancy`.

`platform` must not import business-module internals.

## 9. Entrypoints and bootstrap

- `entrypoints/http`: FastAPI process adapter, middleware, dependency extraction, error translation and router registration; no business commands. Feature routers/DTOs stay with their owning module.
- `entrypoints/worker`: worker process startup/runtime; job semantics remain with the owning module/platform capability.
- `entrypoints/cli`: explicit operational/developer process commands when introduced.
- `bootstrap`: composition root, settings and dependency wiring. Business code never imports bootstrap as a service locator.

Runtime settings live under `bootstrap/` because they belong to process composition, not the package/domain root.

## 10. Persistence and PostgreSQL

Keep the decisions in `07-database-access-contract.md`.

Use ORM for ordinary row loading/inserts/typed relationships. Prefer SQLAlchemy Core or explicit SQL for `FOR UPDATE`, canonical multi-row locks, range operators, `SKIP LOCKED`, aggregate concurrency checks, bulk worker operations and `request_cmd.*` primitives.

Do not hide correctness-sensitive SQL behind a generic repository abstraction.

Within a sufficiently large module, prefer cohesive DB adapters such as:

```text
booking/adapters/db/
├── capacity_repository.py
├── reservation_repository.py
├── reservation_queries.py
└── statements/
```

rather than one repository per table or one repository for the entire module. Database table boundaries do not automatically define domain/repository boundaries.

Each authoritative command gets a task-local Session/AsyncSession and one explicit transaction unless its protocol says otherwise. Do not share AsyncSession across concurrent tasks. Critical command paths should use explicit transaction framing and may disable autobegin to prevent accidental DB work outside the UoW.

## 11. Queries

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

## 12. `request_cmd` Python ownership

PostgreSQL functions remain physically centralized but wrappers live with the logical owner:

```text
lock_capacity_authorities / advance_planning_revision → booking
acquire_idempotency / complete_idempotency → platform/idempotency
claim_outbox_batch / mark_outbox_delivered / release_outbox_claim → platform/outbox
```

Do not create a global `db_commands.py` that erases semantic ownership.

## 13. Tests

Tests are organized first by capability:

```text
tests/modules/<module>/
tests/db/
tests/architecture/
tests/integration/
tests/e2e/
tests/fixtures/
```

Test type is expressed with pytest markers (`unit`, `postgres`, `integration`, `concurrency`, `slow`). Critical lock/constraint/race tests use real PostgreSQL.

Do not mechanically mirror every production subdirectory inside `tests/modules/<module>/`; organize tests around behavior/use cases unless scale requires further grouping.

Architecture tests must enforce import boundaries in addition to repository shape: domain framework independence, `platform` isolation and cross-module public-contract-only imports.

## 14. Cross-module atomicity

A cross-module use case still has one primary command owner. It may coordinate supported contracts/ports of other modules inside the same DB transaction when required by the domain contract.

Do not split a correct authoritative transaction into asynchronous events merely to make module boundaries look cleaner.

## 15. New-module gate

A new top-level module requires meaningful independent language/policy/lifecycle, a stable public boundary and enough independent change to justify separate ownership. A table, noun, endpoint, worker or provider integration alone is insufficient.

Material module-boundary changes update `10-module-ownership-map.md`, module READMEs, architecture tests and an ADR when the decision is hard to reverse.

## 16. Goal

A human or coding agent should be able to locate a business capability and find nearby its commands, rules, ports, DB/provider adapters, API adapter, tests and ownership documentation without traversing unrelated global layer trees. The repository should make the correct dependency direction easier than the incorrect one.
