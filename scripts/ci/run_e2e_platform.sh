#!/usr/bin/env bash
set -euo pipefail

requested="${1:-smoke}"

if [[ "$requested" != "all" ]]; then
  exec bash scripts/ci/run_e2e_suite.sh "$requested"
fi

# Build both immutable test artifacts once; each suite still gets a fresh Compose project/world.
docker compose -f deploy/reference/compose.e2e.yaml --profile runner build api e2e-runner

mapfile -t suites < <(python scripts/ci/e2e_suite_registry.py list)
((${#suites[@]} > 0)) || { echo "no enabled E2E suites are registered" >&2; exit 1; }

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
  printf 'E2E all completed with failures: %s\n' "${failed[*]}" >&2
else
  echo "E2E all completed successfully (${#suites[@]} suites)"
fi

exit "$status"
