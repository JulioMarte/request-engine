# Native recovery HTTP — validation handoff

Checkpoint: 2026-09-13. This document was authored before validation; the executed
result is in the next section. Preserve the dirty tree and previous validator's
changes. Earlier self-authority green evidence does not validate this new code.
Read repository/scoped AGENTS.

## Validation result (2026-09-13, executed)

Validation was executed against local PostgreSQL 18.6 and the dedicated
`request_engine_current` database (0039 applied only there; the Compose
application database `request_engine` was left at 0037). Full results, counts and
the pending authority-status gap are recorded in
`../architecture/auth-implementation-status.md`. Artifacts:
`.ci/native-recovery-http.xml`, `.ci/native-recovery-adversarial.xml`,
`.ci/python-quality-native-recovery-http.json` and
`.ci/current-product-native-recovery-http/` (780 tests, zero failures/errors/
skips, 297 executed files, proof-map gaps empty). The lock-order proof is
mutation-verified: temporarily restoring the pre-0039 function body makes it fail
with `DeadlockDetectedError`.

The required adversarial extensions below are implemented by
`tests/e2e/test_native_password_recovery_adversarial.py` and
`tests/db/test_native_recovery_lock_order.py`; the DB proof was added to
`scripts/ci/run_current_product.sh`. Open gap: a disabled
`identity_authorities.status` does not block recovery consumption; this is a
pre-existing semantic decision pending explicit acceptance, not implemented here.
Everything in "Reporting and limits" still applies: no commit/push/merge/
deployment, application database untouched, exact-head GitHub CI remains the
merge authority.

## Code and contract

- `src/request_engine/entrypoints/http/native_auth.py`: strict secret-bearing body,
  POST `/auth/native/password:recover`, stable `nativePasswordRecover`.
- `native_auth_errors.py`: uniform401 `recovery_intent_invalid` without target details.
- `tests/e2e/test_native_password_recovery.py`: authored PostgreSQL HTTP regression.
- Recovery subsection in `docs/architecture/http-runtime-deployment.md`.

The handler delegates to existing `NativeHumanAuthService.consume_recovery` and
its transactional store. Success204 has no body/session; password policy failure422
must not consume the proof. Migration0039 preserves the function signature, owner,
privileges and effects but changes locking to identity-before-intent, revalidating
the token after the identity lock. It has NOT been applied. No hashing primitive or
business authority change. Internal issuance in setup is only a prerequisite,
not proof of an authorized public/admin recovery issuance workflow.

## Environment and execution

Verify branch/lane and actual DB/container state before running anything. Last
user report: `request-engine-postgres-1`, PostgreSQL18.6, host5432, dedicated test
DB `request_engine_current` at0038. Application DB `request_engine` remains0037.
Do not run truncating tests on the application DB or run DB suites concurrently.
Do not delete/restart historical containers to simplify the environment.

PowerShell, with local Compose test credentials (never production credentials):

```powershell
$env:PGHOST='127.0.0.1'
$env:PGPORT='5432'
$env:PGDATABASE='request_engine_current'
$env:PGUSER='request_engine'
$env:PGPASSWORD='request_engine'
$env:MIGRATION_DATABASE_URL='postgresql+psycopg://request_engine:request_engine@127.0.0.1:5432/request_engine_current'
uv run alembic upgrade head
uv run pytest tests/unit/platform/security/test_native_human_auth.py -q
uv run pytest tests/e2e/test_native_password_recovery.py tests/e2e/test_native_enrollment.py -q -m postgres --tb=short --junitxml=.ci/native-recovery-http.xml
uv run python scripts/ci/ci_jobs.py python-quality --log-dir .ci/logs-native-recovery-http --summary-output .ci/python-quality-native-recovery-http.json
$env:CURRENT_PRODUCT_CI_ARTIFACT_DIR='.ci/current-product-native-recovery-http'
$env:PATH='C:\Users\julio\AppData\Local\Programs\pgAdmin 4\runtime;C:\Program Files\Git\bin;' + $env:PATH
& 'C:\Program Files\Git\bin\bash.exe' scripts/ci/run_current_product.sh
```

Verify executable paths exist. The canonical E2E collection includes the new file;
confirm actual execution, all XML outcomes and final proof-map gaps. Repair real
defects, not invariants. No SQLite/mocked SQL for transaction/privilege claims.

## Required adversarial extensions

1. Race independent HTTP requests for one recovery token: one success, one closed
   rejection, one credential replacement/semantic effect. Coordinate using the
   existing lock protocol and independent connections, not timing-only sleeps.
   Also reproduce the actual0039 regression: consumption competing with issuance,
   rotation or disable on one identity. Old consumption locks intent then identity;
   the other path locks identity then invalidates intents. Force that ordering
   using independent connections and a barrier. New code must converge without
   deadlock/partial credential effects. Issuance revokes old proofs, so do not
   fabricate two simultaneously pending issued tokens to make the scenario fit.
2. Expired intent and disabled authority must reject without credential/session
   mutations; error shape must not disclose whether the target exists.
3. Invalid password leaves the token usable. Malformed/oversized fields and extra
   identity selectors must not expose token/password values in validation errors.
4. Add a populated bound identity: recovery must not restore revoked bindings,
   memberships or grants. The authored unbound case proves no new authority, not
   this entire preservation claim. Inspect auth audit facts and ensure raw reset,
   password and session secrets never enter audit/outbox/telemetry.
5. Model lost successful response: new-password login reconciles success; token
   replay cannot create another credential or duplicate the semantic effect.
6. Native-only/OIDC-disabled composition must mount the route. No public issuance
   route or agent-tool projection should be added. Update additive OpenAPI/error
   inventory expectations only when justified, never suppress coverage.

## Reporting and limits

Record actual environment, commands, counts/failures/skips and artifacts in the
authentication status document. Formatting is not lint/type proof. Obtain current
exact-source quality packets and semantic review; do not split files for metrics
or fabricate human approval. Dirty-tree local green is not GitHub exact-head CI.

Do not apply migrations to the application DB, commit/push/merge or deploy as an
implied part of validation. Governed issuance/delivery, disable administration,
binding management and full recovery remain unfinished. Exposing `issue_recovery`
on an ordinary email-only request would permit account takeover; never use that
shortcut to make an acceptance journey appear complete.
