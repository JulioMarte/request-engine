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

A business module may depend on another business module only when both conditions
are true:

1. the dependency direction is explicitly approved;
2. the import uses the target module's published `contracts` surface.

Example:

```text
booking -> catalog.contracts        allowed
booking -> catalog.domain           forbidden
booking -> catalog.application      forbidden
booking -> catalog.adapters         forbidden
booking -> catalog.api              forbidden
```

`contracts` is not universal permission. The module-to-module edge itself must also
be approved.

## 3. Approved synchronous Python dependency directions

The baseline policy is deliberately small:

```text
catalog
   ^
   |
booking
   ^
   |
queue

booking
   ^
   |
communications
```

In table form:

| Owner | Approved synchronous business-module targets |
|---|---|
| `tenancy` | none |
| `catalog` | none |
| `requests` | none |
| `booking` | `catalog` |
| `queue` | `booking` |
| `communications` | `booking` |
| deferred modules | none until reactivated |

This is a permission map, not a requirement that every permitted edge be used.

The policy intentionally does **not** pre-approve edges merely because two modules
may eventually exchange information. For example, booking consequences consumed by
communications normally cross an outbox/event boundary instead of creating
`booking -> communications` coupling.

Adding a new edge requires an architectural decision, not a mechanical test edit.
Before adding it, answer:

```text
Who owns the capability?
Why must the dependency be synchronous?
What exact contract crosses the boundary?
Does the caller require immediate consistency?
Would an outbox/event surface preserve ownership better?
Could this edge create a dependency cycle?
```

Update the ownership/connection-surface documentation when the answer changes the
accepted architecture.

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

### Contracts

`modules/<owner>/contracts` is a published connection surface. It must remain
framework-free and dependency-light. It must not re-export the owner module's domain,
application, adapter or API internals.

If another module needs a concept, map the smallest stable representation into the
contract instead of exposing an internal entity/repository/transport DTO.

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

## 7. What the tests enforce

`tests/architecture/test_connection_surfaces.py` protects the process/module HTTP
boundary.

`tests/architecture/test_dependency_policy.py` protects:

- cross-module imports through `contracts` only;
- approved module dependency direction;
- acyclic module graph;
- domain inward dependency direction;
- application separation from adapters/transport;
- HTTP router separation from concrete adapters;
- dependency-light public contracts;
- persistence separation from HTTP transport.

`tests/architecture/test_repository_structure.py` continues to protect baseline
module ownership, platform purity, no global horizontal business roots, deferred
module isolation and other repository-level rules.

`tests/architecture/test_branch_workflow_contract.py` protects the repository
integration topology defined by `docs/architecture/branch-integration-contract.md`:

- ordinary PRs target `development`;
- only `development -> main` may target `main`;
- `tmp/*` branches cannot become ordinary PR heads;
- every ordinary PR must claim the single development integration lane by setting
  `.github/development-integration-lane` to the exact `GITHUB_HEAD_REF`;
- a stale/parallel sibling branch therefore receives an explicit integration-lane
  failure after another branch is integrated into `development`.

The lane guard is intentionally part of architecture CI rather than a separate
workflow so it does not add another Actions pipeline or status check.

These tests are **fitness functions**, not business correctness tests. PostgreSQL
race/invariant tests, unit tests and HTTP integration tests remain independently
required.

## 8. Failure messages are part of the agent interface

Architecture-test failures should explain:

```text
what boundary was crossed
which file/import crossed it
what surface is allowed
what design question must be answered before changing the policy
```

Branch-workflow failures additionally explain the repository recovery action. A
`Development integration lane mismatch` means the PR head no longer represents the
current serialized `development` integration state. The correct response is to
fetch/reconcile with current `origin/development`, set the lane cursor to the actual
PR head, and rerun required exact-head checks. It is not valid to weaken the test,
add a bypass branch, retarget the PR to `main`, or stack it on another feature branch.
