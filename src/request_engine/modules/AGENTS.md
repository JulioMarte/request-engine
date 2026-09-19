# Business module agent rules

Applies to `src/request_engine/modules/**` in addition to the repository-root `AGENTS.md`.

Before editing a module, read:

1. `docs/architecture/continuous-evolution-policy.md`;
2. `docs/architecture/system-optimization-mode.md` while the temporary optimization phase remains active;
3. `docs/10-module-ownership-map.md`;
4. the owning module `README.md`;
5. the current capability/domain contract being changed;
6. `docs/testing/current-guarantees.toml` for affected semantic guarantees;
7. `docs/testing/repository-governance-contract.md` for HARD / CONTROLLED / FLEXIBLE / HISTORICAL classification;
8. `docs/15-api-design-and-usability-standards.md` and `docs/16-canonical-operation-and-tool-projection-pattern.md` for machine-facing API/tool work.

## Current architecture posture

Request Engine is a modular monolith. Modules are organized by current business ownership, not by historical V2/V3/F1-F7 phases.

Current active business modules are:

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
onboarding
operational_copilot
```

Payments/reconciliation and field-service dispatch remain future domain areas only. They are deliberately **not current Python modules**; do not create empty placeholder packages for them. Introduce a new module only after accepted product scope gives it real ownership, connection surfaces and code.

Historical feature labels may remain in documentation/tests for provenance, but they are not a reason to preserve obsolete module boundaries or naming during the current optimization phase.

## Dependency boundary

A module's internals are private:

```text
domain/
application/
adapters/
api/
```

Cross-module business code may import only the target module's published `contracts` surface unless an explicit newer architecture decision defines another supported connection surface.

Never import another module's DB mappings, repositories, domain internals, application internals, HTTP DTOs or provider adapters merely because it is convenient.

Conceptual direction remains:

```text
api / provider adapter
        ↓
application
        ↓
domain + application ports
        ↑
adapters/db + adapters/providers
```

Entrypoints/bootstrap compose concrete modules. Business modules must not use bootstrap as a service locator.

## Connection surfaces

A module change is incomplete until its important inbound/outbound surfaces are explicit:

```text
Inbound caller/contract
Authentication + capability boundary
Application Command/Query
Transaction + idempotency boundary
Domain invariants
DB read/write adapter surface
Cross-module contracts
Outbox/ScheduledAction/provider surfaces
Failure/retry/reconciliation semantics
```

Do not create an adapter merely because two packages need to call each other. First decide ownership, contract direction, transaction boundary and failure semantics.

For Python ↔ PostgreSQL, prefer semantic operations such as `ReservationCommands` or `AppointmentAvailabilityReader`, not generic CRUD repositories. Keep correctness-sensitive SQL visible enough to review locks, constraints and race behavior.

For provider/network surfaces, external I/O occurs outside authoritative lock transactions and ambiguous outcomes reconcile before resend.

## Machine-facing operation gate

For any new or changed HTTP/agent-facing operation preserve these distinct concepts:

```text
owner
capability policy
OpenAPI operationId
optional tool name/audiences
```

Use resource-oriented HTTP when standard resource semantics are truthful. Use semantic custom methods for domain actions such as booking, rescheduling, check-in, intake control or recovery execution rather than generic status PATCHes or an untyped command bus.

Capability metadata remains authorization policy. Tool metadata is only projection/discovery metadata and must never replace capability/relationship/owner checks.

A tool-exposed operation requires an explicit stable `operationId` and owner. Agent/MCP adapters must call the same typed owner operation used by normal application/API paths; they do not implement business policy a second time.

Do not let model/tool input supply trusted `organization_id`, `principal_id`, authority Party, capability grants or trusted revision identity.

## Type and naming boundaries

Transport, business contracts, domain values and persistence models remain deliberately distinct even when their fields currently match:

```text
HTTP request Body      != application Command
HTTP response View     != domain/cross-module contract
cross-module contract  != persistence row
provider SDK type      != business contract
```

Business `domain`, `application` and `contracts` stay independent of Pydantic. Pydantic belongs at transport/configuration boundaries.

Use semantic operation names that expose intent rather than generic table mutation language.

Do not create generic business dumping grounds such as `services.py`, `helpers.py`, `utils.py`, `common.py`, `managers.py`, generic `repositories.py` or shared business `models.py` to avoid deciding ownership.

## Cohesion and maintainability

LOC, McCabe complexity, file count, fan-in and fan-out are review signals, not automatic architecture verdicts.

For changed Python:

```text
effective file LOC > 120
    -> QR-FSIZE-001 REVIEW_CANDIDATE

Ruff C901 McCabe > 10
    -> QR-CPLX-001 REVIEW_CANDIDATE

new direct outbound business-module dependency
    -> QR-COUPLING-001 REVIEW_CANDIDATE
```

There is **no hard 120-line architecture ceiling**. Do not split a cohesive file at 120/121 lines, do not target a lower metric as the definition of success, and do not retain an unnecessary abstraction merely because it helps a metric.

When a signal fires, review responsibility, reasoning complexity, side effects, locality, ownership, abstraction value and testability. `HEALTHY_AS_IS` is valid when the evidence does not justify structural change.

Do not game sensors by:

- mechanically splitting cohesive files;
- adding forwarding wrappers or one-function modules;
- proliferating interfaces/factories without a real substitution boundary;
- hiding direct dependencies behind service locators, runtime imports or re-export facades;
- moving business logic into `platform`, `shared`, `common` or utilities;
- duplicating logic to reduce measured fan-out or file size.

## Commands and persistence

Authoritative state changes are semantic commands and own their transaction orchestration.

Preserve accepted lock roots/order and cross-module atomicity when the domain requires them. Do not replace a correct local transaction with asynchronous events merely for architectural aesthetics.

Advisory reads/projections do not mutate source-module facts.

Never perform provider/network I/O while authoritative DB locks are held.

Provider SDK types stop at adapters. Domain code remains framework-free. SQLAlchemy mappings are adapter-local persistence details, not cross-module contracts or HTTP schemas.

Provider/n8n callbacks use authenticated, tenant-bound, idempotent semantic commands; never direct DB mutation or generic `set_status` APIs.

## Schema evolution

The accepted `0001_initial` + `migrations/baseline/` is immutable history. Ordinary schema evolution appends `0002+`; module work must not rewrite the accepted baseline to make a feature easier.

A schema change still begins from the module owner and affected guarantees. Follow `docs/architecture/continuous-evolution-policy.md` for compatibility, migration, rollout and recovery obligations.

## Optimization-mode changes

During `cohesion/system-optimization`, module ownership, dependency edges, internal file structure and historical names remain CONTROLLED but mutable when a change measurably improves present-day cohesion.

Any intentional ownership/dependency change must:

1. state why the old boundary is insufficient;
2. identify the new authoritative owner;
3. update the dependency policy and ownership docs coherently;
4. disposition affected guarantees;
5. preserve or strengthen adversarial/current-product proof;
6. avoid using architecture changes merely to make metrics or tests green.
