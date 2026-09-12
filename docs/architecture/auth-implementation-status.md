# Authentication implementation: local validation checkpoint

Date: 2026-09-12. This is a verification checkpoint, not a replacement for the
acceptance criteria in `identity-provider-and-staff-provisioning-plan.md` or the
amended slices in `principal-agent-and-provisioning-authority-model.md`.

**Overall status: incomplete; not certified for production.** Passing the current
tests is necessary but does not prove the unimplemented acceptance journeys.

## Verified implementation

| Area | Implemented boundary and evidence |
| --- | --- |
| Native-first HTTP | Explicit ASGI factory, required secret configuration, native enrollment/session endpoints, optional OIDC disabled by default. Real TCP startup/OpenAPI/auth rejection proof in `tests/e2e/test_http_runtime_factory.py`. |
| Runtime database identity | Startup rejects privileged logins and membership in any role other than the app role. Real PostgreSQL tests include non-inherited worker, private-definer and read-all-data memberships. |
| Runtime native authority | Startup rejects absent, disabled and wrong-kind native-authority configuration. A bounded, boolean-only DB projection backs readiness; disabling the authority while serving TCP produces 503 with no details and no-store. It does not certify the full schema head or worker health. |
| Native credential inputs | Login/rotation reject blank handles and injected fields. Invalid new passwords produce typed 422 after validating the current credential, including byte-size/UTF-8 failures, without replacing credentials or revoking sessions. Successful HTTP rotation invalidates old passwords/sessions without provisioning a Principal. |
| Native staff | Invite, activate, bounded authority replacement and suspension execute through HTTP. List/detail expose revisions and standing grants under explicit `staff.read`, with bounded UUID pagination and foreign/random-ID opacity. The DB reader rechecks a revoked grant even when passed a previously valid actor. Operational grants remain non-delegable and do not manufacture Party Representations. |
| Integration workloads | HUMAN-controlled provisioning, bounded operational authority, list/detail with revisions, activation/suspension/revocation and credential rotation. HTTP booking journey proves immediate old-token rejection and secret-free idempotent rotation replay. |
| Integration provenance | Appended governance facts, immutable origin and credential metadata without reusable secrets. Existing legacy state is identified rather than attributed to an invented creator. |
| Optional OIDC bearer | Strict configured access-token profile, bounded JWKS fetching/cache, current-authority revalidation and explicit subject-to-Principal binding. Native/external coexistence and external-authority removal are tested with a controlled external boundary. |
| Tenant references | Appended composite foreign keys and scoped provenance guards distinguish tenant-local references from legitimate platform provenance. Applied baseline history is unchanged. |
| Operation metadata | Ten manually registered configuration/discovery operations now have explicit stable operation IDs and capability/owner metadata. This does not automatically expose them as agent tools. |
| Resource configuration | Creating a Resource without weekly windows no longer fabricates an assignment; this matches the accepted onboarding semantics. |

Important distinction: INTEGRATION workload access for a website's server is not
the B2B external-human identity-provider adapter slice. A workload credential must
not be embedded in browser JavaScript.

## Agent inspection continuation (2026-09-12, revision 0037)

`GET /v1/agents` and `GET /v1/agents/{agent_principal_id}` now expose current
profile/authority revisions, lifecycle and sorted standing capabilities under
explicit HUMAN `agent.read`. The adapter rechecks current grant/Principal state
and reads target data in one PostgreSQL statement snapshot; foreign and random
IDs are opaque. No credentials or effective Party/resource permission claims are
returned. See `agent-governance-inspection.md` for the owner operation contract.

Additive 0037 appends immutable `tenant-controller-v2` (v1 plus `agent.read`),
used only for new native roots. Both the habitual PostgreSQL 18.6 database on
5432 and the isolated proof cluster have been migrated. Startup/readiness
validate the selected policy through the private selector without gaining table
access. Existing v1/no-policy roots and their revocations are not upgraded.

Executed evidence so far:

- Focused DB/HTTP run: 17 passed and one failed because its final policy-key
  assertion still expected v1. Updated the assertion to the explicit v2 default;
  the earlier failure is retained in `.ci/agent-inspection-focused-20260912.xml`.
- Final HTTP/OpenAPI/readiness repetition: **15 passed** in
  `.ci/agent-inspection-http-final-20260912.xml`, including absent-selected-policy
  readiness failure and the controller/agent booking journey.
- Python-quality: all 12 steps passed in
  `.ci/python-quality-agent-inspection-final-20260912.json`.
- Populated physical upgrades passed through the multidatabase proof: create a
  real root at 0035 and another with policy v1 at 0036, revoke authority, upgrade
  to 0037, select v2 and replay; original facts, grants and revocations persist.

The initial migration attempt rolled back before applying because SQLAlchemy
parsed a compact JSON `:true` as a bind parameter. The corrected literal applied
successfully; subsequent JSON whitespace formatting did not change stored data.
The canonical full run and Linux repetition are still running. Earlier 759-test
evidence is not assigned to these new changes. No deployment/push was performed.

## Agent handoff and populated upgrade continuation (2026-09-12, still 0036)

The native controller now completes the AGENT journey without SQL manager grants
or SQL revision lookups: provision, bounded standing authority, risk/tool policy,
activation, and booking for a patient. Agent creation returns the actual initial
Principal `authority_revision` separately from `profile_revision`, persists that
snapshot with the idempotent result and marks the response `no-store`. Replay
never returns the workload secret or invents current revisions. Historical cached
responses lacking the added field return null. A dedicated current-state agent
inspection/refresh API is still missing; the creation response does not replace it.
No schema migration, database privilege or new capability was needed for this fix.

The focused final HTTP/agent-unit selection passed **6** tests:
`.ci/initial-controller-agent-final-20260912.xml`. It includes a legacy-cache-shape
compatibility input after real provisioning, without rewriting authority facts.
The populated physical upgrade proof also passed on PostgreSQL 18.6 through
`scripts/db/prove_multidatabase_migration_compatibility.py`: install 0035, create a
real root through its private command, revoke `staff.read`, upgrade to HEAD, then
select the newer policy and replay. Grant IDs, statuses, revisions and provenance
remain unchanged, and the root policy remains absent. Its isolated temporary
database is deleted afterwards, never the source database.

The previous completed 0036 canonical run passed **759** tests (**399 E2E**), zero
failures/errors/skips and no mapped-proof gaps:
`.ci/current-product-initial-controller-20260911/`. The Linux repetition passed
**17** tests under Python 3.13.15: `.ci/linux-initial-controller-20260912.xml`.
Those results precede the agent response addition above. Final Python-quality
passed every step in `.ci/python-quality-initial-controller-agent-final-20260912.json`;
the first attempt stopped on one overlong test SQL string, corrected without
changing its assertion. The final canonical run subsequently completed with
**759** tests (**399 E2E**), zero failures/errors/skips and no mapped-proof gaps:
`.ci/current-product-initial-controller-agent-20260912/`. These results include
the agent response addition, but precede the separate 0037 inspection changes.
The final Linux repetition of the affected native-platform/agent-lifecycle
journeys passed **2** tests under Python 3.13.15:
`.ci/linux-initial-controller-agent-final-20260912.xml`. This run includes the
new authority-revision response and legacy-cache compatibility proof.

## Initial controller policy continuation (2026-09-11, revision 0036)

Native organization creation now explicitly selects immutable `tenant-controller-v1`.
Revision 0036 records it on the root and materializes 25 additional grants atomically;
the resulting controller has 33 active capabilities, with no wildcard, platform
authority or automatic inheritance of future registry additions. Existing roots
retain their original policy, and replay never restores revoked grants. The
private process requires the policy selector at startup. See
`initial-controller-policy.md` for exact authority and rollout semantics.

Executed focused PostgreSQL 18 evidence:

- 16 runtime/HTTP/policy/legacy-root cases passed in
  `.ci/initial-controller-policy-runtime-20260911.xml`. The CLI/bootstrap-to-HTTP
  controller configures actual bookable supply, books a patient and provisions,
  bounds and activates an integration without inserting controller grants.
  The workload can look up the patient but cannot read staff. Workload-authority
  installation configuration is still explicitly seeded; this is not a fully
  fixture-free installation journey.
- 7 final policy/concurrency/legacy-replay cases passed in
  `.ci/initial-controller-race-final-20260911.xml`: independent connections
  demonstrably wait on the creator lock, then produce one root and 33 active
  grants; a selected-policy replay leaves an old root's original grants unchanged.
  The first attempt exposed two test errors: counting historical revoked grants
  as active duplicates, and reading setup data under the intentionally restricted
  control role. Corrected oracles preserve the seven historical revoked records.
- The full DB selection passed 316 cases in `.ci/db-initial-controller-20260911.xml`
  before the extra concurrency case and strengthened legacy-replay assertion.
  Those changes passed the seven-case final selection above.
- Python-quality passed every step in
  `.ci/python-quality-initial-controller-final-20260911.json`; the last two test-only
  corrections are additionally checked by targeted Ruff/Pyright and PostgreSQL.

Both local PostgreSQL clusters are now at 0036. The auxiliary cluster first
rejected connections during crash recovery from its earlier interrupted shutdown;
no migration/test executed during those two rejected connection attempts. Recovery
completed normally before the upgrade and focused proof. The completed 0036
canonical result is recorded above; the older 0035 result below does not certify
0036. The later auxiliary shutdown completed its checkpoint and exited cleanly.
No deployment or publication is claimed.

## Private process continuation (2026-09-11, historical checkpoint 0035)

`bootstrap.platform_server:create_app` now owns the three distinct pool lifecycles,
validates explicit deployment configuration and verifies real login privileges
at startup and readiness. It rejects unexpected memberships (including NOINHERIT),
direct read/write relation privileges, extra callable private functions, app-to-platform
privilege crossover and inactive native authority. Endpoint/user mismatches and
hidden URL routing overrides fail before startup. External identity remains optional.
The deployment contract and remaining ingress/TLS obligations are described in
`http-runtime-deployment.md`.

The canonical PostgreSQL 18.6 runner completed **754** tests, including **399 E2E**,
with zero failures/errors/skips and no mapped-proof execution gaps:
`.ci/current-product-private-platform-20260911/`. Baseline integrity and the
controlled second-database migration checks passed. The explicit host/database
validation was added during the earlier SQL phases, before E2E loaded the factory;
the final Python-quality run passed all steps separately:
`.ci/python-quality-private-platform-explicit-20260911.json`. This includes the
ten pure configuration proofs; nine real-PostgreSQL private-process cases include
real TCP and privilege/authority drift. The complete DB selection also passed
**312** tests on schema 0035: `.ci/local-db-platform-root-20260911.xml`.

The first Linux repetition failed during collection with local memory exhaustion,
before executing any test; it is not behavioral evidence. The auxiliary proof
container was stopped (not deleted) after the global runner completed to free
memory for a sequential Linux retry. The habitual PostgreSQL container on port
5432 remains running and both databases retain revision 0035. The sequential Linux
retry passed **31** tests under Python 3.13.15:
`.ci/linux-private-platform-sequential-20260911.xml`. No exact-SHA publication
certificate or production deployment is claimed.

The adversarial fixture initially left two newly created control-test roles with
their deliberately injected grants after teardown failed. Both were verified to
own zero objects and removed with their test grants; no product rows or pre-existing
roles were removed. Fixture cleanup now removes its own temporary privileges
before dropping its own role. No migration was edited for this process work.

## Native platform provisioning continuation (2026-09-11, revision 0035)

The separate private control API now supports native provisioner creation and
organization/first-controller creation. No external provider is required. The
ordinary native tenant API does not install these routes. Revision 0035 adds
atomic native provisioner binding; organization creation reuses the existing
root function with full-intent idempotency provenance rather than editing history.
The operation/connection design is in `http-runtime-deployment.md`.

Focused real PostgreSQL 18 proof passed **6** cases:
`.ci/native-platform-root-http-final-20260911.xml`. This includes independent
competing transactions, atomic rollback, payload conflicts, replay after target
revocation, creator authority revocation, and the bootstrap-to-controller HTTP
journey without manually inserted bindings or tenant provisioning facts. The
tenant controller can inspect staff; the platform provisioner cannot enter that
tenant, and the tenant controller cannot provision platform organizations.

Validation history is not hidden: the first 0035 quality run stopped on 17 type
errors; after correction a second reached architecture and identified the missing
private composition entry. The module-owned transport/import restriction was
preserved while registering this explicit composition. The first expanded HTTP
test expected 401 for an authenticated identity without plane authority; the
existing resolver correctly returned 403, and the assertion was corrected.
The full Python-quality job passed every step:
`.ci/python-quality-platform-root-20260911.json`. The canonical PostgreSQL 18.6
runner passed **745** tests, including **390 E2E**, with zero failures/errors/skips
and no mapped-proof execution gaps:
`.ci/current-product-platform-root-final-20260911/`. Baseline integrity and the
controlled second-database upgrade also passed. Its first attempt found a missing
exact-owner catalog entry for the new private function; that entry was pinned to
its full signature, without adding a generally trusted definer owner.
Linux/Python 3.13.15 passed **22** platform/authentication/TCP cases independently:
`.ci/linux-platform-root-20260911.xml`. These results certify only this local
checkpoint, not GitHub exact-head CI or production deployment.

This closes the basic native A-to-B-to-tenant transport journey, not the entire
production objective. Initial operational controller policy, recovery/binding
administration and the remaining plan acceptance journeys are still incomplete.

## Platform continuation (2026-09-11, revision 0034)

An actual least-privilege native Platform Controller resolution exposed the
pre-existing platform-binding read defect: FORCE RLS hid the bootstrap-created
binding from the function's schema-owner execution context. Forward migration
`0034_platform_binding_read` assigns that exact read to the existing private
platform-read definer with eight explicitly reviewed binding SELECT columns.
No applied revision was edited, and the app role remains unable to read platform
authority directly. See `http-runtime-deployment.md` for the connection design.

The native runtime now offers an opt-in provider-neutral platform HTTP actor
resolver requiring a separate platform-read session factory. It rejects tenant
selectors, ignores forged authority headers and re-reads current RE binding/grants.
Ordinary native startup does not enable it and OIDC remains optional.

The real bootstrap/login/actor proof, private definer catalog and platform/app
separation tests passed **10** cases on PostgreSQL 18.6 after the fix:
`.ci/platform-http-definer-final-20260911.xml`. The first attempt correctly failed
on the hidden binding. A subsequent composition attempt incorrectly used the app
pool for platform authority and failed on its intentional privilege boundary;
the fix uses a distinct minimally privileged read login, not widened app grants.

Python-quality passed all steps after the implementation:
`.ci/python-quality-platform-http-final-20260911.json`. The first quality attempt
stopped on one formatting discrepancy; formatting was corrected and the entire
job rerun. The full current-product runner passed **743** tests, including **389
E2E**, with zero failures/errors/skips and no mapped-proof execution gaps:
`.ci/current-product-platform-http-20260911/`. Baseline integrity and the second
database's upgrade to 0034 passed as part of that runner. Linux/Python 3.13.15
also passed **17** platform-boundary and TCP runtime cases independently:
`.ci/linux-platform-http-20260911.xml`.
The complete local PostgreSQL selection passed **311** tests on revision 0034:
`.ci/local-db-platform-http-20260911.xml`. The canonical runner has also completed
its **87** principal-authority tests and baseline/multidatabase migration checks.
Prior 0033 evidence below does not certify revision 0034.
At the 0034 checkpoint, platform provisioning endpoints and the native provisioner
binding command were not implemented; the 0035 continuation above supersedes that
status. Complete initial controller policy remains unfinished.

## Continuation through revision 0033

The habitual PostgreSQL 18.6 instance on port 5432 now has
`0033_staff_terminal_revocation`. Appended revisions 0031-0033 add explicit staff
inspection, the private native-authority readiness projection and complete terminal
staff revocation; revisions 0001-0030 were not rewritten by this continuation.

The expanded HTTP staff journey exposed a real command/schema mismatch: the
accepted state machine permitted revoking invited/suspended memberships, while
the command accepted only active members. Revision 0033 fixes the command and also
rejects missing/nonpositive expected revisions and missing provenance at the DB
boundary. It retains self-transition rejection, tenant scoping, current-manager
checks, last-controller protection and atomic session invalidation.

The native password-rotation HTTP route also lacked a typed mapping for password
policy failures. The failing PostgreSQL-backed regression was reproduced before
the transport correction. Credential policy lengths, hashing parameters and
authority assignment were not relaxed.

Clean, completed continuation evidence:

- The complete canonical current-product runner finished on PostgreSQL 18.6 at
  revision 0033: **740 passed**, including **389 E2E**; JUnit records zero failures,
  errors or skips (two non-PostgreSQL E2E cases were deselected). Accepted baseline
  integrity, multidatabase upgrade and mapped-proof execution checks also passed.
  Artifacts: `.ci/current-product-auth-final-20260910/`. This run had already
  executed its authority block before the two new concurrency cases below were
  added; their subsequent 86-case authority rerun is separate evidence, not an
  invented 742-case full-run result. Production source did not change between them.
- The later adversarial closure adds both serialized orders of competing staff
  reactivation/revocation. Actual PostgreSQL lock-wait observation precedes commit;
  the stale loser returns `40001` without overwriting state or session epoch.
  The complete current-product principal-authority selection was rerun afterward:
  **86 passed**, `.ci/principal-authority-staff-race-20260910.xml`. Its focused
  lifecycle suite passed **12** cases, `.ci/staff-lifecycle-concurrency-20260910.xml`.
  The same **12** lifecycle cases also passed independently on Linux/Python
  3.13.15 against PostgreSQL 18.6: `.ci/linux-staff-race-20260910.xml`.
- Python-quality was rerun after those concurrency proofs and passed every step:
  `.ci/python-quality-staff-race-20260910.json` and `.ci/logs-staff-race-20260910/`.
  No production code, grants or applied migration changed in this proof-only step.
- The final Python-quality job passed all steps; machine-readable results are in
  `.ci/python-quality-auth-final-20260910.json` with its referenced logs.
- Linux/Python 3.13.15 independently passed **28** focused PostgreSQL, real TCP,
  native enrollment/rotation, staff/integration/OIDC, provisioning and hard-process
  crash proofs on revision 0033: `.ci/linux-auth-final-20260910.xml`.
- The complete host `tests/db -m postgres` selection passed on revision 0033:
  **308 passed**, `.ci/local-auth-db-final-20260910.xml`.
- A separate disposable PostgreSQL 18.6 cluster was installed at 0030, populated
  with original controllers and upgraded through 0033. Three one-off local
  scenarios passed: missing staff.read was added once; an existing active grant
  was not duplicated; a revoked grant stayed revoked. Every previously existing
  grant retained its ID, key, state, delegability and revision. This is local
  upgrade evidence, not a newly installed canonical CI test. The proof container
  `request-engine-auth-upgrade-20260910` was stopped, not deleted.
- The earlier complete canonical run on revision 0032 passed **735** tests,
  including **389** E2E, with clean baseline/multidatabase/proof-map checks. This
  earlier result does not certify the subsequent 0033 migration.

The first staff-read canonical attempt failed because two new routes lacked
entries in the general isolation probe matrix. Those probes were added with the
existing DB-authority rejection semantics; the real authenticated staff journey
separately proves foreign/random membership opacity. An attempted test run also
overlapped a focused host test with Linux tests on the same database. That run was
invalidated/interrupted and is not release evidence. The 28-test Linux result
above was executed again without that overlap. The two canonical test clusters
are separate from each other; tests must remain serialized within each database.

## Earlier executed evidence (revision 0030)

The source was the dirty local `cohesion/system-optimization` worktree based on
`43f889da023ef4559ddea0a902b720a5c3920df3`, not a new committed/published release.
These results do not certify that commit alone or replace exact-head GitHub CI.

- The local database on port 5432 was verified as PostgreSQL 18.6 at revision
  `0030_integration_provenance` for this checkpoint.
- `scripts/ci/ci_jobs.py python-quality` passed after the runtime/staff/crash-proof
  changes: lint, format, strict typing, security/dependency scans, architecture,
  unit and module checks. The final repeat including the staff-capability
  description correction also passed; its machine-readable result is recorded below.
- `scripts/ci/run_current_product.sh` completed on a separately created PostgreSQL
  18.6 cluster through Git Bash and Windows Python: **725 tests passed**, including
  **384 E2E tests**, with 2 E2E cases deselected by the PostgreSQL marker. Accepted
  baseline integrity, second-database migration and proof-map execution also passed.
- The complete `tests/db` PostgreSQL selection passed independently on the local
  port-5432 database: **298 passed**.
- A Linux container using Python 3.13.15 reran the critical HTTP runtime, native
  staff/provisioning, integration booking/rotation, OIDC and process-crash proofs:
  **10 passed** against real PostgreSQL 18.6. This includes the real POSIX SIGKILL
  branch, not just the Windows hard-termination adaptation.

Local generated evidence (ignored by Git):

```text
.ci/current-product-local-20260910/*.xml
.ci/current-product-local-20260910/baseline-integrity.json
.ci/current-product-local-20260910/proof-execution.json
.ci/local-auth-db-20260910.xml
.ci/linux-auth-20260910.xml
.ci/python-quality-auth-20260910.json
```

The Windows crash test originally failed before testing recovery because SIGKILL
is unavailable on Windows. The test now uses unconditional TerminateProcess there,
retains SIGKILL on POSIX, checks the exact expected termination code and bounds
subprocess execution. Lease recovery and stale-worker fencing assertions remain.

An attempted fresh database installation in the habitual cluster failed closed
because two existing `re_e2e_*` logins retain app/worker memberships. The immutable
baseline requires its audited role topology. The clean-cluster proof did not
remove those logins or weaken that guard. Installing another database into an
already provisioned runtime cluster remains an operational limitation to resolve
explicitly; clean-cluster installation and the runner's controlled multibase case
are not evidence that every existing role topology is supported.

The empty database from that failed first attempt was verified to contain no
user tables and removed. The separate proof container was stopped, not deleted;
its database remains recoverable by restarting `request-engine-proof-20260910`.
The habitual port-5432 container remains running.

## Still required by the identity plan

1. Operational acceptance of the private platform-control service in the selected
   deployment environment. The authenticated HTTP journey and separately configured
   process now exist; credentials, private ingress and TLS are not yet deployed.
2. Explicit management of older controller policies. Current-state agent inspection
   is implemented in 0037; its new full evidence is tracked above. The initial policy
   now has HTTP human/integration/agent
   booking proof and populated physical-upgrade evidence; legacy roots deliberately
   retain their authority rather than being silently upgraded on replay.
3. Party/resource-effective authority inspection. Native staff invitation cancellation,
   activation, suspension, reactivation with fresh login and terminal revocation now
   have owner-backed HTTP proof. Staff list/detail and client-visible revisions are
   implemented; active standing grants intentionally do not claim effective access
   to every Party/resource.
4. Governed native recovery/disable, platform provisioner lifecycle and explicit
   authority/binding administration surfaces. Creating a provisioner is not a full
   lifecycle API. Internal mechanisms or SQL setup are not an operator-facing product.
5. A real external-human B2B identity adapter and conformance/portability evidence,
   including signed events, replay/out-of-order handling and reconciliation where
   that provider facet is supported. Generic OIDC verification does not supply it.
6. Onboarding identity/controller/staff prerequisites and actionable machine-readable
   blockers. Business supply readiness currently does not prove identity readiness.
7. The complete fixture-free acceptance journeys and their adversarial closure,
   including production deployment, credentials/TLS/ingress limits, worker/provider
   delivery, backup/recovery and operational acceptance in the intended environment.

The next implementation priority is Party/resource-effective authority inspection and
identity administration. The providerless creation and initial authority journeys
now exist; their production operational acceptance remains separate. External
identity must remain optional throughout that work.

## Review and publication limits

No commit, push, PR, merge or production deployment was performed for this
checkpoint. Existing unrelated work was preserved. The single integration lane
still names the current branch; `origin/development` was fetched and the branch
was verified as 0 commits behind and 315 ahead.

Maintainability scans are not semantic approval. Exact-source validated review
packets and per-candidate dispositions are still required before calling the
review/publish cycle complete. A dirty-tree test result is not an exact-SHA
publication certificate; the managed pre-push gate and GitHub CI still apply.

The 2026-09-12 scan also reports `QR-9d3bb247f80f` (upgrade evidence, 128
effective LOC) and `QR-05d049acb91d` (native platform HTTP journey, 440 effective
LOC), both `QR-FSIZE-001`. Formal packet-review disposition:
`INSUFFICIENT_CONTEXT` (high confidence that validated exact-source packets are
absent, not a verdict that the code is defective). Protected properties are
cohesion and reasoning locality. Source inspection finds one migration scenario
and one end-to-end authority journey respectively; a counterargument is that the
long journey can make failure localization harder. Do not split them merely to
cross the LOC threshold. Generate/validate exact-source packets and obtain the
required review before claiming the review cycle complete; author inspection and
green tests are not independent approval. The measurements above come from
`.ci/python-quality-signals.json`, which remains a scan, not an evidence packet.

The 0037 scan updates those two candidates to 137 and 470 effective LOC,
respectively, and reports `QR-ff49fe31057b` (private factory, 160) and
`QR-9e8841575714` (policy proof, 212). The same `INSUFFICIENT_CONTEXT` formal
packet disposition applies: no validated exact-source packets are present.
Source inspection concerns are failure localization in the growing HTTP journey
and keeping owner policy selection separate from technical readiness checks.
The factory consumes explicit owner composition metadata; the reader remains
one tenant-scoped query responsibility with a typed application port and HTTP
DTO mapping. No extraction or authority-rule waiver was made to reduce metrics.
Architecture, lint/types and behavior proofs remain required independently;
`human_verdict` is null because no human supplied a review disposition.
