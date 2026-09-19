# Auth/API ergonomics — validation handoff

Date: 2026-09-13. User explicitly assigned this session to implementation and asked
for another agent to run validation. **No tests were started after that change of
instruction.** Import ordering/formatting is not test, lint or type certification.

## Scope and provenance

Workspace: `C:\Users\julio\Documents\GitHub\request-engine`.
Branch: `cohesion/system-optimization`; last inspected HEAD:
`ca30131c10ba3c5e8058b49c4595751ebcc4eed4`. All new work is uncommitted. Preserve it.
Do not reset the tree, rewrite migrations 0001..0037, waive architecture rules,
push without managed certification, or treat these notes as production approval.
Read root/scoped AGENTS and the canonical docs before changing anything.

Two distinct blocks must not be conflated:

1. **Agent catalog block, before self-inspection:** optional agent admission to
   the exact server-marked GET catalog; current policy/risk filtering; canonical
   schema pointers; relationship requirements; no-store. This block actually
   passed local Python quality (180 architecture, 353 unit, 459 module tests) and
   the full PostgreSQL lane: **763 tests, zero failures/errors/skips, 293 executed
   files, proof-map gaps empty**, including 400 E2E. Artifacts:
   `.ci/python-quality-agent-catalog-final-20260912.json`,
   `.ci/logs-agent-catalog-final-20260912/`,
   `.ci/current-product-agent-catalog-20260912/`.
   The run had already completed when interruption was attempted. It was not an
   interrupted partial run. One existing Starlette TestClient deprecation warning
   remains; dependencies were not changed to suppress it.
2. **Self-authority block:** new typed query/DB reader/HTTP route; explicit
   capability; migration0038/default controller policy v3; authored regression
   tests and updated route inventory. **NOT EXECUTED OR VALIDATED. Migration0038
   has NOT been applied locally.** Earlier green evidence does not cover this block.

The GitHub green source checkpoint predates both dirty blocks; exact-head GitHub
CI remains required after publication. Local maintainability scans are not
validated exact-source packets. Do not infer human approval from green tests.

## Implementation to inspect first

- `docs/architecture/self-authority-inspection.md`: operation/connection/authority
  design gate, intentional standing-grant requirement and snapshot limitations.
- `src/request_engine/modules/tenancy/application/queries/self_authority.py`.
- `src/request_engine/modules/tenancy/adapters/db/self_authority_reader.py`.
- `src/request_engine/modules/tenancy/api/self_authority.py` and module API install.
- `src/request_engine/platform/security/capability_registry_identity_authority.py`.
- `migrations/versions/0038_self_authority_policy.py` and the native provisioning
  command's selected policy constant.
- Updated catalog, policy resolver and shared risk predicate; no generic unmarked
  route bypass is intended.

`GET /v1/me/authority` / `authority_read_self` / `authority.read_self` are distinct
HTTP identity, operation identity and permission. It exposes current self Party
relationships only. It does NOT decide arbitrary business/resource authorization.
v3 is exactly v2 plus one explicit delegable operational grant; old roots never
upgrade or regain revoked rights on replay. New private-process readiness must
fail before0038 is installed. No app/worker privileges or identity providers change.

## Environment: verify rather than assume

Last observed running container: `request-engine-postgres-1`, PostgreSQL18.6,
host5432, Compose credentials/database owner `request_engine`.
Dedicated test database: **`request_engine_current`**, last migrated0037.
Compose application database **`request_engine`** was migrated0037 separately;
DO NOT run truncating pytest fixtures on that application database.

Stopped historical containers exist. Do not restart/delete them or their volumes
to make the environment look clean. Avoid concurrent PostgreSQL suites: fixture
cleanup truncates tenant data. Roles are cluster-global; a fresh dedicated PG18
test cluster is preferable if real application runtime users now share this one.
Confirm Docker health, PostgreSQL major version, database identity and Alembic
revision. Do not print production secrets. Test users below are local Compose
credentials, never production deployment recommendations.

## Execution order (PowerShell)

First use read-only status/diff checks and read the new code. Fix actual findings
without weakening invariants. Run the narrow pure transport/policy proofs:

```powershell
uv run pytest tests/unit/test_operation_catalog.py tests/unit/test_agent_policy_enforcement.py tests/unit/test_self_authority_http.py -q
```

Configure only the dedicated test DB, then apply the new migration:

```powershell
$env:PGHOST='127.0.0.1'
$env:PGPORT='5432'
$env:PGDATABASE='request_engine_current'
$env:PGUSER='request_engine'
$env:PGPASSWORD='request_engine'
$env:MIGRATION_DATABASE_URL='postgresql+psycopg://request_engine:request_engine@127.0.0.1:5432/request_engine_current'
uv run alembic upgrade head
```

Do not apply0038 to the application database until the isolated migration and
behavior proofs pass. The private process selects v3 and intentionally fails
readiness/startup against the old catalog. A failure is not permission to fall
back silently to v2 or edit historical manifests.

Run these PostgreSQL proofs serially against the dedicated DB:

```powershell
uv run pytest tests/db/test_self_authority_reader.py tests/db/test_initial_controller_policy.py -q -m postgres --tb=short --junitxml=.ci/self-authority-db.xml
uv run pytest tests/e2e/test_native_platform_provisioner_http.py tests/e2e/test_native_agent_lifecycle.py tests/e2e/test_platform_control_runtime_factory.py tests/e2e/test_http_tenant_isolation_matrix.py -q -m postgres --tb=short --junitxml=.ci/self-authority-http.xml
```

The new DB proof is explicitly included in `scripts/ci/run_current_product.sh`.
Review the new current surface inventory entry and foreign-selector probe; do not
delete an operation from coverage to avoid a fixture or expected-status problem.

Then run the full owning lanes (not merely a cherry-picked green subset):

```powershell
uv run python scripts/ci/ci_jobs.py python-quality --log-dir .ci/logs-self-authority --summary-output .ci/python-quality-self-authority.json
$env:CURRENT_PRODUCT_CI_ARTIFACT_DIR='.ci/current-product-self-authority'
$env:PATH='C:\Users\julio\AppData\Local\Programs\pgAdmin 4\runtime;C:\Program Files\Git\bin;' + $env:PATH
& 'C:\Program Files\Git\bin\bash.exe' scripts/ci/run_current_product.sh
```

Verify those executable paths exist before use. Full PostgreSQL runner includes
fresh baseline/multi-database upgrade and populated prior-policy replay proof,
worker/runtime, tenant isolation, all E2E, booking regressions and final executed
proof-map validation. Read all XMLs and `proof-execution.json`; no gaps or skipped
required proofs. Never assume process exit or a partial progress line means pass.
Linux/Python3.13 repetition is useful for CI parity after host runs, but never in
parallel with another suite on the same DB; previous simultaneous heavy runs
exhausted memory. Use the repository's pinned toolchain, not ad hoc dependency upgrades.

## Adversarial acceptance to complete, not just test names

- A forged in-memory capability without a current standing DB grant is denied.
- Same cached ActorContext after grant revocation or caller deactivation is denied.
- Foreign tenant + real Principal ID is indistinguishable from an unavailable
  self snapshot; no foreign representations/Party facts or owner metadata leak.
- Another Principal's relationships in the same tenant never appear. Add an
  explicit same-tenant second-Principal case if existing coverage does not prove it.
- Future/expired/revoked representations and inactive Parties are excluded.
- Empty authorized page is200; denial is403. Exact-full final pages return null
  cursor; no duplicates across stable pages, and pagination remains bounded.
- Query input cannot manufacture Principal/tenant/Party authority. No schema or
  error body leaks credentials. Validate unknown filters and malformed cursors.
- HUMAN, INTEGRATION and AGENT callers need current explicit standing permission;
  AGENT additionally needs an allowed current READ policy. Add a native agent
  HTTP self-inspection journey, including grant and policy removal, before calling
  the workload-facing acceptance complete. Temporary delegated permission alone
  must not accidentally satisfy the explicit standing requirement.
- Reads do not consume mutation budget or change relationships, grants, Principal
  revisions, audit/outbox facts. Use independent DB state as the oracle.
- Native root creation uses v3 with35 active grants and27 policy-attributed facts;
  v1/v2 stay byte-for-byte immutable. Existing roots remain old policy after
  upgrade/replay, even when permissions were revoked. The current upgrade helper
  proves pre-policy/v1 histories; add populated v2->v3 proof if missing.
- Private readiness is false when the binary-selected policy is unavailable.
- Catalog schema pointers still resolve and AUTHORITY_CHANGE stays excluded even
  at the highest ceiling; arbitrary unmarked routes remain denied to agents.

Use real PostgreSQL roles/transactions for DB claims; external auth/session setup
must not seed the result under test. If a test fails, classify the defect and
repair code or legitimate preconditions; do not add broad allowlists or bypass RLS.

## Review and report

Collect current maintainability signals against the integration base. The default
HEAD-parent scanner misses tracked dirty-only changes; don't interpret its empty
candidate list as a review. After a real checkpoint, generate/validate exact-source
quality-evidence packets using the repository workflow. Follow semantic review
instructions, not metric-only file splitting, and do not fabricate human verdicts.

Update the authentication status document with actual commands, environment,
counts/failures/skips and artifacts. Report self-authority code as unvalidated
until its proofs have actually run. Remaining production work includes governed
identity recovery/disable and binding administration, upgrades of existing root
policies, full resource-effective diagnostics, identity-aware onboarding and
deployment/backup/provider operational acceptance. This handoff is not a claim
that those capabilities were implemented or that production is ready.
