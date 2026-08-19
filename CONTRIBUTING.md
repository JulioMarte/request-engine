# Contributing to Request Engine

## Canonical branch model

Request Engine uses a strict two-stage integration model with **one serialized development integration lane**:

```text
current development
        |
        v
one feature / fix / release-proof branch
        |
        v
PR -> development
        |
 exact-head CI/evidence
        |
        v
merge + delete branch
        |
        v
next branch starts from NEW development
        |
        v
full integrated release proof
        |
        v
development -> main
```

The detailed normative policy is `docs/architecture/branch-integration-contract.md`.

### `development`

`development` is the **only canonical integration branch**.

- All independent development work MUST start from the current `origin/development` HEAD.
- All ordinary pull requests MUST target `development`.
- Only one ordinary integration lane should be treated as active/merge-ready at a time.
- Long-lived or provisional branches MUST reconcile with the new current `development` after every preceding integration before they are considered merge-ready.
- Do not infer the development base from GitHub's default branch.

### `main`

`main` is the **validated/release branch**, not a normal development base.

- Do not start feature, fix, refactor, test, documentation, or agent branches from `main`.
- Do not open ordinary pull requests into `main`.
- The only normal pull request allowed to target `main` is `development -> main` after integration and release gates have been reconfirmed.
- No feature branch may bypass `development` and merge directly into `main`.

## Required workflow

Before creating a durable work branch:

```bash
git fetch origin
git switch development
git pull --ff-only origin development
git switch -c <branch-name>
```

Then claim the integration lane by setting:

```text
.github/development-integration-lane
```

to exactly the new branch name, one line only. For example:

```text
feature/example-capability
```

The pull-request architecture test compares this value with `GITHUB_HEAD_REF`.

Before declaring the pull request merge-ready:

1. finish the complete coherent feature/gate intended for that branch;
2. fetch current `origin/development` again;
3. reconcile/rebuild the branch if `development` changed;
4. resolve `.github/development-integration-lane` to exactly the current work branch name;
5. rerun the required quality, architecture, PostgreSQL, concurrency, and release evidence relevant to the change;
6. require exact-head CI before merge.

After merge, delete the merged work branch. The next work branch starts from the **new** `development` HEAD and replaces the lane cursor with its own name.

## Parallel and dependent work

Do not treat sibling branches created from the same older `development` snapshot as independently merge-ready.

If exploratory work must happen in parallel, it is provisional only. After the active integration owner merges, the provisional branch must reconcile with the new current `development`, claim the lane, and rerun required checks before review or merge.

Avoid silently branching from another feature branch. This creates hidden stacked dependencies and makes pull requests appear independent when they are not.

If work genuinely depends on an unmerged branch, keep that dependency explicit and do not present the child as independently mergeable into `development`. Prefer waiting for the parent integration or rebuilding/rebasing the child on the updated `development` after the dependency is integrated.

## Temporary branches

`tmp/*` branches are scratch/reconciliation space only.

- They MUST NOT be used as heads of ordinary pull requests.
- If scratch work becomes durable, rebuild or transfer it onto a proper branch created from current `origin/development`.
- Delete temporary branches when their purpose is over.

## LLM and automation rule

LLMs, coding agents, scripts, and other automation MUST NOT use the repository default branch as an implicit base.

They MUST:

1. resolve the current `development` HEAD;
2. confirm whether another ordinary integration lane is already active;
3. create/rebuild work from current `development`;
4. set `.github/development-integration-lane` to their own branch name;
5. target `development`;
6. finish, validate, merge, and delete that branch before starting the next ordinary integration feature.

They MUST NOT create multiple sibling merge-ready PRs merely to continue working ahead, retarget a feature branch to `main` to avoid conflicts, or weaken the branch-workflow fitness test when it reports stale/parallel topology.

## Pull request topology

Allowed normal topology:

```text
feature-x -> development
# merge feature-x; delete branch
# next branch starts from new development
fix-y     -> development

development -> main   # release promotion only
```

Disallowed topology:

```text
feature-x -> main
fix-y     -> main
feature-x -> unrelated-feature-y
tmp/experiment -> development

# two sibling branches both treated as independently merge-ready
old-development -> feature-a -> development
old-development -> feature-b -> development
```

## Integration-lane fitness test

`tests/architecture/test_branch_workflow_contract.py` enforces:

- ordinary PRs target `development`;
- only `development -> main` may target `main`;
- `tmp/*` cannot be ordinary PR heads;
- `.github/development-integration-lane` must equal the actual PR head branch.

A failure such as **Development integration lane mismatch** is an integration-state error, not a style error. Fetch/reconcile with current `origin/development`, claim the lane with the actual branch name, and rerun CI. Do not bypass or relax the test.
