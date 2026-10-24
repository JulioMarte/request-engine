# Rebaseline 0047 — integrated-worktree validation

## Scope

The backend `feature/admin-dashboard-completion` worktree contains a pending
`git merge --no-ff --no-commit tmp/rebaseline-0047` from source HEAD
`afbbe397681732399702aad34da917e15d503018`, plus the clean-startup correction.
No final commit or push is made. `origin/development` was fetched and resolved to
`cb211a56e8948f0872952884927f49c2efb45e93`, already an ancestor of the work branch.
The candidate's four uncommitted formatting changes remain in its original worktree.
The final handoff has no unresolved merge paths: HEAD remains `afbbe397`,
MERGE_HEAD is `dcbd4ae4c801493e7ddb406eb362159e53a24b90`, and the intended changes
are staged. `.claude/worktrees/` remains untracked and unstaged. The user owns
the eventual merge commit and publication after verification is completed.

## Protected properties and changes

- Preserve the effective schema, role attributes/ACLs and normalized reference data
  of historical head 0047 in a clean independent PostgreSQL 18 installation.
- `Stack.require_known_revision` first checks relation existence, then separately
  reads the version table. The old CASE expression failed during PostgreSQL name
  resolution on a fresh database. Retired revisions are refused without migrating
  or deleting data; guidance points to a parallel project. `up` checks lineage
  before building, so refusal also precedes replacing an existing image tag.
- `tests/db/test_local_stack_revision_guard.py` executes the actual guard SQL on
  PostgreSQL for absent/empty/current/retired migration state and asserts that
  pre-existing sentinel data and migration state remain unchanged. It is included
  in the canonical current-product runner.
- `tests/unit/scripts/test_local_stack_startup.py` protects the orchestration
  refusal: the only Compose operation admitted before an unknown-lineage refusal
  is starting/waiting for PostgreSQL, never building or running a migration.
- Native baseline proof explicitly initializes UTF-8. Without `--encoding=UTF8`,
  the locale of the Linux CI user produced SQL_ASCII; Psycopg returned bytes for
  server version and SQLAlchemy failed before installing the baseline. The runner
  still creates an independent cluster, uses SCRAM/loopback, installs twice and
  performs every catalog and identity check. No proof is skipped.
- Existing authorization/capacity/worker assertions are not weakened. Historical
  migration-proof dispositions are in the owning rebaseline audit.

## Evidence

**PARTIAL_GREEN_OTHER_FAILURE / INFRASTRUCTURE_BLOCKED.** Neither complete lane
is certified. Earlier candidate evidence and old remote green do not certify
this uncommitted tree. Full local lanes do not replace exact-head GitHub CI.

### Independent effective-model reproduction — PASS

Two new `postgres:18` containers (18.6), `re-rb-verify-sol-a` and
`re-rb-verify-sol-b`, used the private `re-rb-verify-sol` network and no published
PostgreSQL ports. A installed the old source commit's complete chain to 0047;
B installed the integrated replacement to `0001_initial`. Neither was the
development database. The updated role exporter was used on both so the
`request_retention_%` namespace was included in both comparisons.

| Executed check | Result |
|---|---|
| `compare_schema_catalogs.py` | equivalent: 164 relations, 1,820 columns, 2,673 constraints, 442 indexes, 376 routines, 218 triggers, 118 policies |
| `compare_role_catalogs.py` | equivalent: 17 roles, zero memberships and role settings |
| `compare_seed_data_catalogs.py` | equivalent: 18 reference rows in five nonempty tables, 153 tables inspected |
| `pg_dump --schema-only --exclude-table=public.alembic_version`, guard-directive sanitization, `compare_exact_files.py` | byte-identical: 2,010,892 bytes, SHA-256 `c0637f8f0fb6fce3b0b16f3bc3a1fd8723f3d8f31d49f25e40a56ecc471a7deb` |

Schema comparison normalizes physical column-position gaps; reference-data
comparison normalizes only the accepted installation-local IDs/timestamps.
The dump comparison retains owners, ACLs and comments, excluding Alembic's
lineage bookkeeping and PostgreSQL's random psql guard directives.

### Clean startup — PASS, with final orchestration boundary noted

Executed on Windows using the existing Python environment:

```powershell
$env:RE_DEV_IMAGE_TAG = 'rebaseline-0047-sol-proof'
.\.venv\Scripts\python.exe scripts/dev/local_stack.py up `
  --project request-engine-rb-sol-proof --api-port 58300 --control-port 58301 `
  --console-port 58302 --gateway-port 58390
.\.venv\Scripts\python.exe scripts/dev/local_stack.py status `
  --project request-engine-rb-sol-proof
```

The new volume installed 0001, generated separate runtime logins, claimed the
instance through HTTP, provisioned the development organization/integration and
started the worker. API/control-plane/console/gateway health returned HTTP 200;
worker was running with zero restarts. The last later edit moves build after
the lineage check; its refusal ordering passed the unit regression, but a second
complete Docker startup after that ordering change was blocked by storage.
Generated credentials stayed in the ignored new project's state directory;
their values are not included in evidence.

### Canonical lanes — attempted completely, not certified

Linux runner image `request-engine-rebaseline-ci:20261023` extends the existing
local CI image with PostgreSQL 18.6 server binaries. It runs as the PostgreSQL
OS user, with `REQUEST_ENGINE_BASELINE_PG_BIN=/usr/lib/postgresql/18/bin`.
Current-product uses a separate PostgreSQL 18.6 container; its accepted-baseline
proof creates another temporary native cluster. There is no Docker socket,
development volume or source bind mount in this runner. A Git bundle clone plus
the uncommitted diff supplied the source without creating a snapshot commit.

Executed canonical commands from `/workspace/repo`:

```bash
uv run python scripts/ci/ci_jobs.py python-quality \
  --summary-output /evidence/python-quality-final.json \
  --log-dir /evidence/python-quality-final-logs
CURRENT_PRODUCT_CI_ARTIFACT_DIR=/evidence/current-product \
  bash scripts/ci/run_current_product.sh
```

- The first current-product attempt exposed the native SQL_ASCII issue above.
  After correction the full runner was restarted from its beginning. Baseline
  integrity (including both installation identities) and multidatabase both
  passed. The last accessible JUnit/log evidence contains **38 schema + 14
  business-info + 324 semantic-command tests passed, zero failures/skips**.
  Execution had proceeded beyond those groups; no final exit or proof-map result
  could be retrieved after Docker became unresponsive. No tail-only run or
  baseline-skipping launcher was used.
- Initial Python-quality attempts found strict typing errors in the newly added
  PostgreSQL regression and a 101-character docstring line. Both were corrected,
  not suppressed. A targeted Linux Pyright run for that regression returned
  **0 errors**. The complete canonical command was restarted; its final result
  became inaccessible when Docker stopped responding. This is not a full PASS.
- After the infrastructure block, the final Windows source passed
  `pytest tests/unit/test_baseline_loader.py
  tests/architecture/test_baseline_repository_contract.py
  tests/unit/scripts/test_local_stack_startup.py -q -p no:cacheprovider`:
  **10 passed in 0.58s**. Ruff check and format-diff for `local_stack.py` and both
  new regression files passed. Before the block, the real PostgreSQL guard
  regression passed all **four** absent/empty/current/retired cases.

### Infrastructure blocker and evidence retention

The Windows C: drive reported only **5,406,720 free bytes**. Removing solely this
session's temporary source bundle recovered it to **16,154,624 bytes**. The exact
growth attribution was not established. Docker `stats`, `version`, `ps` and a
stop request addressed exclusively to this session's new parallel/A/B containers
timed out (30 to 300 seconds). WSL could list the running distribution but could
not execute a shell within it. Both new and existing API health probes then
timed out; final development health is therefore not verified.

No global prune, Docker restart/reset, VHD deletion, existing-volume removal or
existing-project stop was performed. Cleanup of the new containers could not be
confirmed either. When Docker responds again, evidence remains under `/evidence`
in `re-rb-verify-sol-runner` (not a bind mount). Clean-start stdout/stderr are in
the private local temp directory as `rebaseline-clean-start.log`/`.err`.

**Resume:** free sufficient disk capacity without deleting retained project data,
restore Docker availability, recover the existing evidence, then recreate a
fresh isolated runner/database from the final worktree and rerun both complete
canonical commands above. Include the final added startup unit test in that
snapshot. Do not infer completion from an old exit file, partial JUnit packet or
the former candidate's evidence. Revalidate the parallel startup and original
development health; clean up only this session's explicitly named resources.

### Local semantic review

Scope: changed baseline loader/verification, revision guard and its regressions,
native initialization and associated documentation. Classification: CONTROLLED
lineage replacement; HARD authority/RLS/provenance/data-preservation guarantees
remain protected. The historical test dispositions are explicit in the audit.
The loader's declarative role/bootstrap phases and the local stack orchestrator
retain cohesive installation responsibilities; splitting them for file size
would add navigation without improving ownership. Disposition: **HEALTHY_AS_IS
for structure**, not a waiver of missing deterministic proof. Confidence is
limited by the blocked full lanes; human approval is not asserted. Source context
was the full changed files, candidate diff and independent catalog/dump checks.

## Data and operational boundary

The existing development PostgreSQL cluster and all existing worktrees are retained.
No `down --volumes`, `stamp`, development migration or secret publication is part
of this change. Existing databases on the retired graph require their old code/image;
this is not an in-place data migration. Use the parallel project procedure in
`../audits/postgresql-rebaseline-0047.md`.
