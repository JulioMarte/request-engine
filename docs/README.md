# Request Engine — current documentation

This folder contains the authoritative product/domain/architecture design for the current Request Engine rebuild.

## Authoritative documents

Read in this order:

1. `00-product-definition.md` — product boundaries, vocabulary, ownership and domain invariants.
2. `01-architecture-v2.md` — transactional modular-monolith architecture, concurrency, command protocols, workers and integrations.
3. `02-pre-sql-domain-contract.md` — normative cardinalities, serialization roots, transaction proofs and invariant matrix.
4. `07-database-access-contract.md` — normative Python ↔ PostgreSQL boundary, Unit of Work, repositories, read views and narrow DB primitives.
5. `09-python-module-architecture.md` — normative physical Python repository/module layout and import boundaries.
6. `10-module-ownership-map.md` — normative mapping from domain concepts/commands/DB surfaces to Python module ownership.

The domain and transaction contracts have precedence over implementation convenience. SQL implements the contracts; it must not silently redefine them.

### Physical layout clarification

`01-architecture-v2.md` established the modular-monolith dependency direction. Its original illustrative horizontal folder tree is superseded for Python **physical organization only** by `09-python-module-architecture.md`.

The semantic rule remains:

```text
entrypoint/adapter
      ↓
application command/query
      ↓
domain rules + explicit ports
      ↓
PostgreSQL/adapters
```

The new physical layout groups those layers inside business modules to improve maintainability; it does not change transactional boundaries or introduce microservices.

## PostgreSQL executable design chain

Executable SQL no longer lives in `docs/`. The current pre-baseline V2.6→V2.10 design chain is under `migrations/sql/design_chain/` and is applied in this order:

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
