# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files should point here rather than duplicate these documents.

## V3 transition status

Request Engine is in a **pre-baseline capability-first V3 transition**.

`11-capability-first-v3.md` records the current product/architecture direction after the adversarial V2 review. The V2 PostgreSQL design chain remains useful as an executable design notebook, but it is **not** a schema to freeze while it contains concepts that V3 has deferred or redefined.

When V3 and V2 conflict about product scope, Request semantics, baseline capabilities or whether a concept belongs in the first schema, V3 wins. Proven V2 safety rules such as tenant integrity, explicit transaction boundaries, canonical locking, idempotency, outbox-after-commit and real PostgreSQL race testing remain in force where the corresponding V3 concept still exists.

## Authoritative documents

Read according to the task, using this precedence when rules overlap:

1. `11-capability-first-v3.md` — current product thesis, capability model, V3 baseline and explicit V2 reductions.
2. `00-product-definition.md` — V2 product/domain contract; authoritative only where it does not conflict with V3 during transition.
3. `01-architecture-v2.md` — proven transactional/concurrency architecture retained where the V3 concept still exists.
4. `02-pre-sql-domain-contract.md` — V2 invariant/race catalog; source material for the reduced V3 matrix, not a baseline-freeze checklist until rewritten.
5. `07-database-access-contract.md` — normative Python ↔ PostgreSQL boundary, Unit of Work, repositories, read views and narrow DB primitives unless V3 explicitly changes the concept.
6. `09-python-module-architecture.md` — normative physical Python repository/module rules and transition topology.
7. `10-module-ownership-map.md` — normative mapping from domain concepts/commands/DB surfaces to module ownership.

Transition execution order and disposition of V2 concepts are documented in:

- `12-v3-transition-plan.md`.

The domain and transaction contracts have precedence over implementation convenience. SQL implements accepted contracts; it must not silently redefine them.

## Architecture Decision Records

`adr/` records durable rationale for hard-to-reverse architectural decisions. ADRs explain why the architecture exists; they do not replace the detailed normative contracts above.

Current accepted decisions include:

- modular monolith instead of premature microservices;
- smart PostgreSQL with Python-owned command orchestration;
- module-first Python physical organization;
- repository documentation as the canonical knowledge system for coding agents;
- capability-first product core instead of a universal workflow/domain model;
- durable transactional communications and scheduling separated from provider delivery.

See `adr/README.md`.

## Physical layout clarification

`01-architecture-v2.md` established the modular-monolith **logical dependency direction**. Its original illustrative horizontal folder tree is superseded for Python **physical organization** by `09-python-module-architecture.md`.

The semantic rule remains:

```text
entrypoint/adapter
      ↓
application command/query
      ↓
domain rules + explicit ports
      ↑
database/provider adapters
```

The physical layout groups those layers inside business modules to improve ownership/navigation; it does not change transactional boundaries or introduce microservices.

## Documentation organization policy

The numbered canonical documents are intentionally retained while the domain/schema is being reduced and frozen because many invariant references and design-chain comments point to them. Do not perform a cosmetic bulk move into new directories until the V3 contracts stabilize; that would create link churn without changing architecture.

New durable rationale belongs in `adr/`. New operational documentation should be grouped by purpose rather than extending historical numbering indefinitely after the V3 transition.

## PostgreSQL executable design chain

Executable SQL does not live in `docs/`. The current pre-baseline V2.6→V2.10 design chain is under `migrations/sql/design_chain/` and is applied in this order:

```text
03-postgresql-schema.sql
04-postgresql-v2.7-hardening.sql
05-postgresql-v2.8-hardening.sql
06-postgresql-v2.9-integrity.sql
08-postgresql-v2.10-access-surface.sql
```

These are pre-production design deltas, not permanent Alembic production history and not the V3 baseline. V3 should construct a clean reduced candidate schema rather than indefinitely layering compatibility migrations over speculative V2 concepts. See `migrations/README.md` and `12-v3-transition-plan.md`.

## Historical material

Everything under `legacy/` is historical and non-authoritative. Do not edit, move, delete, reformat, or implement directly from it unless the user explicitly requests an archive edit.
