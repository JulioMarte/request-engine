# Database migrations

This directory owns executable PostgreSQL schema evolution.

## Current state: pre-baseline design

Request Engine has not yet declared a production schema baseline. The historical V2.6→V2.10 executable design chain is preserved under:

```text
migrations/sql/design_chain/
```

Apply it in order when validating the current DBA design:

```text
03-postgresql-schema.sql
04-postgresql-v2.7-hardening.sql
05-postgresql-v2.8-hardening.sql
06-postgresql-v2.9-integrity.sql
08-postgresql-v2.10-access-surface.sql
```

These files explain how the physical design evolved. They are **not** considered production Alembic history.

## Baseline rule

When the domain/schema freeze gate is satisfied and before the first production deployment:

1. apply the complete design chain to a clean PostgreSQL 18 database;
2. validate the full invariant/race/privilege test suite;
3. produce one reviewed `0001_initial` Alembic baseline representing the final state directly;
4. verify clean install from that baseline matches the approved schema;
5. preserve all later production migrations append-only.

Do not force future deployments to replay design mistakes that existed only before production.

## Alembic

`env.py` and `script.py.mako` establish the migration environment now, but `versions/` intentionally contains no production revision until baseline freeze.

Runtime schema changes after baseline must go through reviewed Alembic revisions. Do not apply ad-hoc manual DDL to production.

## SQL ownership

PostgreSQL object responsibilities remain:

```text
request_engine  authoritative model and integrity
request_read    versioned read contracts
request_cmd     narrow consistency primitives
request_admin   diagnostics/operations
```

See `docs/07-database-access-contract.md`.
