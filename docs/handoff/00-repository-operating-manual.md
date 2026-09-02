# Handoff 00 — Repository Operating Manual

Audience: the next engineer or AI agent working in this repo with zero context.
Style: what actually breaks, not what should work in theory. Everything below was
verified against the repo state at `development` merge `a8760d9f` (Sep 2026).

## 1. Branch and lane discipline (non-negotiable, mechanically enforced)

- `development` is the canonical integration branch. `main` is release-only.
  Never push to either. All work happens on a feature branch with a PR **targeting
  `development`**.
- There is **one serialized integration lane**. The file
  `.github/development-integration-lane` must contain exactly the name of the branch
  that is the head of the open ordinary PR. You claim the lane by setting it (commit
  `063332fc` is an example of a lane-claim commit). Before starting work, fetch and
  confirm no other ordinary workstream still owns the lane. `tests/architecture/
  test_branch_workflow_contract.py` fails the PR otherwise.
- Merge evidence is **exact-head CI**: all 7 GitHub Actions jobs green on the exact
  commit being merged. CI also runs on pushes to `development`/`main` so every merged
  SHA carries its own canonical run.

The 7 CI jobs (`.github/workflows/ci.yml`) and what each proves:

1. **python-quality** — Python quality and architecture (12 steps, see §3).
2. **observability-contract** — the pinned OpenTelemetry runtime launches the process
   zero-code (`scripts/observability/run_with_otel.py --check`) and the SDK/exporter
   smoke test passes.
3. **postgres-v2-history** — the historical V2 design chain SQL
   (`scripts/db/apply_design_chain.sh`) still applies on PostgreSQL 18.
4. **postgres-v3-bootstrap-proof** — the frozen V3 candidate bootstraps repeatedly and
   cleanly from scratch.
5. **postgres-v3-candidate-proof** — frozen V3 compatibility:
   `scripts/ci/run_v3_frozen_compatibility.sh` proves the immutable baseline is
   untouched, the released tree still reproduces its own test suite on its own schema,
   and the current public API is a superset of the released one. Plus
   `tests/historical` provenance tests.
6. **postgres-production-head** — the current product at Alembic head
   (`scripts/ci/run_current_product.sh`, includes `tests/e2e/`) works on PostgreSQL 18.
7. **postgres-v3-candidate** — the aggregate gate: requires all of the above
   (`scripts/ci/require_successful_needs.py`) and publishes the
   `Request Engine / CI aggregate` commit status that branch protection reads.

## 2. The traps that actually cost CI cycles

Each as: **trap → what fails → what to do.**

### 2.1 The immutable V3 baseline files
- **Trap:** editing any of the paths in `IMMUTABLE_V3_PATHS`
  (`scripts/ci/run_v3_frozen_compatibility.sh`): `migrations/versions/0001_initial.py`,
  `migrations/v3_initial_payload.py`, `migrations/sql/v3_initial/`,
  `migrations/sql/v3_candidate/`, `scripts/release/v3_public_api_contract_baseline.py`,
  `docs/release/v3-candidate-freeze.json`.
- **Fails:** job 5; the script diffs these paths against the pinned release SHA
  `07da8be8...` and exits if the diff is non-empty.
- **Do:** NEVER edit `v3_public_api_contract_baseline.py` to "register" a new
  capability — that is the frozen baseline of the released API. Post-baseline
  capabilities are tolerated by the wrapper
  `scripts/release/prove_v3_public_api_compatibility.py`: released capabilities must
  remain exact, **additions are allowed** and fail only if something released is
  removed or changed.

### 2.2 Frozen literal error codes in `entrypoints/http/errors.py`
- **Trap:** moving HTTP error handlers or their `code="..."` literals out of
  `entrypoints/http/errors.py` into another module, or refactoring the literal strings
  away.
- **Fails:** job 5. The frozen V3 public API proof scans `errors.py` **textually** for
  the literal error codes, including the `code = "not_found"` / `method_not_allowed` /
  `http_error` assignments inside `http_exception_handler`.
- **Do:** keep the literals in-file. The handlers may delegate to
  `platform/http/errors.py` helpers and handler *registration* may live in
  `error_handlers.py` (that split was accepted after it broke CI once — commit
  `ff09edbc`), but the codes themselves stay. New files in `entrypoints/http/` also
  need an allowlist entry (see 2.4).

### 2.3 Effective line budget (the silent one)
- **Trap:** adding even one line to a legacy oversized file, or writing a new file over
  120 effective lines. "Effective lines" = tokenize-based code lines; comments and
  blank lines are free, **docstrings count**. Limits: soft target 100, hard max 120.
- **Fails:** the `file-budget` step of python-quality *(superseded: the file budget is now a
  non-blocking REVIEW_CANDIDATE signal, not a hard failure; see docs/engineering-quality/)*:
  `scripts/ci/check_python_file_budget.py --base-ref origin/development`. Files already
  over 120 are **ratcheted**: they may not grow by a single line
  (`previous -> current` growth is a hard failure).
- **Do:** new code goes into new files. Fix legacy growth by extraction/splitting
  (see commits `d92d1a32`, `60ccfa91`, `ca07549f` — all are "compact back under the
  budget" fixes). Only `src/` and `tests/` are counted. In CI the base ref comes from
  `FILE_BUDGET_BASE_REF`; locally always pass `--base-ref origin/development` (the
  default is `HEAD^`, which only compares against your own last commit and can pass
  when CI will fail).

### 2.4 Architecture tests freeze shapes you wouldn't expect
- **Trap:** creating a new `.py` file under `src/request_engine/entrypoints/http/`.
- **Fails:** `tests/architecture/test_connection_surfaces.py` asserts the directory's
  file set is a subset of `ENTRYPOINT_ALLOWED_PYTHON`. Adding a file means adding it to
  that allowlist deliberately (this happened with `error_handlers.py`).
- **Trap:** naming a contract class `*View`, `*Body`, `*Row`, `*ORM` in a module
  `contracts` package, or using transport DTO shapes in domain/application/contracts.
- **Fails:** `tests/architecture/test_repository_governance_contract.py`
  (`FORBIDDEN_CONTRACT_SUFFIXES = ("Body", "View", "Row", "ORM")`).
- **Do:** transport DTOs (`*Body`, `*View`) belong to module `api` packages;
  contracts stay Pydantic-free. Read the failure message — these tests are
  intentionally explicit.

### 2.5 Documentation contract check
- **Trap:** touching a contract-sensitive file without updating its mapped normative
  doc. The mapping lives in `docs/architecture/documentation-contracts.toml`; e.g.
  changing `bootstrap/http.py` requires changing `docs/v3/12-cross-tenant-shared-
  capacity-design.md` in the same PR.
- **Fails:** `scripts/ci/check_documentation_contract.py` (step inside the
  architecture gate chain / runnable locally).
- **Do:** run `python scripts/ci/check_documentation_contract.py --base
  origin/development` before pushing. The required doc change must be a *true
  statement* about what changed, not a drive-by edit.

### 2.6 Test lanes are physically separated
- `tests/modules/` — **DB-free module unit tests. No PostgreSQL allowed.** They run in
  python-quality (step `modules`).
- `tests/e2e/` and `tests/integration/` — real PostgreSQL 18, marked `-m postgres`;
  they run in jobs 5/6, not in python-quality. A test that needs a DB but isn't marked
  will not run where you think it will; a test marked postgres will not run locally
  without a PostgreSQL 18 server.
- `tests/architecture/` — runs in python-quality; this is where boundary/naming rules
  (2.4) bite.
- `tests/historical/` — pinned release provenance; runs in job 5 only.
- Every postgres proof must start and end from a clean database state via
  `tests/conftest.py` (leaked locks/rows fail fast).

### 2.7 Windows development limitation: SIGKILL crash-recovery tests
- **Trap:** `tests/integration/v3_worker_runtime/test_process_crash_recovery.py` and
  `test_process_crash_recovery_other_families.py` (the latter parametrized over the
  `outbox` and `provider_event` families — three test cases total) kill their own
  process with `os.kill(os.getpid(), signal.SIGKILL)`.
- **Fails locally on Windows:** `signal.SIGKILL` does not exist there. This is
  expected, not a bug.
- **Do:** do not chase these locally. They prove the worker lease/fencing recovery
  guarantee (INV-WORKER-001) and run in the PostgreSQL CI lanes only.

### 2.8 Migrations
- Append-only after release. `0001_initial` is immutable release history; never edit
  it or the frozen candidate SQL (see 2.1).
- Alembic's version table column is `varchar(32)`: **keep revision ids ≤ 32 chars**.
  `0025_s0b2_authority_and_history` (31 chars) is already at the edge.
- Local dev-DB rebuild when schema state is broken or stale:
  drop the application schemas and Alembic bookkeeping, then re-upgrade:
  ```sql
  DROP SCHEMA IF EXISTS request_engine, request_read, request_cmd, request_admin CASCADE;
  DROP TABLE IF EXISTS public.alembic_version;  -- actually: alembic_version lives in public
  ```
  then `MIGRATION_DATABASE_URL=postgresql+psycopg://... alembic upgrade head`
  (`MIGRATION_DATABASE_URL` is mandatory — `migrations/env.py` refuses without it).
  Expect the four application schemas; the fingerprint/bootstrap proof scripts
  (`scripts/db/`) assert exactly this schema set.

### 2.9 RLS + `SET ROLE` silent zero-row updates
- **Trap:** connecting as a role and doing `SET ROLE request_engine_*` without setting
  the tenant context. The session contract (`src/request_engine/platform/db/session.py`)
  issues `SELECT set_config('request_engine.organization_id', :org, true)` on every
  transaction.
- **Fails (silently, worse than failing):** an RLS-filtered `UPDATE` against the wrong
  or missing organization context matches **0 rows** — no error, no trigger fires, the
  command "succeeds" having done nothing.
- **Do:** in any hand-written SQL test or session, after `SET ROLE`, always set
  `set_config('request_engine.organization_id', '<org-uuid>', true)` in the same
  transaction before mutating. If an update mysteriously does nothing in a test, check
  the tenant context first.

## 3. Validation workflow

Narrowest relevant checks first, then the canonical lane:

```bash
python scripts/ci/ci_jobs.py python-quality   # 12 steps:
# file-budget, uv-sync, lockfile, ruff-lint, ruff-format, pyright, secret-scan,
# python-sast, dependency-audit, architecture, unit, modules
```

Then run the PostgreSQL selection that owns your proof (e.g. the relevant
`tests/integration/...` directory with `-m postgres`) per `docs/testing/README.md`.
Exact-head CI on the integration lane remains the only merge evidence; never report a
check as passed if it did not actually run against the intended environment — report
skipped/unavailable checks explicitly.

Before pushing, always run:

```bash
python scripts/ci/check_python_file_budget.py --base-ref origin/development
python scripts/ci/check_documentation_contract.py --base origin/development
```

## 4. The working pattern that has been effective

One slice at a time, fully closed:

1. Claim the lane (set `.github/development-integration-lane`), rebuild the branch
   from current `origin/development`.
2. Implementation subagents land **one coherent slice**, committed after each green
   validation run.
3. Independent adversarial review subagents — one security track, one evidence/test
   track — attack the slice.
4. Fix round addressing the findings.
5. Full validation (§3), push, exact-head CI green, merge into `development`, delete
   the work branch. Only then start the next slice.
6. If `development` moved meanwhile: reconcile/rebuild onto the new head and re-run
   CI before merging.

## 5. Where the rules live (read before editing, in this order)

`AGENTS.md` (repo root) → `docs/README.md` → the owning `docs/v3/<contract>.md` for
your slice → `docs/10-module-ownership-map.md` → the owning module's
`src/request_engine/modules/<module>/README.md` → `docs/testing/README.md` and
`docs/testing/evidence-authoring-guide.md` before touching tests →
`migrations/README.md` before touching schema.
