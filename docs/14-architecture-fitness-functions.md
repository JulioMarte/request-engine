# Request Engine — architecture fitness functions

> **Estado:** normativo para las reglas estructurales ejecutables del backend actual.
>
> Este documento complementa `09-python-module-architecture.md`, `10-module-ownership-map.md`, `13-connection-surfaces.md`, `testing/repository-governance-contract.md` y `architecture/system-optimization-mode.md`. Los tests de `tests/architecture/` hacen cumplir estas reglas; no sustituyen los contratos de dominio/transacción.

## 1. Purpose

Request Engine treats architecture as an executable constraint, not only a diagram.

The repository protects simultaneously:

```text
horizontal responsibility
+ vertical business ownership
+ explicit connection surfaces
+ understandable acyclic dependency direction
```

A change may compile and pass feature tests while still being architecturally invalid if it crosses a boundary through an unsupported surface.

Architecture fitness functions detect unreviewed drift. During system optimization they do **not** turn previous V3/Fx repository shape into an immutable constitution.

## 2. Cross-module rule

A business module may depend synchronously on another business module only when both conditions are true:

1. the dependency direction is explicitly approved;
2. the import uses the target module's published `contracts` surface.

Example:

```text
booking -> catalog.contracts        allowed when the edge is approved
booking -> catalog.domain           forbidden
booking -> catalog.application      forbidden
booking -> catalog.adapters         forbidden
booking -> catalog.api              forbidden
```

`contracts` is not universal permission. The module-to-module edge itself must also be approved.

## 3. Current approved synchronous Python dependency directions

The executable source used by the dependency fitness tests is `tests/architecture/dependency_policy.py`. This document must describe the same accepted topology; if either changes intentionally, update both in one coherent architecture change.

Current permission map:

| Owner | Approved synchronous business-module targets |
|---|---|
| `tenancy` | none |
| `catalog` | none |
| `requests` | `tenancy` |
| `booking` | `catalog`, `tenancy` |
| `queue` | `booking`, `tenancy` |
| `communications` | `booking` |
| `discovery` | `booking` |
| `delivery` | none |
| `live_capacity` | `booking`, `delivery`, `queue` |
| `operational_recovery` | `booking`, `communications`, `live_capacity` |
| `operational_copilot` | `booking`, `catalog`, `discovery`, `live_capacity`, `operational_recovery`, `queue`, `tenancy` |
| `payments` | none |
| `dispatch` | none |

This is a **permission map**, not a requirement that every permitted edge be used. Actual imports may be a strict subset.

Do not widen the map mechanically to make a test pass. Before accepting a new synchronous edge answer:

```text
Who owns the capability?
Why must this relationship be synchronous?
What exact contract crosses the boundary?
Does the caller require immediate consistency?
Would an outbox/event/read model preserve ownership better?
Could the edge create a dependency cycle?
Is an orchestrator genuinely the correct owner of this fan-out?
```

A high-fan-out orchestrator is not automatically unhealthy. Fan-out is a review signal; hidden dependencies, cycles or wrong ownership are the actual architectural risks.

An existing allowlist is the accepted current policy, not an eternal ban on evolution. A capability may change the topology when its current normative contract demonstrates that the old ownership model is insufficient and the replacement remains explicit, acyclic and proven.

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

Do not solve cycles with a shared business `common` package, service locator, runtime import trick or re-export facade.

## 5. Layer fitness rules

### Domain

`modules/<owner>/domain` must not depend on FastAPI, SQLAlchemy/asyncpg/psycopg, bootstrap/entrypoints, the module's application layer, adapters or API transport.

### Application

`modules/<owner>/application` must not depend on FastAPI/persistence drivers, bootstrap/entrypoints, concrete adapters or API transport. Application defines/uses semantic Commands, Queries and `Protocol` ports.

### Contracts

`modules/<owner>/contracts` is a published connection surface. It must remain framework-free and dependency-light and must not re-export owner domain/application/adapter/API internals.

If another module needs a concept, map the smallest stable representation into the contract instead of exposing an internal entity/repository/transport DTO.

### Database adapters

`modules/<owner>/adapters/db` may know persistence infrastructure but must not depend on FastAPI, module HTTP DTOs or process entrypoints.

Mapping direction:

```text
PostgreSQL row/result
    -> DB adapter
    -> application/domain/contract value
    -> transport mapper
    -> HTTP DTO
```

Never `DB adapter -> HTTP DTO`.

## 6. HTTP/composition fitness rules

A module HTTP router is an inbound adapter and must be typed against application surfaces rather than concrete PostgreSQL implementations.

Concrete DB/provider construction belongs in the module-owned install/composition surface or process composition root according to `13-connection-surfaces.md`.

`entrypoints/http` and `bootstrap` are composition/trust boundaries. They must not become a hidden parallel business taxonomy or service locator. If cross-domain business policy appears there, assign an explicit owner rather than hiding fan-out from the business-module graph.

## 7. What the tests enforce

`tests/architecture/test_connection_surfaces.py` protects process/module composition boundaries.

`tests/architecture/test_dependency_policy.py` protects:

- cross-module imports through `contracts` only;
- approved module dependency direction;
- acyclic module graph;
- domain inward dependency direction;
- application separation from adapters/transport;
- HTTP router separation from concrete adapters;
- dependency-light public contracts;
- persistence separation from HTTP transport.

`tests/architecture/test_repository_governance_contract.py` protects type/DTO/instruction/repository governance boundaries.

`tests/architecture/test_branch_workflow_contract.py` protects serialized development integration topology.

Other architecture tests may protect narrower current capabilities. Their authority comes from the semantic property they defend, not from their filename or release-era origin.

These are fitness functions, not substitutes for PostgreSQL races/invariants, application tests or production-like E2E proof.

## 8. Maintainability signals are not architecture verdicts

Current quality tooling may emit:

```text
QR-FSIZE-001     file-size review candidate
QR-CPLX-001      C901/McCabe review candidate
QR-NAV-001       navigation/forwarding review candidate
QR-COUPLING-001  new outbound module-dependency review candidate
```

These are non-blocking semantic-review prompts. There is no hard `120 LOC`, `C901 > 10`, file-count, fan-in or fan-out architecture cliff.

The required review path is defined by:

- `docs/engineering-quality/agent-semantic-review-playbook.md`;
- `docs/engineering-quality/semantic-review-protocol.md`.

`HEALTHY_AS_IS` is valid. Do not split cohesive files, add forwarding wrappers, hide dependencies or introduce abstraction ceremony only to improve a metric.

Deterministic HARD failures — unsupported internal imports, unapproved edges, cycles, inward framework leakage, security/authority/transaction invariants — remain independently blocking and cannot be waived by semantic review.

## 9. Fitness-function evolution

A fitness-function failure has two legitimate dispositions:

```text
UNINTENTIONAL DRIFT
  repair implementation to satisfy accepted architecture

INTENTIONAL ARCHITECTURE EVOLUTION
  update current normative ownership/connection contract
  update executable policy/test coherently
  preserve or strengthen the protected guarantee
  provide exact-head evidence
```

The second path is not a bypass. It is governed by `architecture/system-optimization-mode.md`, `architecture/pre-production-evolution-policy.md` and `testing/repository-governance-contract.md`.

Exact snapshots/allowlists are useful only where the listed shape is itself CONTROLLED. They must not force current Request Engine to retain an old module inventory, capability list, migration-head assumption or repository shape merely because it was once release-proven.

When evolving a structural test:

```text
old assertion
    -> identify protected risk
    -> define current architecture
    -> KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition
    -> preserve semantic proof
    -> add adversarial evidence when risk is behavioral/concurrent/security-sensitive
```

Removing an obsolete structural assertion without preserving its protected intent is invalid. Keeping an obsolete assertion after the accepted contract changed is also invalid.

## 10. Failure messages are part of the agent interface

Architecture-test failures should explain:

```text
what boundary was crossed
which file/import crossed it
what surface is allowed
what design question must be answered before changing policy
```

Branch-workflow failures additionally explain the repository recovery action. A `Development integration lane mismatch` is an integration-state error: reconcile with current `origin/development`, set `.github/development-integration-lane` to the actual PR head and rerun exact-head checks. Do not weaken the test, create a bypass branch or retarget ordinary work to `main`.
