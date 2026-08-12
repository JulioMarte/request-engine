# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files should point here rather than duplicate these documents.

## V3 transition status

Request Engine is in a **pre-baseline capability-first V3 transition**.

The V3 product thesis is followed by concrete capability and pre-SQL transaction contracts under `docs/v3/`, and those contracts now drive an executable clean PostgreSQL 18 candidate under `migrations/sql/v3_candidate/`.

The historical V2 PostgreSQL design chain remains useful as executable design history, but it is **not** a schema to freeze or extend. The active candidate is still pre-baseline: it must survive the required PostgreSQL invariant/race/security tests and application vertical slices before becoming `0001_initial`.

When V3 and V2 conflict about product scope, Request semantics, baseline concepts, cardinality, transaction protocol, lock order, invariant ownership or whether a concept belongs in the first schema, V3 wins. Proven V2 safety patterns remain useful only where the corresponding V3 promise survives.

## Authoritative documents

Use this precedence when rules overlap:

1. `11-capability-first-v3.md` — product thesis, baseline capabilities and explicit V2 reductions.
2. `v3/01-capability-contracts.md` — public/application capability semantics for agents, forms, apps and integrations.
3. `v3/02-pre-sql-contract.md` — V3 entities/cardinalities, serialization roots, lock ordering, transaction protocols, invariants and race matrix.
4. `07-database-access-contract.md` — Python ↔ PostgreSQL boundary where not superseded by V3.
5. `09-python-module-architecture.md` — physical Python repository/module rules.
6. `13-connection-surfaces.md` — mandatory contracts between transport, modules, PostgreSQL, workers and providers.
7. `10-module-ownership-map.md` — module ownership.
8. `00-product-definition.md`, `01-architecture-v2.md`, `02-pre-sql-domain-contract.md` — V2 source material only where it does not conflict with V3.

Transition support documents:

- `12-v3-transition-plan.md` — implementation/reduction order;
- `v3/sql-disposition.md` — V2 SQL disposition inventory; later V3 contracts close previously open `RE_EVALUATE` questions;
- `migrations/README.md` — active V3 candidate ownership, apply order and baseline-freeze gate.

The domain/transaction contracts have precedence over implementation convenience. SQL implements accepted contracts; it must not silently redefine them.

## Architecture Decision Records

`adr/` records durable rationale for hard-to-reverse architectural decisions. ADRs explain why the architecture exists; they do not replace the detailed normative contracts above.

Current accepted decisions include:

- modular monolith instead of premature microservices;
- smart PostgreSQL with Python-owned command orchestration;
- module-first Python physical organization;
- repository documentation as the canonical knowledge system for coding agents;
- capability-first product core instead of a universal workflow/domain model;
- durable transactional communications and scheduling separated from provider delivery;
- the minimal V3 booking/capacity model;
- PostgreSQL RLS as tenant defense-in-depth with narrow cross-tenant worker claim surfaces.

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

Physical organization is module-first according to `09-python-module-architecture.md`. Business transport is module-owned, while process entrypoints compose published module surfaces rather than reaching into module persistence/provider internals.

Every boundary crossing is also an explicit connection surface according to `13-connection-surfaces.md`:

```text
BOX A
  |
 |-|
  |
BOX B
```

The connector must define ownership, contract, trust/tenant context, transaction semantics and failure/retry behavior where applicable. This remains one modular monolith and does not imply microservice boundaries.

## Documentation organization policy

The older numbered canonical documents are retained during transition because design history and invariant references still point to them. Do not perform cosmetic bulk moves while V3 is stabilizing.

New V3 domain/schema contracts belong under `docs/v3/`. Durable rationale belongs in `adr/`.

## PostgreSQL executable surfaces

Executable SQL does not live in `docs/`.

### Active V3 candidate

The active clean pre-baseline candidate is under:

```text
migrations/sql/v3_candidate/
```

It is installed by:

```bash
bash scripts/db/apply_v3_candidate.sh
```

CI installs it into a clean PostgreSQL 18 database and runs PostgreSQL-backed invariant/race/RLS tests. It is **not** yet production migration history and must not be called `0001_initial` until the freeze gate in `v3/02-pre-sql-contract.md` passes.

### Historical V2 design chain

The historical V2.6→V2.10 chain remains under:

```text
migrations/sql/design_chain/
```

Those files are pre-production design history, not permanent Alembic history and not the active candidate. CI validates them separately so useful historical SQL does not silently rot.

See `migrations/README.md` before changing SQL.

## Historical material

Everything under `legacy/` is historical and non-authoritative. Do not edit, move, delete, reformat, or implement directly from it unless explicitly requested.
