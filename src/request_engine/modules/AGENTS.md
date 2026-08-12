# Business module agent rules

Applies to `src/request_engine/modules/**` in addition to the root `AGENTS.md`.

Before editing a module, read its `README.md`, confirm ownership in `docs/10-module-ownership-map.md`, and identify the capability (`Query`, `Command`, `Request`, or scheduled business action) plus the V3 invariant/promise affected.

## V3 module status

Baseline modules:

```text
tenancy
catalog
requests
booking
queue
communications
```

Deferred/incubating during transition:

```text
delivery
payments
dispatch
```

Baseline modules must not import or depend on deferred modules unless a concrete product use case reactivates the concept through an accepted architecture change.

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

`bootstrap` wires dependencies. Do not pull dependencies from a global container inside module code.

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

Do not create generic `services.py`, `helpers.py`, `utils.py`, `common.py`, `managers.py`, or one global repository abstraction to avoid deciding ownership.

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
