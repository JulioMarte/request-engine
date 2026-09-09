# Release and migration archaeology disposition

Status: **closed after the audited pre-production rebaseline**.

This record distinguishes current executable authority from historical provenance. Historical naming is not itself a reason to remove an artifact; current consumption and protected guarantees decide the disposition.

## Classification vocabulary

- `CURRENT`: executed or loaded by accepted product/runtime/CI paths.
- `HISTORICAL`: useful provenance but not current executable authority.
- `DEAD`: no current consumer and no unique current guarantee; Git history is the reconstruction mechanism.
- `ADMINISTRATIVE_ZOMBIE`: historical behavior still required by an external repository rule/status context.

## Current execution roots

1. `.github/workflows/ci.yml`;
2. `scripts/ci/ci_jobs.py` for Python quality and the retained V2-history lane;
3. `scripts/ci/run_current_product.sh` for current PostgreSQL product proof;
4. `migrations/versions/**` for the current Alembic graph;
5. `migrations/baseline/**` for immutable `0001_initial` payload integrity.

A script called only by disconnected historical machinery is not current merely because that machinery is internally self-consistent.

## Accepted migration authority

### `CURRENT`

```text
migrations/versions/0001_initial.py
migrations/baseline/**
```

The pre-production rebaseline is complete. `0001_initial` installs the checksummed baseline and exact six-role topology from a clean PostgreSQL 18 cluster. Future schema evolution appends `0002+`; it does not rewrite this baseline.

### Removed as `DEAD`

The following were required only to construct or replay the superseded pre-rebaseline graph and are intentionally absent from current HEAD:

- `migrations/v3_initial_payload.py`;
- `migrations/sql/v3_initial/**` Base85 payload;
- `migrations/sql/v3_candidate/**` construction chain;
- `migrations/f2_steps/**` helpers formerly imported by old revision `0004`;
- `migrations/s0d_steps/**` helpers formerly imported by old revision `0030`;
- historical Alembic revisions `0002..0050` superseded by the accepted baseline;
- V3 candidate/baseline construction scripts that no current proof executes.

Their provenance remains in Git history and historical release documentation. Keeping them executable beside the accepted baseline would create a false second migration authority.

## V2 design history

### `ADMINISTRATIVE_ZOMBIE`

```text
scripts/db/apply_design_chain.sh
migrations/sql/design_chain/**
```

These files are **not** current schema authority. They remain because the repository still requires the exact status context `PostgreSQL 18 V2 design history`, and `scripts/ci/ci_jobs.py` executes the design chain to satisfy that requirement.

Remove them only as one coherent administrative change after the external status/ruleset requirement is retired. Until then, they are deliberately preserved historical evidence.

## Release scripts and historical V3 proofs

The old executable V3 release/candidate machinery is not part of current product assurance. Generic security checks were moved to generic ownership; release-specific freeze/evidence/bootstrap machinery belongs in Git history rather than current execution paths.

Historical release documents may describe commands and files that no longer exist. They answer what an earlier release process proved; they are not instructions for current schema work.

## V3/Fx-named current tests

Historical path names do not automatically imply historical semantics. Tests explicitly executed by `scripts/ci/run_current_product.sh` remain `CURRENT` when they protect current booking, queue, worker, tenancy, recovery, concurrency or security guarantees.

Renaming those suites is optional navigation work and should not create large path churn merely to erase provenance labels. Remove or rename only when current ownership/guarantee mapping is clear.

## Permanent boundary after rebaseline

The accepted baseline and current HEAD have different responsibilities:

```text
0001_initial + migrations/baseline
    immutable bootstrap history

0002+ current Alembic head
    normal product evolution
```

CI must prove both without requiring them to remain identical forever. A future destructive rebaseline would require a new explicit schema audit and reproduction cycle; it must not emerge accidentally from ordinary cleanup or feature work.

The governing rule remains:

> historical release machinery may disappear from current HEAD; current guarantees may not disappear silently.
