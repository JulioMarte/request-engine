# Business module agent rules

Applies to `src/request_engine/modules/**` in addition to the root `AGENTS.md`.

Before editing a module, read its `README.md`, confirm ownership in `docs/10-module-ownership-map.md`, identify the capability (`Query`, `Command`, `Request`, or scheduled business action), the V3/current invariant or promise affected, and every architectural connection surface the change crosses. For repository/type-boundary rules also read `docs/testing/repository-governance-contract.md`.

## V3/current module status

Baseline modules:

```text
tenancy
catalog
requests
booking
queue
communications
```

Active post-V3 modules:

```text
discovery    # F2 cross-tenant published-supply discovery
```

Deferred/incubating during transition:

```text
delivery
payments
dispatch
```

Baseline and active post-V3 modules must not import or depend on deferred modules unless a concrete product use case reactivates the concept through an accepted architecture change. `discovery` follows the same contracts-only cross-module rule as baseline modules; its public process must not embed Booking's tenant-domain database credential.

## Dependency boundary

A module's internals are private to that module:

```text
domain/
application/
adapters/
api/
```

Cross-module code may import only the target module's supported `contracts` surface (or an explicitly documented facade during migration). Never import another module's DB mappings, repositories, domain internals, API DTOs, or provider adapters.

Conceptual direction:

```text
api / provider adapter
        ↓
application
        ↓
domain + application ports
        ↑
adapters/db + adapters/providers
```

Business transport belongs to the module. `modules/<owner>/api` owns its routers, transport DTOs and business-to-HTTP error mapping. Process entrypoints compose that published API surface; they must not reach into module DB/provider adapters.

## DTO and naming boundary

Transport, business contracts, domain values, and persistence models are deliberately distinct even when their fields happen to match today:

```text
HTTP request Body      != application Command
HTTP response View     != domain/cross-module contract
cross-module contract  != persistence row
provider SDK type      != business contract
```

Business-module `domain`, `application`, and `contracts` must remain independent of Pydantic. Pydantic belongs at transport/configuration boundaries, not in business semantics.

Current HTTP transport naming convention:

- top-level request JSON models: descriptive `*Body`;
- response/read projections: descriptive `*View`;
- transport-only path/query models: an explicit transport suffix such as `*Params`;
- nested request components may use a descriptive transport-explicit suffix such as `*InputModel`;
- cross-module `contracts`: business names, never transport/persistence suffixes such as `Body`, `View`, `Row`, `ORM`, or provider-specific SDK names.

Do not rename these categories into ambiguous generic `Model`/`Schema` objects merely to reduce mapping code. The mapping is intentional boundary evidence. A nested `*InputModel` is acceptable because its transport role is explicit; the rule is not that every nested object must pretend to be a top-level Body.

## Connection surfaces

A module change is incomplete until its inbound and outbound surfaces are explicit.

Before coding, record mentally or in the change design:

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

For Python ↔ PostgreSQL, adapters must be semantic (`ReservationCommands`, `AppointmentAvailabilityReader`, etc.), not generic CRUD repositories. Keep correctness-sensitive SQL visible enough to review locks, constraints and race behavior.

For module ↔ module, use only supported `contracts`; never shortcut through another module's adapters.

For provider/network surfaces, external I/O occurs outside authoritative lock transactions and ambiguous outcomes reconcile before resend.

## Product-language boundary

- Do not use `Request` as a universal wrapper for mutations. Cancel/reschedule/attendance/queue actions are Commands by default.
- Keep ServiceQueue and Waitlist distinct.
- Keep reservation confirmation and attendance confirmation distinct.
- Communications owns transactional intent/delivery semantics; external providers/n8n remain adapters.
- Do not reintroduce Workflow/OutcomeScope/advanced payments/dispatch/fulfillment/capacity-pool abstractions into baseline modules solely because V2 docs or SQL contain them.

## Structure discipline

Create folders only when real code needs them. A small module may begin with a few cohesive files and grow toward:

```text
<module>/
  domain/
  application/
    commands/
    queries/
    ports/
  adapters/
    db/
    providers/
  api/
  contracts/
  README.md
```

Do not create generic business dumping grounds such as `services.py`, `helpers.py`, `utils.py`, `common.py`, or `managers.py`. Do not use a generic `repositories.py` or shared business `models.py` to avoid deciding ownership. `api/models.py` is acceptable specifically as the module-owned transport DTO boundary; persistence models remain adapter-local and private.

Use semantic operation names that expose intent (`BookAppointment`, `JoinQueue`, `RecordDeliveryResult`) rather than table-mutation language (`SetStatus`, generic `UpdateEntity`) unless the latter is genuinely the accepted business capability.

Keep handwritten Python files near 100 effective code lines. The repository intentionally tolerates 101–120 effective lines; do not split or regenerate a cohesive file just because it reached 102. New or previously compliant files may not exceed 120 effective lines. Blank/comment-only lines do not count, while docstrings do. Existing files already above 120 are ratcheted and may not grow.

## Commands and persistence

- Authoritative changes are semantic commands and own their transaction orchestration.
- Preserve documented lock roots/order and cross-module atomicity when the domain requires it.
- Do not replace a correct local transaction with asynchronous events merely for module aesthetics.
- Never perform provider/network I/O while authoritative DB locks are held.
- Provider SDK types stop at adapters.
- Domain code remains framework-free.
- SQLAlchemy mappings are persistence details, not cross-module contracts or API schemas.
- Prefer semantic DB operations and explicit SQL/Core for correctness-sensitive locking/concurrency paths.
- Provider/n8n callbacks use authenticated, tenant-bound, idempotent semantic commands; never direct DB mutation or generic `set_status` APIs.
