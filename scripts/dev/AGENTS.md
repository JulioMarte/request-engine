# Local developer tooling — agent rules

These instructions apply to `scripts/dev/**` and extend the repository-root `AGENTS.md`.

## Publication-boundary authority

Local commits are unrestricted checkpoints. Local publication is different: before a local agent runs `git push`, the exact pushed commit SHA must pass `scripts/dev/certify_push.py` through the managed pre-push hook or the equivalent explicit `certify` command.

The certifier MUST preserve these properties:

- certify the pushed commit in a detached temporary worktree, never the caller's dirty working tree;
- reuse canonical `scripts/ci/ci_jobs.py` step definitions rather than duplicating Ruff/Pyright/pytest commands;
- bind successful cache entries to commit SHA + base SHA + toolchain fingerprint;
- keep PostgreSQL/concurrency/release proof remote unless calibration evidence justifies adding a targeted local proof;
- preserve local commits and working-tree changes on failure;
- retain actionable local logs/attempt metadata under the Git common directory rather than committing them;
- never present `LOCAL_PUSH_CERTIFIED` as merge evidence.

Coding agents MUST NOT use `git push --no-verify`, disable/replace the managed hook, weaken the profile to publish the current change, or choose an unrelated/stale base manually and then claim the actual pushed SHA was certified.

If this publication policy itself changes, keep governance evolution separate from product changes using the existing quality-policy separation rules. GitHub exact-head CI remains authoritative regardless of local certification.

Optimize this tooling for **short, deterministic feedback**, not maximum local proof. A hook that routinely takes minutes or needs heavy services is a workflow defect unless measured remote misses justify that cost.
