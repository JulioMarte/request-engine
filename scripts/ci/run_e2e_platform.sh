#!/usr/bin/env bash
set -euo pipefail

requested="${1:-smoke}"
registry="scripts/ci/e2e_suite_registry.py"

if [[ "$requested" != "all" && "$requested" != policy:* ]]; then
  exec bash scripts/ci/run_e2e_suite.sh "$requested"
fi

# Build both immutable test artifacts once; every selected suite still gets a fresh world.
artifact_root="${E2E_ARTIFACT_ROOT:-.ci/docker-e2e}"
mkdir -p "$artifact_root"
bash scripts/ci/retry_transient_docker.sh "$artifact_root/platform-build.log" \
  docker compose -f deploy/reference/compose.e2e.yaml --profile runner build api e2e-runner

if [[ "$requested" == "all" ]]; then
  mapfile -t suites < <(python "$registry" list)
else
  policy="${requested#policy:}"
  mapfile -t suites < <(python "$registry" select "$policy")
fi
((${#suites[@]} > 0)) || {
  echo "E2E selector '$requested' resolved no enabled suites" >&2
  exit 1
}

status=0
failed=()
for suite in "${suites[@]}"; do
  echo "::group::E2E suite: $suite"
  if E2E_IMAGES_READY=1 bash scripts/ci/run_e2e_suite.sh "$suite"; then
    echo "E2E suite '$suite' completed successfully"
  else
    rc=$?
    status=1
    failed+=("$suite:$rc")
    echo "E2E suite '$suite' failed with exit code $rc" >&2
  fi
  echo "::endgroup::"
done

if ((status != 0)); then
  printf 'E2E selection %q completed with failures: %s\n' "$requested" "${failed[*]}" >&2
else
  echo "E2E selection '$requested' completed successfully (${#suites[@]} suites)"
fi

exit "$status"
