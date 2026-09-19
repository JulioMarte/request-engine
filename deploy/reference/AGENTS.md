# Reference deployment agent rules

Applies to `deploy/reference/**` in addition to the repository-wide `AGENTS.md`.

`docs/architecture/docker-e2e-ci-plan.md` is the canonical contract for the reusable Docker system/E2E platform.

## Stable deployment, swappable suites

This directory defines the reusable deployment topology under test. Do not create a complete feature-specific Compose topology for every suite.

Normal shape:

```text
deploy/reference/compose.e2e.yaml
        ×
Compose profiles / declared optional services
        ×
suite registry
```

A suite should select required services/profiles; it should not fork the deployment definition merely for convenience.

## Request Engine artifact

- Maintain one immutable Request Engine image for migrate/bootstrap/API/control-plane/worker surfaces unless a documented production/runtime requirement proves separate artifacts necessary.
- PostgreSQL is always a separate service/container.
- Separate API/control-plane/worker containers are valid because their lifecycles/failure domains differ even though they use the same image.
- Do not use a supervisor/mega-container to hide those process boundaries.

## Network and credential boundaries

- Use explicit `edge/test` and `backend` networks for black-box E2E once the reusable platform is implemented.
- PostgreSQL/backend-only services must not be reachable from the normal test runner.
- Do not expose PostgreSQL to the host in the canonical black-box CI profile merely for test convenience.
- Avoid one common environment block that gives every process every DB login/secret. Give each surface only the DSN/secret authority it needs.
- Migration/bootstrap credentials are installation authority and must not leak into runtime services or the test runner.
- Do not add `network_mode: host`, host gateways or Docker socket mounts that bypass runner isolation.

## Optional infrastructure

Worker, Vault, Mailpit, Authentik or future providers may be selected through profiles/registry requirements when not needed by every suite. Do not make every E2E pay for every optional dependency by default.

Vault dev/Mailpit are plumbing evidence only. Their presence must not be described as production secret-management or deliverability certification.

## Lifecycle and readiness

- Use real health/readiness conditions and one-shot completion for migration/bootstrap where appropriate.
- Do not replace deterministic readiness with fixed sleeps.
- Fault-injection lifecycle actions are owned by the outer orchestrator, not by the test runner.
- A worker must not be started with a fabricated zero principal or dummy publisher merely to make CI green; provision real runtime authority for evidence that claims worker behavior.

## Suite independence

The deployment definition may reuse immutable images/layers across suites, but authoritative data/volumes are fresh per suite by default. Do not introduce a shared persistent test database that makes `suite=all` order-dependent.
