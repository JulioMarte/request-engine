# Branch and pull-request integration contract

Status: canonical repository workflow policy.

Request Engine uses **one serialized development integration lane**. The purpose is to keep `development` as the only truthful integration state and prevent sibling feature branches from accumulating independently until they become expensive or ambiguous to reconcile.

## Canonical lifecycle

For ordinary feature, fix, refactor, test, documentation, release-proof, or agent work:

```text
current origin/development
        |
        v
one durable work branch
        |
 implement + test + reconcile
        |
        v
PR -> development
        |
 exact-head required CI/evidence
        |
        v
merge
        |
        v
delete merged work branch
        |
        v
next branch starts from NEW origin/development
```

`main` is release-only. The only normal PR to `main` is `development -> main` after the integrated development candidate passes the required release proof.

## One integration lane

`.github/development-integration-lane` records the branch that currently owns the ordinary development integration lane.

Every ordinary PR into `development` MUST set that file to exactly its own `GITHUB_HEAD_REF`.

Example:

```text
feature/example-capability
```

The file is intentionally a single line. Do not turn it into a queue, list of branches, lock database, or workflow scheduler.

Why this works:

1. branch A starts from current `development` and changes the lane from the previously merged branch to `branch-A`;
2. a sibling branch B created from the same older development snapshot would change the same line to `branch-B`;
3. after A merges, current `development` contains `branch-A` as the lane cursor;
4. B must reconcile with that new development state before it can claim the lane as `branch-B` and pass exact-head CI;
5. therefore B cannot remain silently independent of the integration that happened before it.

The cursor does not mean the previous branch remains active after merge. On `development`, it simply records the last integration owner. The next work branch replaces it when that branch is created from the new development head.

## Parallel work policy

The default is **do not open multiple ordinary merge-ready PRs from sibling development snapshots**.

If exploratory work must happen in parallel, it is provisional only. It must not be treated as independently merge-ready. After the current integration owner merges, the provisional work must be rebuilt, rebased, or merged with the new `origin/development`, claim the lane, and rerun all required checks before review.

A dependency on unmerged feature work is never hidden. Do not stack an ordinary PR on another feature branch and present it as if it were based on `development`.

## Temporary branches

`tmp/*` is scratch space only.

A `tmp/*` branch MUST NOT be used as the head of an ordinary pull request. If experimental work becomes durable, create or rebuild a properly named work branch from current `origin/development`, transfer the intended changes, claim the integration lane, validate it, and open the PR from that durable branch.

Temporary branches should be deleted when their experiment/reconciliation purpose is over.

## Merge completion and cleanup

A work branch is complete only when:

1. its complete intended feature/gate is implemented;
2. required narrow and repository tests pass;
3. it is reconciled with current `development`;
4. exact-head required CI/evidence passes;
5. the PR is merged into `development`;
6. the merged branch is deleted.

Do not split one coherent feature/gate into a chain of partially integrated branches merely to make progress look incremental. Split work only when each resulting PR is independently coherent, production-safe, and useful in `development`.

## CI failure meaning

`tests/architecture/test_branch_workflow_contract.py` enforces the topology and integration-lane rules.

A lane mismatch is not a formatting failure. It means the branch does not represent the current serialized integration state. The repair is:

```bash
git fetch origin
# reconcile/rebuild the work branch with current origin/development
# resolve .github/development-integration-lane to exactly the work branch name
# rerun required checks
```

Do not fix that failure by weakening the test, adding bypass names, targeting `main`, targeting another feature branch, or editing the cursor to a value other than the actual PR head.

## Emergency exception

If an operational emergency genuinely requires parallel integration, that is an explicit repository-governance exception, not an implicit agent decision. The exception must be documented in the PR and the branch must still reconcile against the resulting current `development` before merge.
