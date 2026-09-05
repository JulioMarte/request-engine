# Request Engine — Connection Surfaces

> **Estado:** normativo para cualquier cambio que cruce límites entre transport, módulos, PostgreSQL, workers o providers.
>
> Complementa `09-python-module-architecture.md`, `10-module-ownership-map.md`, `07-database-access-contract.md`, `14-architecture-fitness-functions.md` y `architecture/system-optimization-mode.md`.

## 1. Principle

Request Engine is designed on three simultaneous axes:

1. **horizontal responsibilities** — transport, application, domain, persistence/provider mechanics;
2. **vertical ownership** — current business modules such as tenancy, catalog, requests, booking, queue, communications, discovery, delivery, live capacity, operational recovery and bounded operational tooling;
3. **connection surfaces** — explicit contracts where information/control crosses a boundary.

A component is not considered designed until its inbound and outbound connection surfaces are identified.

```text
BOX A
  |
 |-|
  |
BOX B
```

The `|-|` is a first-class architecture element. It needs explicit semantics, ownership and failure guarantees.

Historical V3/Fx labels may describe when a surface entered the system. They do not define a separate current boundary taxonomy.

## 2. What counts as a connection surface

A connection surface can be a:

- typed Command or Query;
- supported module `contracts` value/protocol;
- module-owned HTTP router/model boundary;
- application port / Python `Protocol`;
- PostgreSQL command/read adapter;
- `request_read.*` view contract;
- narrow `request_cmd.*` consistency primitive;
- outbox/event schema;
- ScheduledAction claim/execution protocol;
- provider send/lookup port;
- authenticated callback command/tool invocation.

The goal is not to manufacture interface classes. The goal is to make crossing a boundary deliberate and reviewable.

## 3. Required design questions

Before implementing or changing a capability/integration, answer:

```text
Business owner:
Capability:

Inbound connection:
Caller:
Input contract:
Authentication boundary:
Authorization/capability boundary:

Application boundary:
Command/Query:
Transaction boundary:
Idempotency boundary:

Domain responsibility:
Invariants:

Outbound connections:
Database:
Other modules:
Provider:
Events/ScheduledAction:

Failure semantics:
Retry semantics:
Ambiguous-result/reconciliation semantics:
```

If a meaningful boundary change cannot answer these questions, implementation is premature.

## 4. HTTP ↔ module surface

HTTP business transport belongs to the owning module:

```text
entrypoints/http
        |
        | module-owned install/composition surface
        |
modules/<owner>/api/
        |
        | application Command / Query / Protocol
        |
module application/domain
```

`entrypoints/http` is a process composition/trust boundary, not a second business taxonomy.

Allowed global HTTP concerns include ASGI app creation, deployment authentication compatibility, middleware/tracing/CORS/request IDs and genuinely transport-global exception handling.

Module-specific routers, request/response models and domain error mappings belong under `modules/<owner>/api`.

Entrypoints must not reach directly into another module's DB/provider internals. If cross-domain business policy appears in the composition root, give that policy an explicit owner rather than hiding coupling there.

## 5. HTTP authentication/authority surface

The shared inbound trust boundary is conceptually:

```text
HTTP Request
    |
    | authenticated actor resolver
    |
ActorContext
```

`ActorContext` carries authenticated tenant/principal/capability context. Caller-supplied organization, principal, Party or revision identifiers never manufacture authority.

Authentication and a broad capability do not automatically grant authority over an arbitrary same-tenant Party. Subject-scoped capabilities must state whether they require Representation, operator override or another explicit authority rule.

## 6. Module ↔ module surface

A module may use another module only through the target module's supported `contracts` package **and** an approved dependency direction.

Examples of accepted current patterns include:

```text
booking              -> tenancy.contracts / catalog.contracts
queue                -> booking.contracts / tenancy.contracts
discovery            -> booking.contracts
live_capacity        -> booking.contracts / queue.contracts / delivery.contracts
operational_recovery -> booking.contracts / live_capacity.contracts / communications.contracts
operational_copilot  -> published owner contracts only
```

The exact current permission map is documented in `14-architecture-fitness-functions.md` and executed by `tests/architecture/dependency_policy.py`.

Forbidden regardless of whether the target edge would otherwise be allowed:

```text
booking -> catalog.adapters.db
booking -> catalog.domain internals
booking -> catalog.api models
```

Cross-module transactions may remain one PostgreSQL transaction when a documented invariant requires it. Module aesthetics do not justify eventual consistency.

A high-fan-out orchestration module is not automatically invalid; the review question is whether it genuinely owns coordination and still relies only on published owner contracts without gaining shadow authority.

## 7. Python ↔ PostgreSQL surface

Python and PostgreSQL share authority deliberately.

Python owns:

- semantic command/query intent;
- policy orchestration;
- transaction framing;
- typed application/domain results.

PostgreSQL owns:

- tenant RLS/privilege backstops;
- FK/unique/check/exclusion structural truth;
- lock serialization roots;
- atomic state-transition backstops;
- durable facts/outbox/idempotency/lease records.

The boundary is semantic rather than generic CRUD.

Do not create a universal repository/UoW abstraction merely to hide correctness-sensitive SQL.

During system optimization, concrete schema/function shape is CONTROLLED and may be redesigned through the dedicated schema-audit/rebaseline process. The tenant/authority/atomicity/capacity/provenance/concurrency guarantees those database structures protect remain HARD.

## 8. Transactional surface checklist

For every PostgreSQL write surface identify:

```text
READ
PLAN
LOCK
VALIDATE
WRITE
EMIT
```

Also document/test:

- tenant context;
- serialization/lock root;
- lock ordering;
- constraints relied upon;
- expected revision/idempotency behavior;
- outbox/audit facts;
- concurrent loser semantics.

Provider/network I/O never occurs while authoritative DB locks are held.

## 9. External/provider surface

External systems connect through explicit ports/adapters:

```text
business intent
    |
    | provider port
    |
provider adapter
    |
external API
```

Provider SDK types do not leak into domain/application/cross-module contracts.

Every provider surface states:

- timeout behavior;
- retryability;
- idempotency/dedupe strategy;
- ambiguous-result handling;
- reconciliation/lookup strategy.

Never blindly resend an operation whose external outcome is unknown.

## 10. Async connection surfaces

Outbox, ScheduledAction and provider-delivery boundaries are asynchronous connection surfaces and therefore require explicit durability/retry/reconciliation semantics.

Examples:

```text
Request Engine transaction
  -> outbox event
  -> integration/provider
  -> authenticated idempotent semantic callback
```

```text
business scheduling intent
  -> ScheduledAction
  -> worker claim/fence
  -> owner command
```

Each asynchronous surface defines dedupe identity, retry schedule, lease/fence behavior where applicable, terminal/dead-letter semantics and reconciliation for ambiguous outcomes.

## 11. Capability locality rule

Filesystem layering protects dependency direction; it must not create a second global taxonomy.

Preferred:

```text
modules/booking/
  application/
  domain/
  adapters/
  contracts/
  api/
```

Avoid business taxonomies under process roots such as:

```text
entrypoints/http/booking_business_logic.py
entrypoints/http/queue_policy.py
```

A capability should have the smallest practical change radius inside its owner while preserving shared invariants. Do not force every command into an isolated mini-application if that duplicates domain policy.

Likewise, do not move cross-domain orchestration into entrypoints/platform simply to avoid a visible business-module edge. Explicit coupling is healthier than hidden coupling.

## 12. Review rule

A code review for a new/changed capability reviews the boxes **and** every `|-|` it introduces or changes.

Ask:

1. Who owns this boundary?
2. What crosses it?
3. Is the contract semantic and typed?
4. What trust/tenant context crosses it?
5. Where does the transaction start/end?
6. What happens on retry, concurrency or ambiguous failure?
7. Can CI enforce that this connection is not bypassed?
8. Does this edge make ownership clearer, or only hide/repackage existing coupling?

Architecture tests should make high-value connection rules executable whenever practical. Intentional evolution is allowed under `architecture/system-optimization-mode.md`; mechanical boundary weakening is not.
