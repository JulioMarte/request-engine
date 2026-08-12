# Database migrations

This directory owns executable PostgreSQL schema evolution.

## Current state: pre-baseline V3 transition

Request Engine has not yet declared a production schema baseline.

The historical V2.6→V2.10 executable design chain is preserved under:

```text
migrations/sql/design_chain/
```

Apply it in order only when validating or comparing the V2 DBA design:

```text
03-postgresql-schema.sql
04-postgresql-v2.7-hardening.sql
05-postgresql-v2.8-hardening.sql
06-postgresql-v2.9-integrity.sql
08-postgresql-v2.10-access-surface.sql
```

These files explain how the V2 physical design evolved. They are **not** production Alembic history and they are **not** the V3 baseline candidate.

## V3 transition rule

Do not keep extending the V2 chain with `v2.11`, `v2.12`, etc. merely to preserve speculative pre-production abstractions.

The V3 process is:

1. inventory every V2 table/view/function/trigger as `KEEP`, `SIMPLIFY`, `REPLACE`, `DEFER`, or `DELETE_FROM_BASELINE`;
2. preserve proven SQL patterns/guarantees, not obsolete object shapes;
3. construct a clean reduced V3 candidate schema for the accepted baseline capabilities;
4. implement the reduced V3 invariant/race suite against PostgreSQL 18;
5. validate the proof verticals from `docs/11-capability-first-v3.md`;
6. only then produce a reviewed `0001_initial` Alembic baseline.

There is no production migration compatibility requirement yet. Optimize the pre-baseline redesign for conceptual integrity, correctness and testability.

See `docs/12-v3-transition-plan.md` and `docs/v3/sql-disposition.md`.

## Baseline rule

Before the first production deployment:

1. apply the complete approved V3 candidate to a clean PostgreSQL 18 database;
2. validate the full V3 invariant/race/privilege/reliability test suite;
3. produce one reviewed `0001_initial` Alembic baseline representing the final state directly;
4. verify clean install from that baseline matches the approved schema;
5. preserve every later production migration append-only.

Do not force future deployments to replay design mistakes that existed only before production.

## Alembic

`env.py` and `script.py.mako` establish the migration environment now, but `versions/` intentionally contains no production revision until baseline freeze.

Runtime schema changes after baseline must go through reviewed Alembic revisions. Do not apply ad-hoc manual DDL to production.

## SQL ownership

PostgreSQL object responsibilities remain conceptually:

```text
request_engine  authoritative model and integrity
request_read    versioned read contracts
request_cmd     narrow consistency primitives
request_admin   diagnostics/operations
```

V3 may replace individual V2 objects/views/functions while preserving this boundary.

See `docs/07-database-access-contract.md`.
