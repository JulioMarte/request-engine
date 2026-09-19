# GitHub workflow agent rules

Applies to `.github/**` in addition to the repository-wide `AGENTS.md`.

For Docker system/E2E CI, read `docs/architecture/docker-e2e-ci-plan.md` and `scripts/ci/AGENTS.md` before changing workflow behavior.

## Workflow boundary

GitHub Actions is the outer **orchestrator**, not the owner of suite/business logic.

Prefer a small parameterized workflow interface such as:

```text
suite = <registered suite | all>
fault mode = suite-defined/default
artifact retention/profile = policy-driven
```

Repository-local scripts and the suite registry own selection/service/profile resolution. The workflow should invoke them rather than duplicate that logic in YAML.

Do not add a large conditional tree such as `if suite == f01`, `if suite == booking`, etc. for ordinary suites. A new normal suite should not require editing the workflow.

## Required properties

- build/test the exact checkout/merge SHA and record the exact image identity;
- preserve the single Request Engine image across migrate/bootstrap/API/control-plane/worker execution surfaces;
- use a fresh authoritative world per suite by default;
- allow explicit/manual execution of a named suite and `all`;
- keep expensive suite selection conservative for cross-cutting changes; path filters alone are not proof of irrelevance;
- orchestrate fault injection externally; never give the runner Docker socket access;
- collect evidence under `if: always()` without masking the primary failure;
- upload only sanitized/allowlisted artifacts;
- tear down containers, volumes and ephemeral secret material under `if: always()`;
- keep the E2E check experimental/non-blocking only while the current documented calibration phase says so; promotion to required is a deliberate policy change.

## What not to put in YAML

Do not put:

- business journey steps/assertions;
- SQL fixtures for business state;
- feature-specific API payloads;
- a second suite registry;
- reusable secrets in command-line arguments;
- raw Compose/inspect environment dumps as artifacts.

If the workflow needs to know feature semantics to run a normal suite, the boundary is probably wrong; move that knowledge to the suite definition/runner while keeping infrastructure authority in the orchestrator.
