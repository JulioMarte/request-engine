# Request Engine — architecture fitness functions

> **Estado:** normativo para las reglas estructurales ejecutables del backend actual.
>
> Complementa `09-python-module-architecture.md`, `10-module-ownership-map.md`, `13-connection-surfaces.md`, `testing/repository-governance-contract.md` y `architecture/continuous-evolution-policy.md`. Los tests de `tests/architecture/` hacen cumplir estas reglas; no sustituyen contratos de dominio/transacción.

## 1. Purpose

Request Engine protects simultaneously:

```text
horizontal responsibility
+ vertical business ownership
+ explicit connection surfaces
+ understandable acyclic dependency direction
```

A change may compile and pass feature tests while still being architecturally invalid if it crosses a boundary through an unsupported surface. Fitness functions detect unreviewed drift; they do not freeze prior V2/V3/Fx repository shape.

## 2. Cross-module rule

A business module may depend synchronously on another business module only when:

1. the dependency direction is explicitly approved; and
2. the import uses the target module's published `contracts` surface.

`contracts` is not universal permission. The edge itself must be approved. Do not hide a real business dependency in `bootstrap`, `entrypoints`, `platform`, runtime imports, service locators or re-export facades merely to avoid showing it in the graph.

## 3. Current active module inventory and approved synchronous directions

The executable source is `tests/architecture/dependency_policy.py`. The test discovers physical module inventory, so an added or removed package requires an explicit policy decision.

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
| `operational_recovery` | `booking`, `catalog`, `communications`, `live_capacity`, `queue` |
| `operational_copilot` | `booking`, `catalog`, `discovery`, `live_capacity`, `operational_recovery`, `queue`, `tenancy` |
| `onboarding` | `booking`, `catalog`, `communications`, `queue`, `tenancy` |

Payments/reconciliation and field-service dispatch are future domain areas, not current Python modules or policy nodes.

This is a permission map, not a requirement that every permitted edge be used. `operational_recovery` and `onboarding` legitimately have wider fan-out because they own explicit cross-domain composition. That fan-out must remain visible and contract-only; hiding it outside the owner is worse architecture than showing it.

Before accepting a new edge answer:

```text
Who owns the capability?
Why must this relationship be synchronous?
What exact contract crosses the boundary?
Does the caller require immediate consistency?
Would an event/read model preserve ownership better?
Could the edge create a cycle?
Is an orchestrator genuinely the correct owner of this fan-out?
```

## 4. Dependency cycles are forbidden

The actual business-module dependency graph must remain acyclic. A cycle normally indicates wrong ownership, an internal leak, a missing one-way contract or two concepts that are not actually separate bounded contexts.

Do not solve cycles with shared business `common`, service locators, runtime-import tricks or facades.

## 5. Layer fitness rules

### Domain
`modules/<owner>/domain` must not depend on FastAPI, SQLAlchemy/asyncpg/psycopg, bootstrap/entrypoints, application, adapters or API transport.

### Application
`modules/<owner>/application` must not depend on FastAPI/persistence drivers, bootstrap/entrypoints, concrete adapters or API transport. Application defines/uses semantic Commands, Queries and Protocol ports. It may depend on other business modules only through approved target `contracts`.

### Contracts
`modules/<owner>/contracts` is a published connection surface. It must remain framework-free, dependency-light and must not re-export owner internals.

### Database/provider adapters
Adapters may know technical infrastructure and approved owner contracts, but they must not depend on HTTP DTOs or process entrypoints. Correctness-sensitive SQL remains reviewable rather than hidden behind generic CRUD repositories.

## 6. Composition-root rule

`entrypoints` and `bootstrap` may construct objects and wire published surfaces. They must not implement business translation/policy solely to keep a module dependency invisible.

Healthy:

```text
entrypoint builds OwnerA contract implementation
entrypoint builds OwnerB orchestration service
entrypoint passes implementation into OwnerB
```

Unhealthy:

```text
entrypoint/bootstrap defines a business adapter that translates OwnerB workflow
into OwnerA semantics so OwnerB -> OwnerA disappears from the module graph
```

Cross-domain aggregate policy with its own product capability belongs to an explicit owner. `onboarding.read`, for example, is owned by `onboarding`; Entrypoints only wires the five owner readers.

## 7. What the tests enforce

`tests/architecture/test_connection_surfaces.py` protects process/module composition boundaries.

`tests/architecture/test_dependency_policy.py` protects:

- every physical business module has an explicit policy entry;
- cross-module imports use `contracts` only;
- approved dependency direction;
- acyclic module graph;
- domain/application inward dependency direction;
- HTTP separation from concrete adapters;
- dependency-light public contracts;
- persistence separation from HTTP transport.

`tests/architecture/test_repository_governance_contract.py` protects type/DTO/instruction/repository governance boundaries. `tests/architecture/test_branch_workflow_contract.py` protects serialized development integration topology.

These are fitness functions, not substitutes for PostgreSQL races/invariants, application tests or E2E proof.

## 8. Maintainability signals are not architecture verdicts

Current quality tooling may emit:

```text
QR-FSIZE-001     file-size review candidate
QR-CPLX-001      C901/McCabe review candidate
QR-NAV-001       navigation/forwarding review candidate
QR-COUPLING-001  new outbound module-dependency review candidate
```

These are non-blocking semantic-review prompts. There is no hard 120 LOC, C901, file-count, fan-in or fan-out cliff. `HEALTHY_AS_IS` is valid. Do not split cohesive files, add forwarding wrappers, hide dependencies or add abstraction ceremony to improve a metric.

Deterministic HARD failures — unsupported internal imports, unapproved edges, cycles, inward framework leakage, security/authority/transaction invariants — remain independently blocking.

## 9. Fitness-function evolution

A fitness failure has two legitimate dispositions:

```text
UNINTENTIONAL DRIFT
  repair implementation to accepted architecture

INTENTIONAL ARCHITECTURE EVOLUTION
  update current ownership/connection contract
  update executable policy/test coherently
  preserve or strengthen protected guarantees
  provide exact-head evidence
```

The second path is governed by `architecture/continuous-evolution-policy.md`, `architecture/system-optimization-mode.md` and `testing/repository-governance-contract.md`.

## 10. Failure messages are part of the agent interface

Architecture-test failures should explain what boundary was crossed, which file/import crossed it, what surface is allowed and what design question must be answered before changing policy.

A `Development integration lane mismatch` is an integration-state error: reconcile with current `origin/development`, set `.github/development-integration-lane` to the actual working PR branch and rerun exact-head checks. Do not weaken the test or create a bypass branch.
