# Request Engine — Connection Surfaces

> **Estado:** normativo para cualquier cambio que cruce límites entre transport, módulos, PostgreSQL, workers o providers.
>
> Complementa `09-python-module-architecture.md`, `10-module-ownership-map.md`, `07-database-access-contract.md` y los contratos V3.

## 1. Principle

Request Engine is designed on three simultaneous axes:

1. **horizontal responsibilities** — transport, application, domain, persistence/provider mechanics;
2. **vertical ownership** — tenancy, catalog, requests, booking, queue, communications;
3. **connection surfaces** — explicit contracts where information/control crosses a boundary.

A component is not considered designed until its inbound and outbound connection surfaces are identified.

```text
BOX A
  |
 |-|
  |
BOX B
```

The `|-|` is a first-class architecture element. It must have explicit semantics, ownership and failure guarantees.

## 2. What counts as a connection surface

A connection surface can be a:

- typed Command or Query;
- supported module `contracts` type/protocol;
- module-owned HTTP router/model boundary;
- application port / Python `Protocol`;
- PostgreSQL command/read adapter;
- `request_read.*` view contract;
- narrow `request_cmd.*` consistency primitive;
- outbox event schema;
- ScheduledAction claim/execution protocol;
- provider send/lookup port;
- authenticated callback command.

The goal is not to manufacture interface classes. The goal is to make crossing a boundary deliberate and reviewable.

## 3. Required design questions

Before implementing a capability or integration, answer:

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

If the change cannot answer these questions, implementation is premature.

## 4. HTTP ↔ module surface

HTTP business transport belongs to the owning module:

```text
entrypoints/http/app.py
        |
        | modules.<owner>.api.install_http
        |
modules/<owner>/api/
        |
        | Command / Query
        |
module application/domain
```

`entrypoints/http` is a process composition/trust-boundary package, not a second business taxonomy.

Allowed global HTTP concerns include:

- ASGI app creation;
- deployment authentication adapter compatibility;
- middleware/tracing/CORS/request IDs;
- genuinely transport-global exception handling.

Module-specific routers, request/response models and domain error mappings live under `modules/<owner>/api`.

The entrypoint must not import `modules/<owner>/adapters/*` directly. It composes the module through its published HTTP installation surface.

## 5. HTTP authentication surface

The shared inbound trust boundary is:

```text
HTTP Request
    |
    | platform.security.http.ActorResolver
    |
ActorContext
```

`ActorContext` carries authenticated `organization_id`, `principal_id` and materialized capabilities. Caller-supplied tenant/principal identifiers never grant authority.

Module HTTP adapters perform capability checks before invoking application operations.

## 6. Module ↔ module surface

A module may use another module only through the target module's supported `contracts` package unless an explicit architecture decision defines another public facade.

```text
booking
   |
   | catalog.contracts
   |
catalog
```

Forbidden:

```text
booking -> catalog.adapters.db
booking -> catalog.domain internals
booking -> catalog.api models
```

Cross-module transactions may remain one PostgreSQL transaction when a documented invariant requires it; module aesthetics do not justify eventual consistency.

## 7. Python ↔ PostgreSQL surface

PostgreSQL and Python share authority deliberately.

Python owns:

- semantic command/query intent;
- policy orchestration;
- transaction framing;
- typed application/domain results.

PostgreSQL owns:

- tenant RLS/privilege backstops;
- FK/unique/check/exclusion structural truth;
- lock serialization roots;
- atomic state transition backstops;
- durable facts/outbox/idempotency records.

The connection surface is semantic, not generic CRUD:

```text
BookAppointmentCommand
        |
        | PostgresReservationCommands
        |
PostgreSQL transaction / locks / claims
```

and:

```text
request_read.reservation_status_v1
        |
        | PostgresReservationReader
        |
Reservation contract
```

Do not create a universal repository/UoW abstraction to hide correctness-sensitive SQL.

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

External systems are connected through ports/adapters:

```text
business intent
    |
    | provider port
    |
provider adapter
    |
external API
```

A provider SDK type must not leak into domain/application contracts.

Every provider surface must state:

- timeout behavior;
- retryability;
- idempotency key strategy;
- ambiguous-result handling;
- reconciliation/lookup strategy.

Never blindly resend an operation whose external outcome is unknown.

## 10. Async connection surfaces

Outbox, ScheduledAction and provider-delivery boundaries are asynchronous connection surfaces and therefore require stronger delivery semantics than normal in-process calls.

Examples:

```text
Request Engine transaction
  -> outbox event
  -> integration/n8n
  -> authenticated idempotent semantic callback
```

```text
ReminderPlan
  -> ScheduledAction
  -> worker claim/fence
  -> CommunicationTask
```

Each asynchronous surface must define dedupe identity, retry schedule, terminal/dead-letter semantics and reconciliation where ambiguity exists.

## 11. Capability locality rule

Filesystem layering exists to protect dependency direction, not to create a second global taxonomy.

Preferred:

```text
modules/booking/
  application/
  domain/
  adapters/
  contracts/
  api/
```

Avoid:

```text
entrypoints/http/booking.py
entrypoints/http/queue.py
entrypoints/http/requests.py
```

A capability should have the smallest practical change radius inside its owner while preserving shared domain invariants. Do not force every command into an isolated mini-application if that duplicates booking/capacity/queue rules.

## 12. Review rule

A code review for a new capability must review the boxes **and** every `|-|` it introduces or changes.

Ask:

1. Who owns this boundary?
2. What crosses it?
3. Is the contract semantic and typed?
4. What trust/tenant context crosses it?
5. Where does the transaction start/end?
6. What happens on retry, concurrency or ambiguous failure?
7. Can CI enforce that this connection is not bypassed?

Architecture tests should make high-value connection rules executable whenever practical.
