# P7 Platform Configuration / OpenBao — continuation handoff

Date: 2026-09-26
Branch: `feature/platform-config-openbao-recovery`
Base branch: `development`
PR: #133
Implementation HEAD before this handoff: `84fb75d9bf6c378eaa4bd3885ff23e28f987e14f`

## Purpose

This is an execution handoff, not a completion declaration. The next agent must continue from the repository state on the branch above, verify the exact HEAD it receives, inspect current CI, and close P7 against the architecture/spec documents and their Definition of Done. Do not assume that code existing in the branch means the operational requirement is proven.

## Where the previous agent stopped

The last implementation commit before this handoff was:

`84fb75d9bf6c378eaa4bd3885ff23e28f987e14f` — `fix(ci): make P7 proof workflow self-contained`

That commit repaired `.github/workflows/p7-platform-configuration-contract.yml` in two concrete ways:

1. The workflow path filter incorrectly referenced `migrations/versions/0093_managed_oidc_authority_projection.py`; the repository file is `migrations/versions/0093_managed_oidc_projection.py`.
2. The P7 pytest step wrote JUnit output to `.ci/p7-platform-configuration.xml` without guaranteeing that `.ci/` existed. The workflow now creates `.ci` explicitly and uses a multiline shell command so the proof job is self-contained.

At the time of handoff creation, GitHub showed CI for HEAD `84fb75d...` still running. At least the `Coolify adapter contract` workflow had completed successfully, while `Docker E2E` was still `in_progress`. Therefore **do not claim exact-head green from this handoff**. Re-check all checks on the current branch/PR first.

## Primary documents to treat as authority

Read these before changing behavior:

- `docs/architecture/p7-platform-configuration-secrets-implementation-handoff.md`
- `docs/architecture/platform-configuration-secrets-recovery-plan.md`
- `docs/architecture/auth-production-completion-plan.md`
- `docs/README.md`

Then inspect any P7-specific implementation/status documents linked by those files. Use the current repository, migrations, tests, workflows, and docs together; do not trust an older prose status report over executable evidence.

## Current implementation areas that must be audited

The branch contains substantial P7 work around platform configuration, secret administration, OpenBao/recovery, readiness, communications/SMTP, managed OIDC, and PostgreSQL projections. Important proof surfaces include at least:

- `src/request_engine/modules/platform_configuration/**`
- `src/request_engine/platform/security/oidc_auth.py`
- `migrations/versions/0080_platform_configuration_governance.py`
- `migrations/versions/0081_platform_configuration_read_boundary.py`
- `migrations/versions/0090_platform_readiness_projection.py`
- `migrations/versions/0093_managed_oidc_projection.py`
- `migrations/versions/0094_managed_oidc_readiness.py`
- `tests/modules/platform_configuration/**`
- `tests/unit/platform/secrets/test_platform_secret_administration.py`
- `tests/db/test_platform_configuration_foundation.py`
- `tests/db/test_platform_configuration_governance.py`
- `tests/db/test_platform_configuration_hot_reload.py`
- `tests/db/test_managed_oidc_projection.py`
- `.github/workflows/p7-platform-configuration-contract.yml`

This list is a starting point, not the full P7 scope. Discover linked code/tests from the authoritative docs.

## Required first actions for the next agent

1. Fetch/checkout `feature/platform-config-openbao-recovery` and record the actual HEAD. If this handoff commit is now HEAD, use its parent/reference above to understand the last code change.
2. Inspect PR #133 and every exact-head GitHub Actions check. Separate failures into product defects, migration defects, test defects, infrastructure/flakes, and workflow-definition defects. Never weaken a meaningful assertion merely to make CI green.
3. If a job failed, inspect the failing step and logs before editing anything. Reproduce locally where practical.
4. Re-read the P7 handoff, recovery plan, and Definition of Done. Build a requirement-to-evidence matrix: requirement -> implementation -> test -> CI/operational proof -> status.
5. Continue implementation for every genuinely missing requirement. Commit small coherent changes and push them to this same branch.
6. After each repair, verify the new exact HEAD rather than relying on a previous green run.

## Completion standard

P7 is not complete merely because unit tests pass. The next agent should only close it when the documented guarantees are both implemented and demonstrated. In particular, verify the requirements around:

- platform ownership/capability boundaries;
- command/read surfaces and PostgreSQL authority;
- secret lifecycle with PostgreSQL metadata and OpenBao secret material kept in the intended trust boundary;
- SMTP configuration validation, testing, activation, and safe failure behavior;
- hot reload / runtime configuration behavior;
- communications configuration behavior;
- managed OIDC administration and readiness;
- rotation semantics and any conditions that deliberately block unsafe rotation;
- readiness projections that fail closed rather than reporting false readiness;
- backup and recovery guarantees;
- OpenBao/Raft snapshot handling where specified;
- restore drills and evidence, not only backup creation;
- clone/restore fencing so a restored clone cannot accidentally behave as the production authority;
- offline/operator recovery and the documented path for regaining administrative access after loss of normal credentials;
- auditability and non-disclosure of secret material;
- CI evidence for the complete P7 proof set.

For backup/restore/OpenBao/recovery items, distinguish carefully between **code exists**, **automated test exists**, and **an operational drill has actually been demonstrated**. A mocked or fake provider may prove wiring but must not be described as proving real-world recovery/delivery if the spec requires stronger evidence.

## Adversarial checks

Before declaring done, actively try to disprove the implementation:

- Can an unauthorized principal read or mutate platform configuration?
- Can plaintext secret material leak through API responses, logs, audit records, database projections, exception messages, or test artifacts?
- Can PostgreSQL claim a secret/configuration is active while OpenBao material is absent, stale, or inaccessible?
- Can a failed SMTP/OIDC validation accidentally activate bad configuration?
- Can concurrent updates, retries, or idempotency races create split-brain state?
- Does process restart preserve the intended configuration state?
- Does hot reload converge safely when one dependency is unavailable?
- Does readiness become green when a required external dependency is actually unusable?
- Can a restored database/OpenBao snapshot start serving as production without the required clone fencing?
- Can recovery bypass the intended authentication/authorization trust root?
- Is there any recovery scenario documented as solved that has never been exercised by an automated or operational proof?

Any `yes` or `unknown` above should be investigated before closure.

## CI note from the stopping point

The previous agent was specifically investigating CI rather than product behavior when work stopped. The last identified workflow defects were real workflow-definition issues, not justification to relax product tests. The repair commit `84fb75d...` should be treated as a CI harness correction. Its resulting exact-head CI had not fully completed when this handoff was written.

## Expected final report

When P7 is actually complete, leave a concise report that states:

- final branch and exact HEAD;
- commits added after this handoff;
- requirements completed;
- tests/proofs executed and their results;
- exact-head CI status;
- any requirement that remains unproven operationally;
- any conscious deviation from the original plan and why the replacement is stronger or safer.

Be explicit about residual risk. If a restore drill, real provider validation, OpenBao operational exercise, or other production-grade proof has not happened, say `NOT PROVEN` rather than translating implementation into evidence.
