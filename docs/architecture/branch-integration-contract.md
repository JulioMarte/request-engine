# Branch and pull-request integration contract

Status: canonical repository workflow policy.

Request Engine uses **one serialized development integration lane**. The purpose is to keep `development` as the only truthful integration state and prevent sibling feature branches from accumulating independently until they become expensive or ambiguous to reconcile.

This policy coordinates integration. It is **not** a product-architecture freeze. Intentional evolution of module boundaries, contracts, schema or capability surfaces is governed by `pre-production-evolution-policy.md` and must be proven on the integrated branch; the lane rule must not be used as a reason to preserve obsolete product design.

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

## Commit and CI checkpoint discipline

The active PR head is a **CI checkpoint, not a remote scratchpad**. Moving it may start the full repository workflow, so related implementation edits MUST be batched deliberately.

For one coherent implementation/fix iteration:

1. prepare the complete related edit set before moving the PR head;
2. run the narrowest available local/static checks first when the execution environment permits it;
3. review the whole batch for obvious lint, typing, effective-line budget, migration-chain, surface-registry and fixture/precondition issues;
4. publish one cohesive checkpoint commit for that batch;
5. use CI for repository-wide and environment-dependent proof;
6. when CI fails, inspect the complete failure output and batch all related corrections into the next checkpoint instead of committing one fix per reported line or file;
7. require successful exact-head CI on the final merge candidate exactly as before.

For agents and automation, one remote file write MUST NOT imply one commit on the active PR branch when a multi-file tree/commit, local staging followed by one push, or another atomic batching mechanism is available. Contents-API helpers that create a commit per file are unsuitable for a multi-file correction directly on the PR head unless no batching mechanism exists.

A running CI checkpoint SHOULD be allowed to finish while it remains useful. Supersede it only when its head is already known to be obsolete or an urgent correctness/security issue requires an immediate replacement. Do not generate speculative micro-commits merely to discover the next lint, format, typing, or file-budget error remotely.

Scratch or `tmp/*` branches may be used to assemble provisional work without moving the PR head, but they remain scratch space: they MUST NOT become ordinary merge-ready PR heads or bypass reconciliation with current `development`. Promote the intended result to the durable work branch as one cohesive checkpoint.

This discipline reduces redundant CI work; it does **not** weaken CI. Only successful evidence for the exact final head can make a branch merge-ready.

Merged integration states also carry their own evidence: CI runs on every `development` and `main` merge SHA, so the canonical lane's verdict exists for the integrated state itself and not only for the PR head that produced it. This supplements, and never replaces, the exact-head PR gate.

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

This restriction applies to **integration topology**, not to accepted architecture evolution. If a feature legitimately changes product architecture, the branch should still claim the lane and reconcile with `development`; then the affected architecture tests/contracts may evolve together according to the pre-production evolution policy.

## Emergency exception

If an operational emergency genuinely requires parallel integration, that is an explicit repository-governance exception, not an implicit agent decision. The exception must be documented in the PR and the branch must still reconcile against the resulting current `development` before merge.
