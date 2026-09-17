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

for suite in "${suites[@]}"; do
  echo "::group::E2E suite: $suite"
  E2E_IMAGES_READY=1 bash scripts/ci/run_e2e_suite.sh "$suite"
  echo "::endgroup::"
done
