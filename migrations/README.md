# Database migrations

This directory owns executable PostgreSQL schema evolution and the retained provenance needed to prove how the V3 production baseline was derived.

## Current state: released V3 baseline

Request Engine V3 has a production schema baseline.

There are now three intentionally different SQL/history tracks:

```text
migrations/sql/design_chain/   historical V2.6→V2.10 executable design history
migrations/sql/v3_candidate/   frozen V3 candidate used by freeze/equivalence proof
migrations/versions/           production Alembic history beginning at 0001_initial
```

### Production Alembic history

`migrations/versions/0001_initial.py` is the reviewed V3 production baseline. G17 proved it structurally, behaviorally and at runtime equivalent to the frozen candidate on PostgreSQL 18.

After release, `0001_initial` is immutable migration history:

- do not rewrite, regenerate or squash it;
- do not edit it to accommodate a later feature;
- do not back-port post-release candidate deltas into it;
- represent every later production schema change as a new append-only Alembic revision;
- preserve upgrade-from-baseline correctness as part of future migration review.

A clean production-style database should be constructed through Alembic, not by treating the frozen candidate apply script as the normal deployment path.

### Frozen V3 candidate provenance

The complete frozen V3 candidate remains under:

```text
migrations/sql/v3_candidate/
```

and can be installed in release-proof/equivalence contexts with:

```bash
bash scripts/db/apply_v3_candidate.sh
```

The release freeze binds the complete 43-file candidate inventory plus its source/tree provenance, apply script and schema-fingerprint machinery. That directory is retained because it is the candidate side of the G17/G20 evidence chain.

It is **not** the mutable post-release schema-development line. Do not append ordinary post-release migrations there and do not revise frozen files merely to keep them cosmetically aligned with later Alembic history.

The candidate was derived from the canonical V3 contracts and their accepted convergence/hardening work, including:

- `docs/v3/01-capability-contracts.md`;
- `docs/v3/02-pre-sql-contract.md`;
- `docs/v3/03-db-contract-convergence.md`;
- later accepted V3 authority/concurrency/runtime/reliability contracts and release-proof fixes;
- `docs/v3/sql-disposition.md` as historical V2→V3 disposition context.

Some documents in that chain describe pre-baseline decisions in the tense in which they were made. Their historical wording does not make the released candidate mutable again.

### Historical V2 design chain

The V2.6→V2.10 design chain remains under `migrations/sql/design_chain/` and may continue to be installed in a separate CI job so useful historical SQL knowledge does not silently rot.

It is **not** production Alembic history and must not receive new `v2.11`, `v2.12`, etc. deltas by default.

## Post-baseline schema evolution rule

For every production schema change after V3 release:

1. update the owning canonical domain/architecture contract when semantics or invariants change;
2. create a new append-only Alembic revision under `migrations/versions/`;
3. preserve `0001_initial` unchanged;
4. add/update PostgreSQL-backed tests for affected invariants, races, RLS/privileges and runtime behavior;
5. prove both fresh bootstrap to head and supported upgrade from the previous production head;
6. preserve rollback policy explicitly where downgrade is supported; do not fake reversibility for destructive or semantically irreversible migrations;
7. keep historical `design_chain/` and frozen `v3_candidate/` provenance separate from current production evolution.

The old pre-baseline rule that candidate files could be freely consolidated is closed. Any future deliberate re-baselining would require a new explicit release/migration policy; it must not be inferred from the V3 development process.

## V3 baseline proof

The V3 release closed the baseline gates with:

- G01–G20 `PASS`;
- frozen 43-file candidate inventory;
- reviewed `0001_initial` SQL SHA-256 `502c98fcce5b5480a3e8f34804ce3a61495e679811a3ac6d0be4872107c34c88`;
- canonical structural fingerprint `8345eec114eb4af2184c0796debece536e27d7fb4851f77811b2721df1afd877`;
- G17 behavioral proof with 466 tests on candidate and 466 tests on `0001_initial`, zero failures/errors/skips and identical test inventory;
- production-like runtime-role bootstrap proof;
- final G20 evidence `VALID` / `READY` for the release promotion candidate.

See `docs/release/v3-release-gates.md` and `docs/release/v3-current-release-roadmap.md` for release provenance.

## SQL ownership

PostgreSQL object responsibilities remain:

```text
request_engine  authoritative relational state + integrity/RLS
request_read    versioned capability-oriented read contracts
request_cmd     narrow consistency/worker/idempotency primitives
request_admin   explicit diagnostics/operations
```

Python remains owner of business-command orchestration and transaction framing. PostgreSQL protects structural truth, concurrency, leases/fencing and local invariant backstops.

No external/provider I/O occurs while authoritative DB locks are held.
