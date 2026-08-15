# Contributing to Request Engine

## Canonical branch model

Request Engine uses a strict two-stage integration model:

```text
feature / fix / refactor branch
            |
            v
       development
            |
   full integration + release proof
            |
            v
           main
```

### `development`

`development` is the **only canonical integration branch**.

- All independent development work MUST start from the current `origin/development` HEAD.
- All ordinary pull requests MUST target `development`.
- Long-lived branches MUST reconcile with the current `development` before they are considered merge-ready.
- Do not infer the development base from GitHub's default branch.

### `main`

`main` is the **validated/release branch**, not a normal development base.

- Do not start feature, fix, refactor, test, documentation, or agent branches from `main`.
- Do not open ordinary pull requests into `main`.
- The only normal pull request allowed to target `main` is `development -> main` after integration and release gates have been reconfirmed.
- No feature branch may bypass `development` and merge directly into `main`.

## Required workflow

Before creating a branch:

```bash
git fetch origin
git switch development
git pull --ff-only origin development
git switch -c <branch-name>
```

Before declaring a pull request merge-ready, reconcile the branch against the current `development` and rerun the required quality, architecture, PostgreSQL, concurrency, and release gates relevant to the change.

## Parallel and dependent work

Avoid silently branching from another feature branch. This creates hidden stacked dependencies and makes parallel pull requests appear independent when they are not.

If work genuinely depends on an unmerged branch, keep that dependency explicit and do not present the child as independently mergeable into `development`. Prefer waiting for the parent integration or rebuilding/rebasing the child on the updated `development` before merge review.

## LLM and automation rule

LLMs, coding agents, scripts, and other automation MUST NOT use the repository default branch as an implicit base.

They MUST resolve `development`, update it from the remote, and use its current HEAD as the base for ordinary new work. They MUST NOT retarget or merge a feature branch directly into `main` to avoid conflicts.

## Pull request topology

Allowed normal topology:

```text
feature-x -> development
fix-y     -> development
refactor  -> development

development -> main   # release promotion only
```

Disallowed topology:

```text
feature-x -> main
fix-y     -> main
feature-x -> unrelated-feature-y
```

The repository architecture tests enforce the PR target rule in GitHub Actions.
