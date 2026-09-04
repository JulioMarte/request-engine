# Request Engine — Database Access Contract

> **Estado:** normativo para la frontera actual Python ↔ PostgreSQL.
>
> **Decisión:** PostgreSQL es una base inteligente y autoritativa para verdad estructural, concurrencia y hechos durables; no es un segundo application backend. Python conserva ownership de commands, policy orchestration y framing de transacciones de negocio. Este contrato complementa `10-module-ownership-map.md`, `13-connection-surfaces.md`, `architecture/system-optimization-mode.md` y los contratos actuales de cada capability.

## 1. Boundary

Request Engine deliberately rejects two opposite failure modes:

```text
A) database as dumb storage
application -> generic ORM CRUD -> arbitrary tables

B) database as second application backend
application -> workflow-sized stored procedures
```

The accepted shape is:

```text
HTTP / Agent / Webhook / Worker
              │
              ▼
       transport/adapters
              │
              ▼
       Application layer
 authority / policy / idempotency
              │
              ▼
      Session / DB transaction
              │
      ┌───────┴────────┐
      │                │
 COMMAND SIDE       QUERY SIDE
      │                │
semantic adapters   request_read.*
+ request_cmd.*     supported reads
      │                │
      └───────┬────────┘
              ▼
       request_engine.*
 authoritative relational state
 constraints / locks / revisions
              │
              ▼
 durable audit/event/outbox facts
```

Historical V2/V3 schema names and routines may be useful provenance, but current authority comes from this boundary, current capability contracts and actual migration/runtime evidence.

## 2. Ownership

### Python/Application owns

- semantic Commands/Queries and use-case orchestration;
- authorization/capability/representation policy;
- business policy evaluation;
- transaction framing;
- planning of multi-root lock work where business semantics require it;
- canonical application-level lock ordering contracts;
- idempotency semantics exposed to callers;
- provider/external I/O orchestration and ambiguity/reconciliation policy;
- domain recovery decisions;
- API/tool DTO contracts and mapping.

### PostgreSQL owns

- PK/FK/UNIQUE/CHECK/EXCLUDE structural truth;
- tenant equality and RLS/privilege backstops;
- stable serialization/lock roots;
- row/range locking and atomicity;
- local monotonicity and append-preserving historical backstops;
- durable idempotency/outbox/lease/audit/event facts;
- narrow atomic state-transition backstops;
- authoritative relational state queried by supported adapters.

### Forbidden

```text
table == public API resource
Pydantic DTO == domain/application type == persistence row
PATCH arbitrary authoritative fields
writable business views as generic mutation interfaces
INSTEAD OF triggers that interpret application workflows
workflow-sized stored procedures duplicating Python orchestration
network calls from PostgreSQL
hidden COMMIT/ROLLBACK inside business routines called by Python
materialized/derived read state used as mutation authority without revalidation
```

## 3. PostgreSQL schemas

### `request_engine`

Authoritative internal relational model: tables, constraints, integrity triggers and narrow internal helpers. It is not a product API.

### `request_read`

Supported capability-oriented read contracts/views where PostgreSQL projection is the appropriate boundary.

Rules:

1. read surfaces grant no mutation authority;
2. derived/read values are advisory unless an owning contract explicitly makes them authoritative;
3. mutation paths revalidate stale/read-derived input under the authoritative transaction/locks/revisions where required;
4. incompatible externally supported read contracts require an explicit compatibility/versioning decision once a real external obligation exists;
5. view/RLS/privilege semantics must be explicit — a view is not automatically a privilege boundary.

Do not proliferate versioned read views merely to simulate compatibility obligations that do not exist in pre-production.

### `request_cmd`

Narrow PostgreSQL primitives used when correctness is safer/clearer next to the data.

Good categories include:

```text
acquire/complete idempotency
claim/fence/release durable worker work
narrow atomic state transition
lock/validate a serialization root
append durable outbox/audit/event fact
```

Bad categories include:

```text
book_and_notify_customer(...)
run_recovery_workflow(...)
complete_front_desk_journey(...)
process_business_request_end_to_end(...)
```

Rule:

> `request_cmd` may encapsulate narrow consistency mechanics; Python remains owner of semantic workflows/commands.

### `request_admin`

Operational/diagnostic surfaces for administration/reconciliation. They are not product APIs and do not grant business authority.

## 4. Functions, procedures and transaction ownership

Python/application is the default owner of `BEGIN / COMMIT / ROLLBACK` for business commands.

A PostgreSQL routine called inside a business transaction must participate in that same transaction. Functions/narrow statements are normally preferred when they express the required primitive cleanly.

`CREATE PROCEDURE` is appropriate only for a demonstrated administrative/maintenance case whose independent transaction semantics are intentional and which does not duplicate a domain workflow.

For callable write/security primitives:

- schema-qualify objects;
- `SECURITY INVOKER` by default;
- use `SECURITY DEFINER` only for a narrowly reviewed privilege boundary with pinned safe `search_path` and explicit grants/revokes;
- revoke broad `PUBLIC` execution where the surface is not public;
- avoid dynamic SQL unless necessary and reviewed;
- never use generic `(entity_type, entity_id)` authority;
- no external I/O;
- do not hide a lock plan that conflicts with the current capability contract.

## 5. Session / transaction scope

One authoritative business command normally uses one task-local Session/AsyncSession and one explicit PostgreSQL transaction.

Do not:

- open independent hidden transactions inside repositories/helpers;
- commit halfway through a semantic command to simplify code;
- use a global/shared Session across concurrent requests;
- hold authoritative locks across external network I/O.

When a command composes multiple business modules atomically, the transaction remains one transaction even though ownership is modular. Module boundaries do not imply distributed transactions.

## 6. READ / PLAN / LOCK / VALIDATE / WRITE / EMIT

Correctness-sensitive writes should make this reasoning visible:

```text
READ      gather admissible current facts
PLAN      derive intended mutation/lock set
LOCK      acquire canonical serialization roots
VALIDATE  re-check stale/authority/capacity/business conditions
WRITE     commit authoritative state transition
EMIT      append durable consequence/audit/outbox facts in the same transaction
```

Not every trivial insert needs ceremonial functions for each word. The protocol is a reasoning model for contested/important mutations, not scaffolding.

For each relevant command identify:

- tenant/actor context;
- serialization roots;
- lock order;
- revision/staleness checks;
- constraints relied upon;
- idempotency identity;
- loser/failure semantics;
- durable side effects/outbox facts.

## 7. ORM vs explicit SQL

Use the simplest persistence mechanism that preserves clarity and correctness.

ORM is appropriate for ordinary relational persistence and mapping.

SQLAlchemy Core/explicit PostgreSQL SQL is appropriate for correctness-sensitive behavior such as:

- `FOR UPDATE` / `SKIP LOCKED`;
- range/exclusion behavior;
- batched worker claiming/fencing;
- atomic conditional updates;
- tenant/RLS/privilege probes;
- query shapes where PostgreSQL-specific semantics are part of the contract.

Do not hide race-critical SQL behind a generic repository abstraction just to make application code appear database-agnostic.

## 8. Mapping/type boundaries

Keep these distinct even when fields match:

```text
HTTP/tool Body/View
application Command/Query
module contract value
business/domain value
persistence row/mapping
provider SDK value
```

A persistence adapter maps database facts into the semantic type required by its caller. A database row or SQLAlchemy mapping must not leak directly as a public API or cross-module contract.

## 9. Read-before-write and stale data

A read/query result never becomes mutation authority merely because it came from PostgreSQL.

Where concurrency/staleness matters:

```text
read/advisory projection
        ↓
caller chooses intent
        ↓
authoritative command transaction
        ↓
lock + revalidate current truth
        ↓
write or deterministic rejection
```

This is especially important for availability, capacity, discovery handoff, recovery alternatives, queue selection, revisions and agent-facing operational reads.

## 10. Tenant / privilege boundary

Runtime database roles remain least privilege.

Current security expectations include:

- tenant isolation/RLS where required;
- caller-supplied identifiers do not establish tenant/subject authority;
- security-definer surfaces are narrow and auditable;
- grants are explicit rather than accidental schema-owner inheritance;
- worker cross-tenant discovery/claim surfaces are controlled and fenced rather than broad table access.

Changing table/function shape during system optimization does not relax these guarantees.

## 11. Provider/external I/O boundary

Never perform provider/network I/O while authoritative database locks are held.

Preferred pattern:

```text
business transaction
   -> durable outbox/task fact
commit
   -> external worker/provider
   -> durable result/callback/reconciliation command
```

If an external operation has an ambiguous outcome, do not blind-retry it without an idempotency or reconciliation contract.

## 12. Testing requirements

Claims that depend on PostgreSQL behavior use real PostgreSQL 18.

Use PostgreSQL-backed evidence for:

- constraints/ranges;
- RLS/privileges;
- row locks / `SKIP LOCKED`;
- races/concurrent loser semantics;
- leases/fencing;
- transaction rollback/atomicity;
- query plans when performance is part of an accepted requirement.

Mocked/in-memory persistence can test application policy but cannot prove PostgreSQL concurrency or privilege semantics.

## 13. System optimization / schema rebaseline

During `cohesion/system-optimization`, concrete schema/function/migration shape is CONTROLLED and may be changed after deliberate analysis. The historical V3 baseline is not a permanent product ceiling.

Do not casually rewrite migration history during unrelated work. A schema rebaseline is a dedicated operation governed by:

- `docs/architecture/system-optimization-mode.md`;
- `migrations/README.md`;
- `docs/testing/current-guarantees.toml`.

Before a rebaseline, audit current tables, relationships, indexes, constraints, RLS/policies, functions, triggers, grants, roles, read/cmd surfaces, lock roots and provenance needs. The target baseline must represent the coherent current model, not simply compress the existing migration chain blindly.

The invariant is not “keep the old SQL”. The invariant is “preserve or strengthen the guarantees the required SQL currently protects.”
