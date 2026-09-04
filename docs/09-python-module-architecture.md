# Request Engine — Python module architecture

> **Estado:** normativo para la organización física actual del backend Python.
>
> Complementa `10-module-ownership-map.md`, `07-database-access-contract.md`, `13-connection-surfaces.md`, `14-architecture-fitness-functions.md` y `architecture/system-optimization-mode.md`. No redefine por sí solo invariantes de dominio, autoridad o locking.

## 1. Decision

Request Engine is a **modular monolith**, organized **module first, layer second**.

Current top-level shape:

```text
src/request_engine/
├── bootstrap/       # composition/settings only
├── entrypoints/     # process/trust boundaries
├── platform/        # technical cross-cutting mechanics
└── modules/         # business ownership
```

Current business-module inventory:

```text
tenancy
catalog
requests
booking
queue
communications
discovery
delivery
live_capacity
operational_recovery
operational_copilot
payments
dispatch
```

`payments` and `dispatch` remain deferred/incubating until a concrete accepted capability gives them real ownership. `delivery` is active current architecture; it owns ReservationAccess and actual execution facts such as ServiceSession/ResourceActivity according to `10-module-ownership-map.md`.

The names `operational_copilot`, V3 and F1–F7 are historical naming/provenance where applicable. They do not create a separate architectural layer or freeze the module inventory. Module ownership may evolve deliberately under `architecture/system-optimization-mode.md` while preserving HARD guarantees.

This is not a microservice split. Modules may share one process, one PostgreSQL database and one authoritative transaction when a command invariant requires it.

## 2. Current capability ownership summary

Detailed ownership lives in `10-module-ownership-map.md`; this section is only a navigation summary.

- `tenancy`: Organization, Principal, Party, Representation and tenant/subject authority truth.
- `catalog`: Location/Offering/OfferingVersion and reusable service/capability vocabulary/configuration.
- `requests`: durable new business demand requiring later processing.
- `booking`: Resource planning, contextual supply, availability, CapacityHold/CapacityClaim, Reservation and booking commitment/revalidation.
- `queue`: ServiceQueue/QueueEntry waiting/calling/no-show plus Waitlist/SlotOpportunity/SlotOffer recovery interest.
- `communications`: transactional communication intent, delivery facts, reminder/acknowledgement semantics.
- `discovery`: explicitly published cross-tenant supply projection and opaque Booking handoff.
- `delivery`: ReservationAccess and actual live service/execution truth.
- `live_capacity`: advisory live-capacity/ETA/intake projection over published owner facts.
- `operational_recovery`: immutable recovery proposal/execution composition over owner contracts.
- `operational_copilot`: bounded typed external operational-tool/admission surface; owns no underlying business truth or conversational runtime.
- `payments`: deferred/incubating.
- `dispatch`: deferred/incubating.

Do not duplicate detailed ownership rules here. When this summary and `10-module-ownership-map.md` disagree, fix the current documentation defect rather than inventing a third interpretation.

## 3. Application semantics

Application code makes semantic operation kind explicit:

```text
Query
Command
Request processing
ScheduledAction execution
```

Do not hide all four behind a universal `Service`, `Manager`, `Workflow` or generic command bus.

- Query = read/derivation without mutation authority.
- Command = explicit semantic mutation/use case.
- Request = durable new business demand requiring later processing, not a wrapper for every mutation.
- ScheduledAction = durable technical scheduling/execution envelope; business action remains owned by its module.

## 4. Internal module growth shape

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

This is a growth shape, not scaffolding to generate eagerly. A young module may remain a smaller cohesive set of files.

Meanings:

- `domain`: framework-independent business rules/types/events/policies owned by the module;
- `application`: use-case orchestration and required ports;
- `adapters/db`: persistence mappings, PostgreSQL queries/commands and correctness-sensitive SQL;
- `adapters/providers`: external provider implementations/SDK boundaries;
- `api`: module-owned transport DTOs/router composition;
- `contracts`: intentionally published cross-module values/protocols.

Avoid generic business dumping grounds such as `services.py`, `managers.py`, `helpers.py`, `utils.py`, `common.py`, universal repositories or shared business-model buckets.

File count and LOC are not design targets. Split only when responsibility/ownership/reason-to-change genuinely separates; preserve locality when behavior belongs together.

## 5. Command-oriented application layer

Authoritative lifecycle changes are semantic commands. Correctness-sensitive commands normally make the protocol visible:

```text
READ / PLAN / LOCK / VALIDATE / WRITE / EMIT
```

The implementation may be a typed function or a small handler object. Do not introduce ceremonial layers merely to reduce file size or satisfy a metric.

A semantic command may coordinate multiple modules in one database transaction when a current invariant requires atomicity; architecture aesthetics do not justify breaking required consistency.

## 6. Ports and adapters

Application/domain code defines the capability it requires; technical implementations live outward in adapters.

```text
api / provider adapter
        ↓
application
        ↓
domain + application ports
        ↑
adapters/db + adapters/providers
```

Repository ports are semantic rather than generic CRUD. SQLAlchemy Session/AsyncSession is already technical transaction/UoW machinery; do not create a universal abstract UoW hierarchy without demonstrated value.

Provider adapters do not own authoritative business state.

## 7. Cross-module imports

A module may use another business module only through the target module's supported `contracts` package and an approved dependency direction.

Preferred:

```python
from request_engine.modules.booking.contracts import ReservationId
```

Forbidden across modules:

```python
from request_engine.modules.booking.domain.reservation import Reservation
from request_engine.modules.booking.application.commands.book_appointment import handle
from request_engine.modules.booking.adapters.db.models import ReservationRow
from request_engine.modules.booking.api.responses import ReservationView
```

`contracts` does not automatically authorize an edge. The current permission map is documented in `14-architecture-fitness-functions.md` and executed by `tests/architecture/dependency_policy.py`.

Do not hide a dependency from the graph with service locators, runtime imports, generic shared helpers or re-export facades.

## 8. Internal dependency direction

Domain does not import FastAPI, SQLAlchemy/persistence drivers, provider SDKs, bootstrap, runtime settings or API DTOs.

Application does not depend on FastAPI, concrete provider/DB adapters, bootstrap or transport DTOs.

Adapters may depend inward on application ports/contracts/domain values as appropriate.

API/Pydantic DTOs, application Commands/Queries, domain objects, cross-module contracts and persistence mappings remain distinct concepts even when fields currently match.

## 9. Platform boundary

`platform/` contains genuinely cross-cutting technical mechanics only, for example:

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

Platform may own clock/lease/fencing/retry/dead-letter/telemetry mechanics. It does not own why a Reservation, QueueEntry, recovery proposal, reminder or discovery publication exists.

Do not move business logic into `platform`, `shared`, `common` or generic helpers to reduce measured module coupling.

## 10. Entrypoints and bootstrap

- `entrypoints/http`: process/trust adapter, middleware, authentication extraction, global exception handling and module router installation; not a parallel business taxonomy.
- `entrypoints/worker`: worker process startup/runtime; business semantics remain owned by modules.
- `entrypoints/cli`: explicit operational/developer process commands.
- `bootstrap`: settings and composition root; business code never imports it as a service locator.

Cross-domain business policy discovered in composition code must receive an explicit business owner rather than remaining hidden there for graph aesthetics.

## 11. Persistence and PostgreSQL

Keep the current decisions in `07-database-access-contract.md`:

- one task-local Session/AsyncSession per authoritative command by default;
- explicit transaction framing;
- ORM/normal persistence where appropriate;
- SQLAlchemy Core/explicit SQL for correctness-sensitive locking/range/batch operations;
- never hide race-critical SQL behind generic repositories;
- no external/provider I/O while authoritative DB locks are held.

Schema shape itself is CONTROLLED and evolvable during `cohesion/system-optimization`; tenant/authority/atomicity/capacity/provenance/concurrency guarantees remain HARD unless replaced by an equal-or-stronger explicit contract.

## 12. Maintainability and evolution

Architecture fitness functions protect ownership/direction, not arbitrary smallness.

LOC, C901, navigation observations and fan-in/fan-out are non-blocking review signals. `HEALTHY_AS_IS` is valid. Never split a cohesive file, create forwarding modules or hide dependencies solely to make a metric smaller.

The current module inventory and approved edges are CONTROLLED rather than immutable. Intentional evolution requires updating:

```text
current capability/ownership contract
10-module-ownership-map.md
13-connection-surfaces.md when boundary semantics change
14-architecture-fitness-functions.md + executable policy/tests
current guarantee/evidence disposition where affected
```

and exact-head proof.
