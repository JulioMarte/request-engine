# Request Engine — architecture fitness functions

> **Estado:** normativo para las reglas estructurales ejecutables del backend V3.
>
> Este documento complementa `09-python-module-architecture.md`,
> `10-module-ownership-map.md` y `13-connection-surfaces.md`. Los tests de
> `tests/architecture/` hacen cumplir estas reglas; no sustituyen los contratos
> de dominio/transacción.

## 1. Purpose

Request Engine treats architecture as an executable constraint, not only a diagram.

The repository protects three things simultaneously:

```text
horizontal responsibility
+ vertical business ownership
+ explicit connection surfaces
```

A change may compile, pass feature tests and still be architecturally invalid if it
crosses a boundary through an unsupported surface.

Architecture fitness functions exist to detect that drift immediately, especially
when code is produced or refactored by coding agents.

## 2. Cross-module rule

A business module may depend synchronously on another business module only when both
conditions are true:

1. the dependency direction is explicitly approved because a current vertical needs it;
2. the import uses the target module's published `contracts` surface.

Example after such an edge has actually been accepted:

```text
queue -> booking.contracts        allowed
queue -> booking.domain           forbidden
queue -> booking.application      forbidden
queue -> booking.adapters         forbidden
queue -> booking.api              forbidden
```

`contracts` is not universal permission. The module-to-module edge itself must also
be approved.

A relational FK between data owned by two modules is **not** a Python module dependency. Shared-database referential integrity, semantic Python calls and direct mutation of another module's rows are reviewed as three different connection surfaces.

## 3. Approved synchronous Python dependency directions

The current policy starts with **zero speculative business-module edges**:

| Owner | Approved synchronous Python targets |
|---|---|
| `tenancy` | none |
| `catalog` | none |
| `requests` | none |
| `booking` | none |
| `queue` | none |
| `communications` | none |
| deferred modules | none |

This does **not** claim the modules never collaborate. Current collaboration may occur through:

- tenant-safe relational integrity in the shared PostgreSQL model;
- immutable IDs/contracts carried into a module command;
- outbox/event consequences after commit;
- provider/integration callbacks;
- a future explicitly accepted synchronous `contracts` edge.

The allowlist is evidence, not a roadmap. A plausible future dependency such as
`queue -> booking` for atomic `AcceptSlotOffer` is intentionally **not** pre-approved.
It must be introduced by the vertical that proves why the dependency is necessary and
what exact contract participates in the shared local transaction.

Adding a new edge requires an architectural decision, not a mechanical test edit.
Before adding it, answer:

```text
Who owns the capability?
Why must the dependency be synchronous?
What exact contract crosses the boundary?
Does the caller require immediate consistency?
Would an outbox/event surface preserve ownership better?
Could the same invariant be enforced by a tenant-safe FK instead?
Could this edge create a dependency cycle?
What transaction/lock context crosses the boundary, if any?
```

Update ownership/connection-surface documentation when the answer changes the
accepted architecture.

The fitness test also rejects **unused pre-approved edges**. This prevents the
allowlist from becoming a wish list that silently grants future coupling.

## 4. Dependency cycles are forbidden

The actual Python business-module dependency graph must remain acyclic.

Forbidden:

```text
booking -> queue -> booking
```

A cycle normally indicates at least one of:

- ownership is wrong;
- a consumer is reaching into another module instead of consuming a fact;
- a missing one-way contract needs to be designed;
- two concepts are not actually separate bounded contexts.

Do not solve cycles with a shared business `common` package or service locator.

## 5. Layer fitness rules

### Domain

`modules/<owner>/domain` must not depend on:

- FastAPI;
- SQLAlchemy/asyncpg/psycopg;
- bootstrap or entrypoints;
- the module's application layer;
- the module's adapters;
- the module's API transport.

Domain code contains business policy/value semantics, not framework plumbing.

### Application

`modules/<owner>/application` must not depend on:

- FastAPI or persistence drivers/ORM;
- bootstrap/entrypoints;
- the module's concrete adapters;
- the module's API transport.

Application defines/uses semantic Commands, Queries and `Protocol` ports.

A thin application function is not automatically a defect. For a correctness-sensitive
PostgreSQL command, a concrete adapter may be a **deep transactional executor** that
keeps lock/revalidation/write/audit/outbox mechanics cohesive inside one DB transaction.
Do not split such a protocol into Repository/UoW ceremony merely to make the application
layer look thicker. Move only framework-independent business policy outward when doing
so actually reduces knowledge/coupling.

### Contracts

`modules/<owner>/contracts` is a published connection surface. It must remain
framework-free and dependency-light. It must not re-export the owner module's domain,
application, adapter or API internals.

If another module needs a concept, map the smallest stable representation into the
contract instead of exposing an internal entity/repository/transport DTO.

Stable public capability IDs may live on a module contract surface. Authorization
permission strings are separate semantics and may differ from capability IDs.

### Database adapters

`modules/<owner>/adapters/db` may know persistence infrastructure but must not depend
on FastAPI, module HTTP DTOs or process entrypoints.

The mapping direction is:

```text
PostgreSQL row/result
    -> DB adapter
    -> application/domain/contract value
    -> transport mapper
    -> HTTP DTO
```

Never `DB adapter -> HTTP DTO`.

Database adapters may implement a complete data-centric semantic transaction protocol.
They still may not own external I/O, transport policy, or another module's arbitrary
state mutation.

## 6. HTTP composition fitness rule

A module HTTP router is an inbound adapter and must be typed against application
surfaces, not concrete PostgreSQL implementations.

Correct:

```text
modules/booking/api/router.py
        |
        | AppointmentAvailabilityReader / BookAppointmentHandler / ...
        v
booking application
```

Concrete construction is allowed only at the module-owned installation/composition
surface:

```text
entrypoints/http/app.py
        |
        | booking.api.install_http(...)
        v
modules/booking/api/__init__.py
        |
        | construct Postgres... adapters
        v
router typed against application Protocols
```

This keeps `entrypoints/http` ignorant of module internals while also keeping the
router ignorant of persistence implementation.

## 7. Capability identity fitness

`docs/v3/capability-manifest.toml` is the machine-readable registry for the current
pre-baseline capability surface.

It distinguishes:

```text
capability id      semantic operation exposed/discovered by machines
permission         authorization requirement for a Principal
status             implemented vs contract-only proof state
semantic           Query / Command / Request / ScheduledAction category
```

A capability ID is not generated from a function/class/table name. Refactoring an
implementation must not silently change a durable public identity.

Architecture tests reject duplicate/unknown capability metadata and prevent
`freeze_ready = true` while freeze-critical coordination verticals remain contract-only.

## 8. What the tests enforce

`tests/architecture/test_connection_surfaces.py` protects the process/module HTTP
boundary.

`tests/architecture/test_dependency_policy.py` protects:

- cross-module imports through `contracts` only;
- evidence-based module dependency direction;
- no speculative unused dependency permissions;
- acyclic module graph;
- domain inward dependency direction;
- application separation from adapters/transport;
- HTTP router separation from concrete adapters;
- dependency-light public contracts;
- persistence separation from HTTP transport.

`tests/architecture/test_capability_manifest.py` protects:

- stable/unique capability identities;
- known baseline ownership and interaction semantics;
- explicit permission metadata;
- the prohibition on external I/O inside authoritative transactions;
- critical proof gates before schema freeze.

`tests/architecture/test_repository_structure.py` continues to protect baseline
module ownership, platform purity, no global horizontal business roots, deferred
module isolation and other repository-level rules.

These tests are **fitness functions**, not business correctness tests. PostgreSQL
race/invariant tests, unit tests and HTTP integration tests remain independently
required.

## 9. Failure messages are part of the agent interface

Architecture-test failures should explain:

```text
what boundary was crossed
which file/import crossed it
what surface is allowed
what design question must be answered before changing the policy
```

A coding agent must not respond to an architecture failure by:

- widening an allowlist automatically;
- pre-approving a plausible future edge;
- moving business code into `platform`/`common`/`shared`;
- exporting domain or adapter internals through `contracts`;
- adding an event solely to avoid a valid synchronous transaction;
- suppressing or deleting the fitness test;
- setting `freeze_ready = true` merely because SQL/tests compile.

The correct response is to reconsider the connection surface first.

## 10. Architecture change gate

Changing an approved dependency direction or public surface requires, as applicable:

1. update `10-module-ownership-map.md`;
2. update `13-connection-surfaces.md`;
3. update `v3/capability-manifest.toml` when capability/permission/proof semantics change;
4. update this executable policy/test;
5. update affected module READMEs/contracts;
6. add/update integration and concurrency tests when semantics change;
7. add an ADR when the dependency/ownership decision is hard to reverse.
