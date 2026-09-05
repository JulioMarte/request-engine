# Release and migration archaeology disposition

Status: **current architecture decision record for the system-optimization phase**.

This inventory records whether V2/V3/feature-era release artifacts participate in the current Request Engine or only preserve provenance from an earlier release process. Historical naming is not itself a reason to remove an artifact; current consumption and protected guarantees decide the disposition.

## Classification vocabulary

- `CURRENT`: executed or loaded by the accepted current product/runtime/CI path.
- `GENERIC_BUT_MISNAMED`: protects a current generic guarantee but carries obsolete release naming or placement.
- `HISTORICAL`: useful provenance for a prior design/release, but must not constrain current HEAD structurally.
- `DEAD`: no current consumer and no unique current guarantee; Git history is the appropriate reconstruction mechanism.
- `ADMINISTRATIVE_ZOMBIE`: no longer part of current product assurance, but still operationally required by repository administration and therefore unsafe to remove until that external requirement changes.

## Current execution roots

The accepted current proof roots are:

1. `.github/workflows/ci.yml`;
2. `scripts/ci/ci_jobs.py` for Python quality and the temporarily retained V2-history lane;
3. `scripts/ci/run_current_product.sh` for PostgreSQL current-product proof;
4. Alembic `upgrade head` for the accepted schema graph.

A script that is only called by another disconnected historical script does not become current merely because the historical cluster is internally connected.

## `scripts/release/**`

### `GENERIC_BUT_MISNAMED` -> moved to current ownership

The former:

- `scripts/release/scan_v3_secrets.py`
- `scripts/release/scan_v3_python_security.py`

protect generic repository/source security properties and are invoked by current `python-quality`. They contain no V3 release semantics. Their current homes are:

- `scripts/security/scan_secrets.py`
- `scripts/security/scan_python_security.py`

The canonical CI consumer points only to the generic locations.

### `DEAD` on current HEAD

The remaining `scripts/release/**` Phase6/V3 proof machinery is retired from current HEAD. This includes the candidate-freeze, final-release, evidence-manifest, release-runtime, public-V3-compatibility, mutation/adversarial, historical query-plan, invariant-registry and artifact-validation tooling.

Reasoning:

- the frozen V3 workflow and historical proof suite were already retired;
- current `.github/workflows/ci.yml` has no release-proof lane;
- current `scripts/ci/ci_jobs.py` has no V3 release job after the security scanners are moved;
- `scripts/ci/run_current_product.sh` proves current PostgreSQL behavior directly against the repository Alembic head rather than composing Phase6 G01-G20 artifacts;
- keeping a self-contained historical proof cluster executable on current HEAD adds a second apparent release authority without adding current coverage.

Historical reconstruction remains available from Git history and the historical release documentation. Current HEAD should not carry executable release machinery solely so an old release can be regenerated from a different tree.

## `scripts/db/**`

### `ADMINISTRATIVE_ZOMBIE`

- `scripts/db/apply_design_chain.sh`

The script applies historical V2 design SQL and is still called only because the active `Request Engine - Development Integration` ruleset requires the exact status context `PostgreSQL 18 V2 design history`. It is not part of current-product PostgreSQL assurance. Remove the ruleset requirement first; then remove the workflow job, `postgres-v2-history` CI job, this script, and `migrations/sql/design_chain/**` as one coherent administrative cleanup.

### `DEAD` on current HEAD

The V3 candidate construction/proof helpers are not part of Alembic current-product migration or current CI and have been removed:

- `scripts/db/apply_v3_candidate.sh`
- `scripts/db/audit_v3_catalog.py`
- `scripts/db/build_v3_initial_candidate.py`
- `scripts/db/prove_v3_candidate_bootstrap.sh`
- `scripts/db/prove_v3_initial_equivalence.sh`
- `scripts/db/v3_schema_fingerprint.py`

They supported construction/proof of the historical V3 candidate and final baseline. Current schema validation uses Alembic and the current-product suites. Their historical implementation remains in Git history.

## Migration SQL/provenance

### `CURRENT`

The following are executable inputs to the accepted Alembic graph and must not be deleted merely because their names encode feature/release provenance:

- `migrations/versions/**` in the single accepted Alembic graph;
- `migrations/v3_initial_payload.py`;
- `migrations/sql/v3_initial/**`;
- `migrations/f2_steps/**`;
- `migrations/s0d_steps/**`.

`0001_initial.py` loads `v3_initial_payload.py`, and that loader reads the `v3_initial` payload parts with a byte-length and SHA-256 check. `0004_f2_discovery` imports and executes the F2 step modules. `0030_s0d_federated_identity` imports and executes the S0d step modules. Removing any of those inputs before a deliberate rebaseline would break `alembic upgrade head`.

### `ADMINISTRATIVE_ZOMBIE` pending V2 ruleset cleanup

- `migrations/sql/design_chain/**`.

This directory is historical architecture consumed only by `scripts/db/apply_design_chain.sh` and therefore by the V2-history status check that repository administration still requires. It is not the current schema source of truth.

### `HISTORICAL` -> removable after current guardrail reconciliation

- `migrations/sql/v3_candidate/**`.

The V3 candidate SQL was the construction chain from which the V3 baseline was produced. It is not loaded by the current Alembic graph. Its old application/proof helpers have been removed. The shared-capacity documentation contract has been redirected from candidate SQL paths to current Booking code and tests, so this directory may now leave current HEAD without weakening that current guardrail.

## `docs/release/**`

Classification: `HISTORICAL`.

These documents answer what the V3 release process proved, froze, or planned at that time. They are not current architecture or release authority. Current maps and agent instructions must not route ordinary work through them. The directory must identify itself explicitly as historical because commands and paths inside old release documents may no longer exist on current HEAD.

## V3/Fx-named tests

Historical naming does not imply historical semantics. Suites explicitly executed from `scripts/ci/run_current_product.sh` are `CURRENT` even when their path contains `v3_`, `f1_`, `f2_`, `f3_`, `f4_`, or `f5_`.

A V3/Fx-named PostgreSQL suite that is not in the current-product gate requires a guarantee-by-guarantee disposition before deletion. Being omitted from the gate is evidence of unclear ownership, not by itself evidence that the assertions are obsolete.

Renaming current suites is optional navigation work, not a correctness requirement. Do not churn hundreds of test paths merely to erase provenance labels. Rename only when the old name materially obscures the owned current capability and all direct consumers can be changed coherently.

## Rebaseline boundary

This archaeology pass does **not** authorize replacing `0001_initial`, deleting its payload, flattening the current Alembic graph, or deleting step modules imported by current revisions. A database rebaseline requires the separate schema audit and proof obligations in `docs/architecture/system-optimization-mode.md`.

The governing rule remains:

> historical release machinery may disappear from current HEAD; current guarantees may not disappear silently.
