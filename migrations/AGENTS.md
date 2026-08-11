# Migration agent rules

Before editing anything here, read:

1. `docs/02-pre-sql-domain-contract.md`
2. `docs/07-database-access-contract.md`
3. `migrations/README.md`

Rules:

- PostgreSQL target is 18+.
- The files under `sql/design_chain/` are pre-baseline design history. Preserve their historical meaning; do not pretend they are production Alembic revisions.
- Before baseline freeze, a DBA design change may add a new design delta when necessary. At freeze, squash the approved final state into `0001_initial`.
- After production baseline exists, never rewrite applied migration history; add a new revision.
- Critical tenant relationships keep DB-provable tenant equality.
- Preserve typed FKs, stable serialization authorities, append-oriented facts, canonical lock protocols, and deny-by-default interface privileges.
- `request_cmd` functions must remain narrow data-centric primitives inside Python-owned transactions.
- SQL changes require PostgreSQL-backed tests for affected invariant IDs.
- Never weaken a constraint because application code already checks it unless the canonical contract explicitly moves that invariant to application policy.
