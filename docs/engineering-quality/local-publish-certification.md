# Local Publish Certification

> **Status:** executable workflow in calibration.
>
> **Purpose:** keep local iteration cheap while preventing an uncertified branch tip from being published to `origin` by normal local workflows.

## Principle

Request Engine distinguishes three actions that must not be conflated:

```text
local commit
    = checkpoint; may be incomplete or red

local push certification
    = exact-SHA publication gate

GitHub exact-head CI
    = authoritative integration evidence
```

Local commits are intentionally unrestricted. The repository does **not** run mandatory architecture or full-quality gates on every commit.

A local `git push`, however, is a publication boundary. The managed `pre-push` hook certifies every commit-bearing tip being sent before Git transmits it.

Local certification never replaces GitHub CI and never makes a pull request merge-ready by itself.

## Why pre-push rather than pre-commit

A coding agent or developer needs cheap checkpoints while reasoning:

```text
commit A  partial implementation
commit B  failing proof added
commit C  type fixes
commit D  final coherent implementation
```

Requiring the full architecture/quality profile for A, B, and C would slow iteration and create pressure to skip hooks or avoid useful commits.

The intended boundary is therefore:

```text
EDIT / TEST / COMMIT freely
            |
            v
         git push
            |
            v
LOCAL PUSH CERTIFICATION
```

## Exact-SHA rule

The certification target is the commit object Git is about to publish, not the developer's current working tree.

A dirty working tree is explicitly allowed. For example:

```text
HEAD = abc123, committed
working tree = abc123 + uncommitted experiment
```

When `abc123` is pushed, certification creates a temporary detached Git worktree at `abc123` and runs the gate there. The uncommitted experiment is not copied into that worktree and is not part of the certificate.

This prevents a false certificate where tests accidentally pass because of local changes that are not included in the pushed commit.

## Fast publication profile

The local profile reuses the canonical step definitions from `scripts/ci/ci_jobs.py` by step ID. Commands are not copied into the hook.

Initial profile:

```text
maintainability / QR-MEGA scan
uv development environment
lockfile consistency
Ruff lint
Ruff format
Pyright
high-confidence secret scan
Python SAST
architecture tests
unit tests
module tests
quality-policy separation
```

The profile intentionally does **not** run the full PostgreSQL, concurrency, historical compatibility, observability, dependency-audit, or release-proof graph on every push.

Those remain remote CI responsibilities during the initial ergonomics calibration.

The reason is operational: a local publication gate that takes several minutes and requires PostgreSQL services/network-dependent vulnerability data becomes an incentive to bypass the gate. The fast profile should catch high-signal defects while preserving a short edit/commit/publish loop.

## Canonical command reuse

`scripts/ci/local_push_profile.py` contains only the selected canonical step IDs. `scripts/ci/ci_jobs.py` remains the source of truth for the commands themselves.

This protects against a local-only implementation of Ruff/Pyright/tests drifting from GitHub CI.

The profile test must fail if a selected step stops existing in the canonical job.

## Hook installation

Git does not safely distribute active hooks merely by cloning a repository. Request Engine therefore tracks a hook **template** at:

```text
.githooks/pre-push
```

and installs a managed executable copy below the repository's Git common directory:

```text
<git-common-dir>/request-engine/hooks/pre-push
```

Install or refresh it with:

```bash
uv run python scripts/dev/install_git_hooks.py
```

Verify without changing configuration:

```bash
uv run python scripts/dev/install_git_hooks.py --check
```

The installer is idempotent and configures local `core.hooksPath` to the managed directory. This avoids relying on executable mode of a tracked hook file across platforms while keeping the hook source reviewable in the repository.

## Pre-push behavior

For each commit-bearing ref on stdin from Git's `pre-push` protocol:

1. resolve the exact local object to a commit SHA;
2. ignore ref deletions because they publish no commit tree;
3. deduplicate identical commit tips;
4. resolve the locally known remote-tracking `development` base, falling back to local `development`;
5. warn when the current working tree is dirty and explicitly exclude those uncommitted changes;
6. consult the successful-certificate cache;
7. if needed, create a temporary detached worktree at the pushed SHA;
8. run the fast canonical publication profile in that worktree;
9. run quality-policy separation against the resolved base SHA;
10. persist concise result metadata and logs below the Git common directory;
11. allow the push only when every pushed commit-bearing tip passes.

The hook does not reset, stash, rebase, amend, squash, or otherwise mutate local source history.

## Base semantics

The local certificate is bound to:

```text
commit SHA
+
locally known development base SHA
+
local toolchain fingerprint
```

The hook does not perform an additional network fetch before every push. This is intentional for latency and credential ergonomics.

Consequences:

- after `git fetch origin`, a changed `origin/development` SHA invalidates the old cache key;
- if the local remote-tracking `development` ref is stale, the certificate honestly means "passed against this local base SHA";
- GitHub PR CI still evaluates the current remote integration state and remains authoritative;
- before merge readiness, the existing serialized-lane contract still requires reconciliation with current `development` and exact-head CI.

If neither a remote-tracking nor local `development` ref exists, certification fails with an instruction to fetch the base rather than silently choosing another branch.

## Cache

Successful certificates live only below `.git` / the Git common directory. They are never committed and GitHub CI never trusts them.

The cache key contains:

```text
certificate schema version
commit SHA
base SHA
OS / architecture
Python major.minor
uv version
```

Therefore changing the code, the known integration base, or the local toolchain causes a new certification run.

A repeated push of the same certified SHA against the same base/toolchain returns a fast `CACHED PASS` instead of rerunning the profile.

`REQUEST_ENGINE_PUSH_CERT_FORCE=1` forces a fresh run when troubleshooting.

## Evidence and local calibration

The local state directory records:

```text
certificates/*.json
attempts.jsonl
runs/<attempt>/python-quality.json
runs/<attempt>/python-quality-signals.json
runs/<attempt>/logs/*
```

Attempt records contain operational gate data such as:

```text
commit SHA
base SHA
PASS/FAIL
cache hit
elapsed seconds
first failed step
review-candidate count
```

These records are for local workflow calibration, not developer/agent productivity scoring and not remote merge evidence.

Run directories are bounded to the most recent 20 attempts by the certifier. Successful certificate metadata may remain because each entry is small and SHA-addressed.

## Failure UX

A failure must preserve the developer's work and say what happened:

```text
REQUEST ENGINE LOCAL PUSH CERTIFICATION
Commit: <exact SHA>
Base:   <exact base SHA>

[PASS] Ruff lint
[PASS] Ruff format
[FAIL] Architecture tests [architecture]
...

[LOCAL_PUSH_CERT] FAIL <sha>
Logs: <git-common-dir>/request-engine/push-certifications/runs/...
Push was not certified. Local commits were not changed.
```

The expected response is:

```text
fix
commit
retry git push
```

not:

```text
reset work
weaken tests
remove the hook
use --no-verify
```

## `--no-verify` and authority

Git technically allows a user to bypass `pre-push` with `git push --no-verify`. The local hook is therefore not a security boundary and must never be presented as one.

Repository coding agents MUST NOT use `--no-verify`, disable the managed hook to make progress, or claim an uncertified SHA is locally certified.

A human repository owner can technically bypass a local hook, but doing so means the SHA is **not locally certified**. Remote GitHub CI remains the authoritative protection either way.

## GitHub-only agents

An agent editing directly through GitHub has no local working tree and therefore no local certificate.

That is a supported mode:

```text
GitHub edit/commit
    -> PR synchronize event
    -> full GitHub CI
    -> agent reads exact failures/artifacts
    -> corrective commit
    -> full CI again
```

No remote CI lane is skipped merely because local certification exists for other contributors.

## WIP commit history

Local intermediate commits may intentionally be red. The publication gate certifies the pushed **tip**, not every ancestor in its history.

That is appropriate for a feature branch, but it creates one integration consideration: knowingly broken checkpoint commits should not become the durable `development` history merely because the final tree is green.

Before merge, use coherent history or an appropriate squash/fixup strategy when preserving intermediate commits would add known-broken checkpoints to integration history. Exact-head CI remains required for the final integration tree.

The repository does not make every intermediate commit independently mergeable as a consequence of local certification.

## Manual certification

When diagnosing the hook or when a local automation environment cannot invoke Git hooks automatically, run the same certifier explicitly:

```bash
uv run python scripts/dev/certify_push.py certify \
  --sha HEAD \
  --base-ref refs/remotes/origin/development
```

Useful controls:

```text
--force     ignore a successful cache entry
--verbose   stream complete canonical step output
```

An agent must not use manual mode with a deliberately weaker base or different SHA and then claim the actual push target was certified.

## What local certification proves

A PASS means:

> The exact commit SHA passed the configured fast local publication profile against the recorded local base SHA and toolchain.

It does **not** mean:

```text
PostgreSQL behavior is proven
concurrency is proven
RLS/privileges are proven
provider/runtime behavior is proven
historical compatibility is proven
current remote development was reconciled
merge readiness is proven
```

Those statements require their actual authoritative proof lanes.

## Calibration questions

After representative use, evaluate:

```text
median / p95 certification duration
first-attempt PASS rate
failure count by step
cache-hit rate
local-green -> remote-red rate
remote failure categories missed locally
hook bypass / installation friction
```

Do not optimize for a synthetic developer score. The useful question is whether the publication gate prevents cheap remote failures at acceptable local latency.

Possible future evolution includes change-impact-based PostgreSQL smoke proofs, but only when observed remote misses justify the added local cost.

## Acceptance scenarios

```text
local WIP/red commit
    -> allowed

same commit with dirty uncommitted files
    -> certify committed SHA in detached worktree
    -> dirty files untouched and excluded

first push of SHA/base/toolchain
    -> run fast profile

retry same SHA/base/toolchain
    -> CACHED PASS

base changes after fetch
    -> cache miss
    -> recertify

architecture failure
    -> push aborted
    -> commits untouched
    -> actionable log retained

ref deletion
    -> no commit certification needed

multiple pushed refs with same commit
    -> certify commit once

agent uses --no-verify
    -> policy violation
    -> cannot claim LOCAL_PUSH_CERTIFIED

GitHub-only edit
    -> no local certificate
    -> full remote CI still runs
```
