# Native authority suspension: validation handoff

Superseded in part by revision0041 (2026-09-14): enrollment under an unavailable
authority now returns503 `native_enrollment_unavailable` instead of409
`native_identity_already_exists`. Everything below remains the executed evidence
for the0040 suspension block and its other paths.

## Status and scope

The original implementation-only handoff was resumed with owner authorization to
write and execute tests on2026-09-14. Migration0040 was already installed in the
local test DB when that session began. DB/HTTP suspension tests and runtime-role
fixtures were also present and were preserved, reviewed and strengthened.
See `../architecture/auth-implementation-status.md` for executed evidence and
remaining limits. The matrix below is acceptance guidance, not a claim that every
item has independent executed coverage. Prior780-test green belongs to0039.

Owner: native authentication technical boundary (`platform/security` and
`request_auth`); tenancy retains all business authority. HARD guarantees: current
identity trust, no privilege escalation, atomic credential transitions, immutable
identity linkage, one-use recovery, no secret disclosure. No HTTP operation,
operationId, capability, input/output schema or tool audience changes. Existing
bool/NULL database rejection maps through the existing service errors; recovery
remains uniform401 `recovery_intent_invalid`. No public recovery issuance.

READ credential/proof candidate; PLAN password verification/hash outside locks;
LOCK active native authority SHARE, then identity, then credential/intent;
VALIDATE identity status and current proof/credential, including expiry;
WRITE existing atomic effects only; no new EMIT/business audit/outbox facts.
Revocation paths deliberately do not require active authority. Commitment guard
now locks authority, identity and credential in separate statements, avoiding
dependence on a join plan for row-lock order.

## Real environment and migration evidence

Recheck branch/lane, working tree, Docker state and PostgreSQL version. Last
validator report: PostgreSQL18.6 on5432; dedicated `request_engine_current` at0039;
Compose application `request_engine` at0037. These are reports, not a fresh probe.
Do not run truncating tests on the app DB or concurrent suites sharing a DB.
Do not delete historical containers or apply migrations to the app DB.

Capture the seven replaced functions' signatures, owners, ACLs, volatility,
SECURITY DEFINER and pinned search_path at0039 and compare after0040. Require
exact preservation of existing grants; commitment guard is not app-executable.
Call public auth primitives as `request_engine_app`, never owner-only to claim
runtime evidence. Exercise commitment through its actual supported provisioning
callers and respective definer roles. Verify no table/constraint/RLS/role drift.
Prove populated0039→head and fresh baseline→head; no historical body rewrites.

## Required authored proofs

1. Real service + DB active control: legitimate enrollment, login, rotation,
   issuance and one-use consumption succeed with an active native authority.
   Obtain tokens through real issuance, not seeded desired results.
2. Disable the authority after legitimate identity/session/pending-proof creation.
   Credential read returns no verifier. Direct SQL session creation, rotation,
   issuance and consumption reject too, bypassing the service snapshot to prove
   the authoritative gate. Enrollment rejects; credentialed commitment fails.
   Unknown/wrong-kind authorities and disabled identities also fail closed.
3. Compare independent before/after auth facts: credential count/verifier/status/
   revision/last_used_at, identity epoch/revision, sessions and pending intents.
   Rejected issuance must not revoke the previously pending proof. No new IDs,
   timestamps or semantic effects; bindings, memberships, grants, audit and outbox
   remain unchanged. Keep raw proofs/passwords/verifiers out of test artifacts.
4. HTTP native-only login and password recovery under suspension reject without
   echoing secrets or exposing authority details; recovery is401 uniform failure
   and no-store. Existing session resolution rejects; readiness503 remains.
   If testing a disabled startup authority, startup fails intentionally: start
   with active authority and disable while the server is running for this case.
5. Stale-read race: service reads usable credential, authority is then disabled,
   service reaches session/rotation/issuance transaction. Each must reject even
   though the old snapshot was valid. Coordinate with explicit barriers.
6. Independent transactions, BOTH authority-lock winners for session creation,
   rotation, enrollment, issuance, consumption and credentialed commitment:
   authority UPDATE first and commit => blocked contender rejects with no effects;
   auth transaction first => UPDATE waits until auth commits/rolls back. Establish
   waiting via pg_blocking_pids/lock observations, not timing-only sleeps. Bound
   waits and clean up all connections. Also cover disable rollback allowing auth.
   Mutate FOR SHARE to FOR KEY SHARE in an isolated scratch proof: the status
   updater must wrongly stop waiting, making this regression test fail.
7. Preserve0039 nonvacuous recovery-vs-issuance/disable race and same-token HTTP
   race: one successful consume, one rejection, one replacement. Add commitment
   versus password rotation/identity disable to protect explicit child lock order.
   Active identities sharing one authority must not be serialized by an exclusive
   authority lock; unrelated authorities remain independent.
8. While suspended, restrictive session revocation and identity disable still
   work via existing privileged/service paths (not an invented public endpoint).
   Reenable: still-valid pending proof/session may work; expired, revoked or
   consumed proofs, revoked sessions, terminal disabled identities and revoked
   business authority must not revive. This is suspension, not bulk revocation.

Each proof needs an independent oracle, plausible preconditions, important
absence-of-effects assertions and canonical lane registration. Add a DB test
file to the explicit current-product runner selection; E2E follows its canonical
collection. Do not widen allowlists or relax guarantees to accommodate failures.

## Execution sequence for the validator

Use local test credentials only; inspect current runner documentation first.
Verify these executable paths exist. With the dedicated test DB confirmed:

```powershell
$env:PGHOST='127.0.0.1'
$env:PGPORT='5432'
$env:PGDATABASE='request_engine_current'
$env:PGUSER='request_engine'
$env:PGPASSWORD='request_engine'
$env:MIGRATION_DATABASE_URL='postgresql+psycopg://request_engine:request_engine@127.0.0.1:5432/request_engine_current'
uv run alembic upgrade head
uv run pytest tests/unit/platform/security/test_native_human_auth.py -q
uv run pytest tests/db/test_native_human_auth_runtime.py tests/db/test_native_recovery_lock_order.py tests/db/test_native_authority_probe.py -q -m postgres
uv run pytest tests/e2e/test_native_password_recovery.py tests/e2e/test_native_password_recovery_adversarial.py tests/e2e/test_native_enrollment.py -q -m postgres
```

Run `tests/db/test_native_authority_suspension.py`,
`tests/db/test_native_authority_suspension_locks.py` and
`tests/e2e/test_native_authority_suspension_http.py` explicitly next, recording
JUnit output and mutation evidence. They are registered in current-product proof.
Then canonical lanes:

```powershell
uv run python scripts/ci/ci_jobs.py python-quality --log-dir .ci/logs-native-authority-suspension --summary-output .ci/python-quality-native-authority-suspension.json
$env:CURRENT_PRODUCT_CI_ARTIFACT_DIR='.ci/current-product-native-authority-suspension'
$env:PATH='C:\Users\julio\AppData\Local\Programs\pgAdmin 4\runtime;C:\Program Files\Git\bin;' + $env:PATH
& 'C:\Program Files\Git\bin\bash.exe' scripts/ci/run_current_product.sh
```

Inspect every result/skip, proof-execution gaps and multi-DB upgrade output; do
not assume shell completion is green. Review migration file-size candidates via
the semantic review protocol: explicit immutable SQL bodies preserve upgrade
reproducibility; extraction is not required solely to lower LOC. No fabricated
human verdict or dirty-tree quality certificate. Record actual environment,
commands, counts, failures and unresolved risks in auth-implementation-status.

## Operational acceptance still required

Drain in-flight native auth and credentialed provisioning/membership transactions
before upgrading: old/new lock orders must not overlap. Replaced functions use a
10-second migration lock timeout, no data backfill and roll-forward-only recovery.
An admin transaction must lock authority before native identity/credential rows;
do not combine identity-first revocation then authority UPDATE in one transaction.
Readiness is not schema certification: inspect head/catalog before restoring
traffic. No deployment, app-DB migration, commit, push or merge is authorized by
this validation handoff. GitHub exact-head evidence and full identity lifecycle/
governed delivery/operational acceptance remain separate production requirements.
