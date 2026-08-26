#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

branch="$(git symbolic-ref --quiet --short HEAD || true)"
if [[ -z "$branch" ]]; then
  echo "ERROR: local F4 verification requires a checked-out branch, not detached HEAD." >&2
  exit 2
fi

if [[ "$branch" != "feature/live-capacity-projection" ]]; then
  echo "ERROR: expected feature/live-capacity-projection, found $branch." >&2
  exit 2
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is dirty. Refusing to destroy local work before forced remote sync." >&2
  echo "Commit, stash, or remove local changes, then rerun." >&2
  git status --short >&2
  exit 2
fi

echo "==> Fetching the newest remote state for $branch"
git fetch --prune origin "+refs/heads/$branch:refs/remotes/origin/$branch"

remote_sha="$(git rev-parse "origin/$branch")"
local_sha="$(git rev-parse HEAD)"
echo "    local : $local_sha"
echo "    remote: $remote_sha"

echo "==> Force-synchronizing the clean local branch to origin/$branch"
git reset --hard "origin/$branch"

synced_sha="$(git rev-parse HEAD)"
if [[ "$synced_sha" != "$remote_sha" ]]; then
  echo "ERROR: forced synchronization did not land on the remote SHA." >&2
  exit 3
fi

echo "==> Running Python quality / architecture / unit / module evidence"
python scripts/ci/ci_jobs.py python-quality

echo "==> Running current-product PostgreSQL 18 / integration / E2E evidence"
bash scripts/ci/run_current_product.sh

echo "==> F4 local closure verification passed at exact remote HEAD: $synced_sha"
