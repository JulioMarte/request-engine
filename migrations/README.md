# Database migrations

This directory owns executable PostgreSQL schema evolution.

## Current state: V3 pre-baseline candidate

Request Engine has **not** declared a production schema baseline.

There are now two intentionally different SQL tracks:

```text
migrations/sql/design_chain/   historical V2.6→V2.10 executable design history
migrations/sql/v3_candidate/   active clean V3 pre-baseline candidate
```

### Active V3 candidate

Apply to a clean PostgreSQL 18 database with:

```bash
bash scripts/db/apply_v3_candidate.sh
```

Current candidate order:

```text
001-foundation.sql
002-schema.sql
003-integrity.sql
004-worker-primitives.sql
005-read-access.sql
006-capacity-hardening.sql
007-contract-convergence.sql
```

The candidate is derived from:

- `docs/v3/01-capability-contracts.md`;
- `docs/v3/02-pre-sql-contract.md`;
- `docs/v3/03-db-contract-convergence.md`;
- `docs/v3/sql-disposition.md`.

`03-db-contract-convergence.md` is a temporary normative pre-baseline amendment for the explicitly listed booking/database decisions. Its decisions must be folded into the canonical V3 contract before `0001_initial` is frozen.

The candidate is deliberately smaller than V2 and excludes deferred concepts such as universal Workflow/OutcomeScope, ReservationItem, CapacityAuthority, ResourceAllocation, CapacityPool, advanced Fulfillment, payments and dispatch.

The candidate is validated independently in CI against PostgreSQL 18 plus real DB/race/RLS tests under `tests/db/`.

### Historical V2 design chain

The V2.6→V2.10 design chain remains under `migrations/sql/design_chain/` and is still installed in a separate CI job so useful historical SQL knowledge does not silently rot.

It is **not** production Alembic history and must not receive new `v2.11`, `v2.12`, etc. deltas by default.

## Candidate evolution rule

Because no production baseline exists yet, candidate files may still be revised/consolidated during review. Do not preserve a bad pre-production object shape for migration compatibility that does not exist.

However, changes must preserve discipline:

1. update the V3 contract first when semantics/invariants change;
2. change the clean candidate;
3. add/update PostgreSQL-backed tests for every affected `V3-Ixx` invariant/race;
4. keep CI green on a clean PG18 install;
5. do **not** create `0001_initial` merely because the candidate applies.

## `0001_initial` gate

Before the first production deployment:

1. the complete approved V3 candidate installs on clean PostgreSQL 18;
2. critical V3 invariant/race/privilege/reliability tests pass;
3. required application vertical slices from `docs/v3/02-pre-sql-contract.md` execute end to end;
4. candidate SQL is consolidated/reviewed so hardening deltas become one intentional final state;
5. one Alembic `0001_initial` is generated/hand-reviewed to represent that final state directly;
6. clean install from `0001_initial` is verified equivalent to the approved candidate;
7. all later production migrations become append-only history.

`migrations/versions/` therefore remains intentionally empty for now.

## SQL ownership

PostgreSQL object responsibilities are:

```text
request_engine  authoritative relational state + integrity/RLS
request_read    versioned capability-oriented read contracts
request_cmd     narrow consistency/worker/idempotency primitives
request_admin   explicit diagnostics/operations
```

Python remains owner of business-command orchestration and transaction framing. PostgreSQL protects structural truth, concurrency, leases/fencing and local invariant backstops.

No external/provider I/O occurs while authoritative DB locks are held.
