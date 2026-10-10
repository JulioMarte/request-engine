# API audit remediation — implementation evidence, 2026-10-03

Status: **in progress, not release certification**. This records the follow-up to
`api-adversarial-coherence-audit-2026-10-03.md`; that audit remains a checkpoint,
not a claim about the final repaired implementation.

## Verified environment

Branch: `feature/admin-console`. Integration base resolved this work session:
`origin/development` = `1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`.
Work is uncommitted and includes earlier unrelated changes; HEAD alone does not
identify the tested working tree. No push, merge or exact-head CI is claimed.

Database proof uses PostgreSQL **18.6**, host `127.0.0.1`, port **55433**, database
`request_engine_admin_verify`. The user's configured database on port 5432 was
not reset. Suites run serially because fixtures truncate their isolated business
world. Explicit PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD are set before pytest.

## Executed root checks

| Command | Actual result |
| --- | --- |
| `uv run pytest tests/integration/f1_operational_profile/test_supply_configuration_reads.py -q --tb=short` | Latest: 4 passed, 17.59s, head `0019_native_provision_reachable`; restricted application-role reads, real SQL pagination, foreign filters/principal, withdrawal, owner-created context/resource exceptions and channel command |
| `uv run pytest tests/modules/booking tests/modules/communications tests/modules/catalog tests/modules/delivery tests/modules/tenancy tests/unit/test_http_authentication_contract.py tests/unit/platform/security/test_webauthn_login_privacy.py tests/unit/test_staff_invitation_http.py -q --tb=short` | 410 passed, 11.89s; no PostgreSQL certification inferred |
| `uv run pytest tests/unit/test_staff_invitation_http.py tests/modules/tenancy/test_staff_command_input_contract.py -q` | Latest: 45 passed, 5.24s; includes valid 254-character mailbox and invalid 255-character mailbox with otherwise valid labels |
| `uv run pyright` | 0 errors, 0 warnings; Requests/authority work still evolving, final rerun required |
| `uv run python scripts/ci/ci_jobs.py python-quality` | First attempt stopped at Ruff; second stopped at formatting. Import sorting and formatting corrected; full final rerun pending |

Previously executed architecture suite passed 201 tests on an earlier working
tree. New Requests/authority edits require a final rerun; this is not exact-head
evidence for the completed change.

Latest standalone architecture rerun: `uv run pytest tests/architecture -q
--tb=short`, **201 passed in 21.86s**. A later canonical quality attempt reached
Pyright and failed on missing optional-row narrowing in new Tenancy tests. The
owner corrected it and reported targeted type proof; final global proof remains
required. Existing `.ci/quality-evidence` packets are older checkpoints and are
not accepted as semantic-review certification of this uncommitted working tree.

Later canonical `python-quality` run **passed every step** (session 42312):
Ruff/format, Pyright, secret scan, static security, dependency audit, architecture,
unit and module suites. This applies to the then-current working tree, not
subsequent migration work; old `.ci/logs` test counts must not be attributed to
this run, which did not specify a log directory.

`uv run python scripts/db/prove_multidatabase_migration_compatibility.py` then
**failed** at immutable baseline role verification: the earlier uncommitted 0013
introduced cluster-global `request_engine_retention_recorder`, outside the exact
baseline role set. Its temporary proof database was cleaned up by the script.
Forward revision `0020_retention_recorder_role` subsequently repaired this
installation defect using the independent extension namespace
`request_retention_recorder`. The baseline and already applied 0013 were not
edited. Unknown role dependencies fail closed; no business data is erased.
The same multi-database command then **passed** at head 0020: a second database
installed 0001 through 0020 and verified shared role attributes and narrow ACLs.
The final rerun after further migrations remains required.

Latest canonical quality run used explicit artifacts:
`uv run python scripts/ci/ci_jobs.py python-quality --log-dir
.ci/api-remediation-quality-20261004 --summary-output
.ci/api-remediation-quality-20261004.json`. Every step **passed**: architecture
201 tests, unit 991 tests (one warning), module 712 tests, Ruff/format, Pyright,
secret/static-security scans and dependency audit. This run predates the final
0021 manifest changes; it is working-tree evidence, not exact-head certification.

Subsequent final-head-0022 quality rerun used
`.ci/api-remediation-quality-head22-final-20261004` and its sibling JSON summary:
all steps **passed** after correcting incomplete lambda parameter types in the
new exporter regression test. This includes the forward session guard and
first-run E2E source changes; PostgreSQL execution is a separate lane.
The canonical current-product runner also passed accepted-baseline integrity and
second-database installation through **0022_native_provision_session**, then
**stopped** in its first schema/security group: 34 passed, 1 failed in 142.62s.
`test_security_definers_are_closed_across_all_runtime_schemas` reports four new
functions owned by `request_platform_control_definer` missing from its exact
signature approval inventory. Subsequent review confirmed their narrow owner,
ACL and RLS contract. Four exact signatures were added; the general trusted-owner
set was **not** widened. Two new proofs check private helper ACLs and reject an
unknown function owned by that definer. Agent-reported complete inventory file:
**5 passed in 19.08s**; negative proof rerun after formatting: **1 passed in
3.59s**. No DDL or privileges changed in this inventory repair. The original
canonical run remains stopped; later groups did not run and a full rerun is
still required. Installation gates do not imply a green current-product lane.

Agent-reported latest narrow PostgreSQL evidence (same isolated PG18 environment):
Tenancy 11 cases across replay/current authority, password/passkey-only posture,
concurrency, owner reads and limit-100 lookahead; Catalog/Delivery/Requests 11
cases at head 0019, including actual API authority bootstrap and deterministic
fresh-submit/deactivation contention; WebAuthn nine journeys at head 0018. These
do not replace the full canonical current-product lane.

## Repair areas and limits

- Forward revision `0021_tenant_controller_v6` and the native provisioning
  creation default now select immutable v5 plus thirteen explicitly curated
  operational grants. Agent-reported isolated PostgreSQL evidence: 16 policy
  tests passed in 63.76s at head 0021. The new HTTP policy proof uses a test
  actor resolver plus real PostgreSQL; its old-v3 root is created through a
  prior-deployment typed command under the current schema. It proves selection,
  grant materialization and replay preservation, not real login or migration
  over a preexisting old database. Existing-controller adoption remains pending.
  Requests internal processing (`record_result`, `complete`, `fail`) is neither
  granted by this delta nor newly exposed in the public runtime composition.
- The native platform provisioning E2E consumer initially failed on missing
  idempotency keys, then on `native_identity_provision_forbidden`: its historical
  CLI controller is not an effective platform OWNER required by current identity
  provisioning. Adapting the proof to the supported owner ceremony is in progress;
  no production authorization check was weakened to accommodate its fixture.
  The replacement real first-run claim/passkey/login journey then exposed a
  **production composition defect**: native actor `credential_id` is the session
  token UUID, whereas the 0019 guard interprets it as a password/passkey credential
  UUID. This rejects legitimate owners with 403. Forward revision
  `0022_native_provision_session` now resolves the real session to its original
  authenticator and locks/revalidates active session, expiry, identity epoch,
  accepted methods and non-recovery posture before receipt lookup. It preserves
  the audit identifier's session meaning and has no credential-UUID fallback.
  Agent-reported PostgreSQL proof: 19 provisioning cases passed in 87.02s at head
  0022, including password/passkey logout, expired-session, global revocation and
  direct-credential-ID negatives. These use materialized test sessions; the
  Actual first-run HTTP regression subsequently **passed**: 1 case in 16.94s,
  `test_claimed_owner_provisions_native_human_and_tenant_without_sql_binding`
  at head 0022. SetupSession, software passkey, recovery codes, finalize and
  verified WebAuthn login establish the real owner; no owner grants are seeded.
  It exercises passkey-session creation/password-session replay, native user and
  fresh-v6 tenant provisioning, integration/agent, booking and revoked replay.
  This is ASGI HTTP plus real PostgreSQL, not Chrome or external network E2E.
- Clean Docker PostgreSQL 18 baseline installation reached the binary seed gate
  and initially failed on Windows CRLF export (40,943 versus 40,056 bytes).
  Semantic seed comparison passed; LF-only normalization reproduced the exact
  immutable manifest SHA-256. `export_seed_data_catalog.py` now writes LF
  explicitly, without relaxing verification or editing baseline history.
  Six exporter/verifier unit tests passed. Rerun
  `bash scripts/db/prove_baseline_integrity.sh
  .ci/api-remediation-baseline-fixed-20261004` **passed** using clean Docker
  PostgreSQL 18 installations (separate cluster, not the user's database).
- Booking supply and Communications channel readback now expose configuration and
  revisions through owner Queries. See
  `../architecture/administrative-configuration-readback.md` for authority,
  pagination, operation semantics and deployment limits.
- Invitation email inputs now share one owner normalization rule with HTTP:
  ASCII mailbox, local part at most 64, normalized address at most 254. Invalid
  input is rejected before invitation creation/provider staging. These checks
  do not prove actual external mailbox delivery.
- Authentication/schema and discoverable-passkey changes have focal unit/module
  proof and nine repeated database-backed WebAuthn journeys. Legacy
  non-discoverable passkeys require replacement
  through existing password/recovery paths, not silent deletion.
- Native identity provisioning has isolated create/replay/conflict,
  grant-withdrawal and native reachability/recovery negative proof, including
  passkey-only authentication. Session expiration/logout still belongs to ingress
  authentication: the command does not receive a session UUID.
- Catalog eligibility, typed responses and pagination have module and narrow
  PostgreSQL proof. Wider consumer/full current-product acceptance remains pending.
- Requests definition administration, inbox and explicit-version replay have
  narrow HTTP/PostgreSQL proof, including concurrent deactivation. Required
  `definition_version` and URL-safe new definition keys are deliberate
  pre-production contract adaptations. Its administrative authority reuses
  API-assignable `operations.manage_profile`; no unreachable new Party scope is
  required. Legacy arbitrary regex `pattern` evaluation remains a documented
  pre-existing denial-of-service risk, not a certified safe regex engine.
- Independent Requests inspection identified an unproved capability-revocation
  interleaving: definition Commands check the operation capability at HTTP actor
  resolution, then revalidate/lock current principal, Party and Representation
  in the authoritative transaction. They do not independently lock/recheck that
  capability grant before receipt replay. Representation withdrawal proof is not
  capability withdrawal proof. This ingress-snapshot pattern also exists in
  older Catalog/Communications/Requests Commands; the stricter Tenancy authority
  replay contract must not be claimed universally. Per-operation authorization
  linearization and adversarial revocation proof remain required before asserting
  execution-time capability revocation safety. No generic grant bypass or broad
  architectural exception was introduced to conceal this gap.

## Required closure

Final checkpoint, 2026-10-04: root executed the strengthened policy and complete
native-provisioning suites together on PostgreSQL 18.6/head 0022:
`uv run pytest tests/db/test_initial_controller_policy.py
tests/db/test_native_identity_admin_provision.py -q --tb=short
--junitxml=.ci/api-remediation-current-product-20261004/final-provision-policy.xml`
→ **37 passed in 181.32s**. This includes the final replay state snapshots and
epoch/recovery-derived variants; previous partial reports are not the final count.

Final post-inventory `python-quality` run also **passed every step**, with logs
under `.ci/api-remediation-quality-security-final-20261004` and its sibling JSON:
**201 architecture, 992 unit (one warning), 712 module** cases. This is tested
uncommitted working-tree evidence, not exact-head remote CI or merge permission.
No PostgreSQL sessions remain running from these checks; the full current-product
run is still incomplete as recorded above. No user data reset or live deployment
update was performed.

Remaining closure:

1. Accept/design the existing-controller adoption journey. Existing
   controllers have an independently confirmed authority-reachability gap:
   delegation cannot manufacture capabilities outside the actor's current ceiling
   and upgrade cannot target itself. ADR 0016 proposes a separate governed
   adoption journey; it is not accepted or implemented. Do not backfill grants.
2. Rerun the full owning current-product lane after the reviewed inventory repair;
   later groups were not executed in the stopped canonical run. Preserve
   negative/current-authority replay and immutable-version behavior.
3. Close operational capability-revocation linearization and legacy regex risk
   with explicit owner contracts and corresponding falsifiable proof. Repeat
   final quality after any further code changes; do not waive unrelated failures.
4. Review deterministic maintainability candidates using the semantic protocol;
   metrics alone are neither defects nor proof of correctness.
5. Validate production-like installation/roles and real browser/provider paths.
   Source changes, in-process HTTP tests and provider doubles do not certify the
   user's live panel, SMTP acceptance, infrastructure or production readiness.

## Maintainability review provenance

Latest quality scan reported 29 non-blocking candidates, not invariant failures.
An independent worktree diagnostic inspected the new Booking/Catalog configuration
readers/routers and Requests definition administration: their SQL/projection,
transport registration and shared single-transaction command phases do not justify
splitting merely to reduce LOC/McCabe. Diagnostic structural recommendation:
`HEALTHY_AS_IS`, with the capability linearization concern above tracked separately.
Tenancy author's review of its own changes is not independent approval.

Formal disposition remains `INSUFFICIENT_CONTEXT`: available evidence packets
`QR-b14901988a74` and `QR-7ce31b8ba060` identify source/tested SHA
`12e55a542fdcbb705641841d25681094822dc1e3`, not this dirty worktree based on
`e4f65b59eae4fcc032f3b7effc0550c165fe6ee7`. The scan is not an exact-head
review packet. No `human_verdict` was inferred (`null`); all 29 candidates have
not received formal disposition. Final publication/merge evidence is pending.

## Local panel follow-up — authorized old-organization reset, 2026-10-04

The user authorized deleting old organizations to start with the new policy.
Read-only inspection of the panel's configured local database found **zero
organizations**, one native identity and a claimed installation, at revision
0013. There was therefore no old tenant to erase or upgrade. Resetting the
whole instance/volume would unnecessarily destroy the owner's setup and other
databases (`request_engine`, `request_engine_baseline_probe`, `postgres`).
Disposition: preserve the existing owner and apply current migrations; no data
deletion, no automatic existing-principal grant update, no policy-adoption API.

Actual environment: owned Docker container `request-engine-postgres-1`, PostgreSQL
**18.6**, `127.0.0.1:5432/request_engine_current`. Its initially stopped container
was started. The three repo panel processes were stopped before migration.
An ignored custom-format `pg_dump` was copied to
`.local-ci/backups/request_engine_current-before-head22-20261004-075442.dump`;
`pg_restore --list` read its catalog successfully. Full restoration was not tested.
The temporary container copy was removed after preserving the host copy.

`uv run alembic upgrade head` with this database's explicitly resolved migration
URL **passed**, 0013 through **0022_native_provision_session**. Postchecks:
0 organizations, 1 native identity, instance still claimed; v6 exists at revision
6 with 42 policy grants. The existing owner retains the active identity-provision,
owner-read, owner-provision and organization-provision grants; none were added
by a reset or manually seeded.

`./scripts/dev/run_local_panel.ps1 -ControlPort 8011 -RuntimePort 8010
-ConsolePort 8012 -Database request_engine_current -WithDelivery` **passed**.
Repeated GET checks returned 200 for control/runtime readiness, console liveness
and `http://localhost:8012/login`. Source files and migration history were not
changed for this deployment. Newly provisioned tenants use the server-selected v6
default after restart; live authenticated tenant creation is not yet proved.
Local OpenBao/Mailpit were started, but the delivery worker is **not started**:
health checks are not email-delivery evidence. Browser login, full current-product
rerun and production acceptance remain pending. No other database, the isolated
55433 test server, Docker volume, Bitwarden entry or passkey was deleted.
