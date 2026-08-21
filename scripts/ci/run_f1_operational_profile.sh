#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Compatibility entrypoint for branch-era/local callers. F1 has been promoted
# into the current-product proof; do not reintroduce an F1-specific Alembic head
# or duplicate the test command inventory here.
if [[ -n "${F1_CI_ARTIFACT_DIR:-}" && -z "${CURRENT_PRODUCT_CI_ARTIFACT_DIR:-}" ]]; then
  export CURRENT_PRODUCT_CI_ARTIFACT_DIR="$F1_CI_ARTIFACT_DIR"
fi

exec bash "$ROOT_DIR/scripts/ci/run_current_product.sh" "$@"
