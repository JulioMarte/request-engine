# Request Engine — current documentation

This folder is the system of record for the current Request Engine product/domain/architecture design. Agent instruction files should point here rather than duplicate these documents.

## Authoritative documents

Read according to the task, using this precedence when rules overlap:

1. `00-product-definition.md` — product boundaries, vocabulary, ownership and domain invariants.
2. `01-architecture-v2.md` — transactional modular-monolith architecture, concurrency, command protocols, workers and integrations.
3. `02-pre-sql-domain-contract.md` — normative cardinalities, serialization roots, transaction proofs and invariant matrix.
4. `07-database-access-contract.md` — normative Python ↔ PostgreSQL boundary, Unit of Work, repositories, read views and narrow DB primitives.
5. `09-python-module-architecture.md` — normative physical Python repository/module layout and import boundaries.
6. `10-module-ownership-map.md` — normative mapping from domain concepts/commands/DB surfaces to Python module ownership.

The domain and transaction contracts have precedence over implementation convenience. SQL implements the contracts; it must not silently redefine them.

## Architecture Decision Records

`adr/` records durable rationale for hard-to-reverse architectural decisions. ADRs explain why the architecture exists; they do not replace the detailed normative contracts above.

Current accepted decisions include:

- modular monolith instead of premature microservices;
- smart PostgreSQL with Python-owned command orchestration;
- module-first Python physical organization;
- repository documentation as the canonical knowledge system for coding agents.

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

The numbered canonical documents are intentionally retained while the domain/schema is still being frozen because many invariant references and design-chain comments point to them. Do not perform a cosmetic bulk move into new directories until the contracts stabilize; that would create link churn without changing architecture.

New durable rationale belongs in `adr/`. New operational documentation should be grouped by purpose rather than extending the historical numbering indefinitely.

## PostgreSQL executable design chain

Executable SQL does not live in `docs/`. The current pre-baseline V2.6→V2.10 design chain is under `migrations/sql/design_chain/` and is applied in this order:

```text
03-postgresql-schema.sql
04-postgresql-v2.7-hardening.sql
05-postgresql-v2.8-hardening.sql
06-postgresql-v2.9-integrity.sql
08-postgresql-v2.10-access-surface.sql
```

These are pre-production design deltas, not permanent Alembic production history. See `migrations/README.md` for the baseline/squash rule.

## Historical material

Everything under `legacy/` is historical and non-authoritative. Do not edit, move, delete, reformat, or implement directly from it unless the user explicitly requests an archive edit.
