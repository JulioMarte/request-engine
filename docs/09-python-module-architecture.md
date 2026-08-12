# Request Engine — Python module architecture

> **Estado:** normativo para la organización física del backend Python durante la transición V3.
>
> Complementa `11-capability-first-v3.md` y `07-database-access-contract.md`. No redefine por sí solo invariantes de dominio o protocolos de locking.

## 1. Decision

Request Engine remains a **modular monolith**, organized **module first, layer second**.

Target transition layout:

```text
src/request_engine/
├── bootstrap/
├── entrypoints/
├── platform/
│   ├── db/
│   ├── idempotency/
│   ├── outbox/
│   ├── audit/
│   ├── events/
│   ├── scheduling/
│   ├── observability/
│   └── security/
└── modules/
    ├── tenancy/
    ├── catalog/
    ├── requests/
    ├── booking/
    ├── queue/
    ├── communications/
    ├── delivery/       # deferred/incubating during V3 transition
    ├── payments/       # deferred/incubating during V3 transition
    └── dispatch/       # deferred/incubating during V3 transition
```

The V3 baseline business modules are:

```text
tenancy
catalog
requests
booking
queue
communications
```

`delivery`, `payments`, and `dispatch` remain physically present during transition only so useful V2 design knowledge is not destroyed prematurely. Baseline modules must not acquire dependencies on those deferred modules. Their eventual archive/reactivation requires an explicit product use case and ownership decision.

This layout is not a microservice split. Modules may share one process, one PostgreSQL database, and one authoritative transaction when a command contract requires it.

## 2. Capability ownership

- `tenancy`: Organization, Principal, Party, Representation and tenant-scoped authority truth.
- `catalog`: Offering, OfferingVersion, structured business/location/service information and reusable offering configuration.
- `requests`: durable business-demand Request, participants/correlations, generic intake and extension-boundary semantics while intake remains small.
- `booking`: Resource, availability, local capacity claims/holds, Reservation and attendance state/policies tightly coupled to reservation operations.
- `queue`: ServiceQueue/QueueEntry plus Waitlist/WaitlistEntry/SlotOffer. Queue and waitlist are distinct domain concepts even while sharing one module.
- `communications`: CommunicationTask, CommunicationDelivery, templates/references, endpoint/preference contracts and ReminderPlan business intent.
- `delivery`: deferred advanced execution/ServiceSession/Fulfillment concepts; not baseline.
- `payments`: deferred pricing/payment/reconciliation domain; not baseline.
- `dispatch`: deferred field-service dispatch/feasibility domain; not baseline.

See `10-module-ownership-map.md` for the detailed map.

## 3. Four application semantics

Application code must make the distinction from `11-capability-first-v3.md` visible:

```text
Query
Command
Request processing
ScheduledAction execution
```

Do not hide all four behind a generic service or workflow abstraction.

Examples:

```text
catalog/application/queries/get_business_info.py
booking/application/queries/find_appointment_slots.py
booking/application/commands/book_appointment.py
booking/application/commands/reschedule_reservation.py
queue/application/commands/join_queue.py
queue/application/commands/accept_slot_offer.py
requests/application/commands/create_request.py
communications/application/commands/record_attendance_response.py
communications/application/commands/create_reminder_plan.py
```

A ScheduledAction worker is technical infrastructure; the business action it invokes remains owned by the appropriate module contract.

## 4. Internal module shape

A module grows structure only as real code requires it:

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

This is a growth shape, not scaffolding to generate eagerly. A young module may remain a small set of cohesive files.

Use these meanings consistently:

- `domain`: framework-independent business rules/types/events/policies owned by the module;
- `application`: use-case orchestration and required ports;
- `adapters/db`: SQLAlchemy mappings, PostgreSQL repositories/query adapters and correctness-sensitive SQL;
- `adapters/providers`: external provider implementations/SDK boundaries;
- `api`: module-owned transport DTOs/router composition;
- `contracts`: intentionally supported cross-module types/query/command contracts.

Avoid giant generic files such as `services.py`, `managers.py`, `helpers.py`, `utils.py`, `common.py`, or a universal `repositories.py`.

## 5. Command-oriented application layer

Authoritative lifecycle changes are semantic commands. Critical commands follow the documented pattern:

```text
READ / PLAN / LOCK / VALIDATE / WRITE / EMIT
```

Examples:

```text
booking/application/commands/book_appointment.py
booking/application/commands/reschedule_reservation.py
queue/application/commands/call_next.py
queue/application/commands/accept_slot_offer.py
communications/application/commands/record_delivery_result.py
```

The implementation may be a typed function or small handler object. Do not introduce ceremonial Service/Manager/Coordinator layers.

Commands such as cancel/reschedule are not wrapped in `Request` merely for consistency with the project name.

## 6. Ports and adapters

Application/domain code defines the capability it requires; technical implementations live in adapters.

```text
api / provider adapter
        ↓
application
        ↓
domain + application ports
        ↑
adapters/db + adapters/providers
```

Repository ports are semantic, not generic CRUD. SQLAlchemy Session/AsyncSession is already the technical Unit of Work; do not create a universal abstract UoW hierarchy without a demonstrated need.

Provider adapters must not own authoritative booking/request/queue state.

## 7. n8n boundary

n8n is an external extension/orchestration adapter.

Preferred direction:

```text
Request Engine transaction
  → outbox event
  → n8n/provider
  → authenticated semantic callback command
  → Request Engine transaction
```

Forbidden:

```text
n8n → direct PostgreSQL mutation
n8n → generic set_status endpoint
provider call while Request Engine lock transaction remains open
```

An experimental flow may later be promoted into a native module without changing the public capability contract.

## 8. Cross-module imports

A module may use another module only through the target module's supported `contracts` package or another explicitly documented public transition surface.

Preferred:

```python
from request_engine.modules.booking.contracts import ReservationId
```

Forbidden across modules:

```python
from request_engine.modules.booking.domain.reservation import Reservation
from request_engine.modules.booking.application.commands.book_appointment import handle
from request_engine.modules.booking.adapters.db.models import ReservationRow
from request_engine.modules.booking.api.responses import ReservationResponse
```

Deferred modules are especially restricted: V3 baseline modules must not depend on `delivery`, `payments`, or `dispatch` without a new accepted architecture decision.

SQLAlchemy mappings, API DTOs and internal domain entities are not cross-module contracts.

## 9. Internal dependency direction

Domain does not import FastAPI, SQLAlchemy, provider SDKs, bootstrap, runtime settings or API DTOs.

Application does not depend on FastAPI or concrete provider/DB adapters. Adapter implementations may depend inward on application ports/contracts and domain types.

API/Pydantic DTOs, domain objects and persistence mappings remain separate concepts even when fields currently look identical.

## 10. Platform boundary

`platform/` is only for genuinely cross-cutting technical capabilities:

```text
platform/db
platform/idempotency
platform/outbox
platform/audit
platform/events
platform/scheduling
platform/observability
platform/security
```

`platform/scheduling` owns generic technical mechanics such as clock abstraction, lease/fencing, worker claiming, retry/dead-letter plumbing and scheduling-lag telemetry. It does **not** decide why a reservation reminder, SlotOffer expiry or medication reminder exists.

Business policy remains in the owning module.

`platform` must not import business-module internals.

## 11. Entrypoints and bootstrap

- `entrypoints/http`: FastAPI process adapter, middleware, dependency extraction, error translation and router registration; no business commands.
- `entrypoints/worker`: outbox/scheduler/communication worker startup/runtime; business semantics remain in module contracts.
- `entrypoints/cli`: explicit operational/developer commands.
- `bootstrap`: composition root, settings and dependency wiring. Business code never imports bootstrap as a service locator.

## 12. Persistence and PostgreSQL

Keep the valid decisions in `07-database-access-contract.md`:

- one task-local Session/AsyncSession per authoritative command;
- explicit transaction framing;
- ORM for ordinary persistence;
- SQLAlchemy Core/explicit SQL for correctness-sensitive locking/range/batch operations;
- never hide race-critical SQL behind generic repositories;
- no external I/O while authoritative locks are held.

V3 will replace the broad V2 pre-baseline schema with a reduced clean candidate after the domain contracts settle; physical Python modules must not assume every V2 table survives.

## 13. Queries and agent-facing surfaces

Queries belong to the owner of the read concept and return use-case DTOs rather than table-shaped entities.

Examples:

```text
business.get_info → catalog
catalog.search_offerings → catalog
appointments.find_slots → booking
appointments.status → booking
queue.status → queue
waitlist.status → queue
requests.status → requests
```

Agent/tool APIs are capability-oriented. Internal rows such as CapacityClaim or outbox records are not agent-facing tools.

## 14. `request_cmd` and DB primitive ownership

PostgreSQL functions may remain physically centralized, but wrappers belong to the logical owner.

Expected V3 examples:

```text
capacity-source locking → booking
idempotency acquisition/completion → platform/idempotency
outbox claiming/delivery → platform/outbox
scheduled-action claiming/fencing → platform/scheduling
```

Do not create a global business `db_commands.py`.

## 15. Tests

Tests are organized first by capability:

```text
tests/modules/<module>/
tests/db/
tests/architecture/
tests/integration/
tests/e2e/
tests/fixtures/
```

Critical race tests use real PostgreSQL.

V3 minimum race families:

- booking double-booking/unit oversell/self-overlap reschedule;
- queue concurrent CallNext;
- SlotOffer accept/expiry/capacity races;
- scheduled-action leases/fencing/dead-letter;
- communication duplicate/provider-timeout/callback behavior;
- n8n callback idempotency/tenant/authority races.

Architecture tests enforce framework independence, platform isolation, cross-module contracts and deferred-module dependency restrictions.

## 16. Cross-module atomicity

A cross-module use case has one primary command owner. It may coordinate supported contracts of other modules inside the same PostgreSQL transaction when the domain invariant requires it.

Do not split a correct local transaction into asynchronous events merely to make module boundaries look cleaner.

Conversely, external provider/n8n communication is never made artificially atomic with PostgreSQL.

## 17. New-module gate

A new top-level module requires:

- meaningful independent language/policy/lifecycle;
- a stable public boundary;
- enough independent change to justify separate ownership.

A table, noun, endpoint, worker or provider integration alone is insufficient.

An intake capability stays in `requests` until it demonstrates enough independent behavior to justify `intake/`.

## 18. Goal

A human or coding agent should be able to locate a business capability and find nearby its commands, rules, ports, DB/provider adapters, API adapter, tests and ownership documentation.

The repository should encode the V3 north star:

```text
one public operational API
        ≠
one universal domain model
```
