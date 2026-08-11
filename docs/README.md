# Request Engine — current documentation

This folder contains the authoritative architecture and PostgreSQL design for the current Request Engine rebuild.

## Authoritative documents

Read in this order:

1. [`00-product-definition.md`](00-product-definition.md) — product boundaries, vocabulary, ownership and domain invariants.
2. [`01-architecture-v2.md`](01-architecture-v2.md) — target modular-monolith architecture, concurrency, transactions, workers and integrations.
3. [`02-pre-sql-domain-contract.md`](02-pre-sql-domain-contract.md) — normative cardinalities, serialization roots, transaction proofs and invariant matrix.
4. [`07-database-access-contract.md`](07-database-access-contract.md) — normative Python ↔ PostgreSQL boundary, Unit of Work, repositories, read views and narrow DB primitives.

The domain/architecture documents have precedence over physical SQL. SQL implements the contract; it must not silently redefine it.

## PostgreSQL 18+ migration chain

`08-postgresql-v2.10-access-surface.sql` is a delta, not a clean-install schema. Apply the SQL files in this exact order:

```text
03-postgresql-schema.sql
        ↓
04-postgresql-v2.7-hardening.sql
        ↓
05-postgresql-v2.8-hardening.sql
        ↓
06-postgresql-v2.9-integrity.sql
        ↓
08-postgresql-v2.10-access-surface.sql
```

The final physical model uses PostgreSQL as authoritative transactional storage while Python/FastAPI owns application commands and orchestration. `request_read` exposes versioned read contracts; `request_cmd` contains only narrow consistency primitives; neither is a replacement application backend.

## Historical material

All retired architecture documentation is isolated under [`legacy/`](legacy/).

**Do not edit, move, delete, reformat or implement directly from `docs/legacy/**` unless the user explicitly asks to modify the historical archive.** The local [`legacy/AGENTS.md`](legacy/AGENTS.md) makes this rule explicit for tools and coding agents.

Anything in `legacy/` is non-authoritative regardless of how polished or detailed it appears.
