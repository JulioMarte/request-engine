# CI orchestration agent rules

Applies to `scripts/ci/**` in addition to the repository-wide `AGENTS.md`.

For reusable Docker system/E2E work, `docs/architecture/docker-e2e-ci-plan.md` is the canonical platform contract and `docs/testing/README.md` is the testing architecture entry point.

## Reusable E2E orchestration

CI scripts should implement a **generic E2E platform**, not encode one feature journey as infrastructure.

The governing split is:

```text
stable deployment definition
suite registry / selection policy
generic or explicitly specialized runner
namespaced evidence
```

Rules:

- resolve a suite from the versioned suite registry; do not maintain a second hidden suite matrix in shell/Python;
- keep feature/business assertions inside suite code, not in orchestration scripts;
- map suite requirements to Compose services/profiles generically;
- build immutable Request Engine/runner images once per run when possible, but create a fresh authoritative world per suite by default;
- `all` iterates suites with isolated DB/volumes/state unless an explicit proven-safe group says otherwise;
- path/change-based selection is an optimization signal, never the sole protection for cross-cutting guarantees;
- preserve a manual/conservative route that can execute any named suite and `all`;
- fault injection is performed by the orchestrator only when declared by the suite; the runner must not receive Docker administrative authority;
- use observable barriers/readiness, not timing-only sleeps, for lifecycle/fault coordination;
- fail with an unknown suite/service/profile instead of silently substituting a default.

## Secret and evidence safety

- Never persist raw `docker compose config`, full `docker inspect`, environment dumps or command lines containing secrets as artifacts.
- Produce allowlisted/sanitized projections before writing evidence; regex redaction is defense in depth, not the primary control.
- Do not pass reusable secrets through argv, URLs, labels or container names.
- Keep ephemeral secret material outside `.ci/docker-e2e/`; destroy it in `always` cleanup.
- Keep raw suite state separate from artifact-safe checkpoint/evidence state.
- Evidence collection is best-effort and runs even on failure, but it must never overwrite/mask the original suite/orchestration exit status.
- Namespace evidence by suite so `all` remains diagnosable.

## Isolation proof

The platform must actively prove, not merely assume, the normal black-box runner boundary:

```text
no PostgreSQL route/DSN
no PG* installation credentials
no Docker socket
no Request Engine application package/internals
only declared edge/test networks
```

If a specialized runner needs a different boundary, its owning suite/risk contract must document the exception explicitly.

## Scope discipline

Do not create `run_f01_stack.sh`, `run_booking_stack.sh`, feature-specific complete Compose files, or large feature branches inside the GitHub workflow when the registry + generic orchestrator can express the requirement.

A new suite should normally require registry/test changes, not orchestration changes. Change orchestration only for a new reusable platform capability.
