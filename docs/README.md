# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files should point here rather than duplicate these documents.

## V3 transition status

Request Engine is in a **pre-baseline capability-first V3 transition**.

The V3 product thesis is now followed by concrete capability and pre-SQL transaction contracts under `docs/v3/`. The V2 PostgreSQL design chain remains useful as an executable design notebook, but it is **not** a schema to freeze while it contains concepts V3 deferred or replaced.

When V3 and V2 conflict about product scope, Request semantics, baseline concepts, cardinality, transaction protocol, lock order, invariant ownership or whether a concept belongs in the first schema, V3 wins. Proven V2 safety patterns remain useful only where the corresponding V3 promise survives.

## Authoritative documents

Use this precedence when rules overlap:

1. `11-capability-first-v3.md` — product thesis, baseline capabilities and explicit V2 reductions.
2. `v3/01-capability-contracts.md` — public/application capability semantics for agents, forms, apps and integrations.
3. `v3/02-pre-sql-contract.md` — V3 entities/cardinalities, serialization roots, lock ordering, transaction protocols, invariants and race matrix.
4. `07-database-access-contract.md` — Python ↔ PostgreSQL boundary where not superseded by V3.
5. `09-python-module-architecture.md` — physical Python repository/module rules.
6. `10-module-ownership-map.md` — module ownership.
7. `00-product-definition.md`, `01-architecture-v2.md`, `02-pre-sql-domain-contract.md` — V2 source material only where it does not conflict with V3.

Transition support documents:

- `12-v3-transition-plan.md` — implementation/reduction order;
- `v3/sql-disposition.md` — V2 SQL disposition inventory; later V3 contracts close previously open `RE_EVALUATE` questions.

The domain/transaction contracts have precedence over implementation convenience. SQL implements accepted contracts; it must not silently redefine them.

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

The semantic dependency direction remains:

```text
entrypoint/adapter
      ↓
application command/query
      ↓
domain rules + explicit ports
      ↑
database/provider adapters
```

Physical organization is module-first according to `09-python-module-architecture.md`. This remains one modular monolith and does not imply microservice boundaries.

## Documentation organization policy

The older numbered canonical documents are retained during transition because design history and invariant references still point to them. Do not perform cosmetic bulk moves while V3 is stabilizing.

New V3 domain/schema contracts belong under `docs/v3/`. Durable rationale belongs in `adr/`.

## PostgreSQL executable design chain

Executable SQL does not live in `docs/`. The historical pre-baseline V2.6→V2.10 design chain remains under `migrations/sql/design_chain/`:

```text
03-postgresql-schema.sql
04-postgresql-v2.7-hardening.sql
05-postgresql-v2.8-hardening.sql
06-postgresql-v2.9-integrity.sql
08-postgresql-v2.10-access-surface.sql
```

These files are pre-production design history, not permanent Alembic history and not the V3 candidate. The next SQL artifact is a **clean reduced V3 candidate** derived from `v3/02-pre-sql-contract.md`, not another compatibility layer over speculative V2 objects.

See `migrations/README.md` before changing SQL.

## Historical material

Everything under `legacy/` is historical and non-authoritative. Do not edit, move, delete, reformat, or implement directly from it unless explicitly requested.
