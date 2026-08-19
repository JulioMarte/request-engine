#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

CLEAN_PROOF=".phase6/v3-production-like-clean-start.json"
RUNTIME_PROOF=".phase6/v3-production-like-runtime.json"
RUNTIME_ENV=".ci/v3-production-like-runtime.env"
G17_PROOF=".phase6/v3-final-initial-equivalence.json"
G19_PROOF=".phase6/v3-production-like-bootstrap-proof.json"
MANIFEST=".phase6/v3-evidence-manifest.json"

cleanup_runtime() {
  local original_status=$?
  local cleanup_status=0

  set +e
  if [[ -f "$RUNTIME_PROOF" ]]; then
    uv run python scripts/release/provision_v3_release_runtime.py \
      --output "$RUNTIME_PROOF" \
      --cleanup
    cleanup_status=$?
  fi
  rm -f "$RUNTIME_ENV"
  set -e

  if [[ $original_status -ne 0 ]]; then
    exit "$original_status"
  fi
  exit "$cleanup_status"
}
trap cleanup_runtime EXIT

python scripts/ci/normalize_ci_line_endings.py
mkdir -p .phase6 .ci
python scripts/release/prove_v3_clean_start.py --output "$CLEAN_PROOF"
bash scripts/db/apply_v3_candidate.sh
uv sync --all-groups
uv run python scripts/release/provision_v3_release_runtime.py \
  --output "$RUNTIME_PROOF" \
  --env-output "$RUNTIME_ENV"
# shellcheck disable=SC1090
source "$RUNTIME_ENV"

if [[ "${GITHUB_ACTIONS:-}" == "true" ]] && command -v docker >/dev/null 2>&1; then
  mapfile -t pg_dump_containers < <(
    docker ps --filter ancestor=postgres:18 --format '{{.ID}}'
  )
  if (( ${#pg_dump_containers[@]} > 1 )); then
    echo "multiple PostgreSQL 18 service containers found; refusing ambiguous pg_dump" >&2
    exit 1
  fi
  if (( ${#pg_dump_containers[@]} == 1 )); then
    export REQUEST_ENGINE_PG_DUMP_CONTAINER="${pg_dump_containers[0]}"
  fi
fi

python scripts/ci/ci_jobs.py postgres-v3-candidate \
  --step test-quality-audit \
  --step test-collection-integrity \
  --step schema-fingerprint \
  --step catalog-audit \
  --step worker-query-plans \
  --step queue-query-plans \
  --step booking-query-plans \
  --step public-api-contract \
  --step initial-equivalence \
  --step v3-tests \
  --step concurrency-stability \
  --step test-order-independence \
  --step mutation-probes \
  --step adversarial-failure-proof

uv run python scripts/release/prove_v3_final_initial_equivalence.py \
  --output "$G17_PROOF"
uv run python scripts/release/validate_v3_final_initial_equivalence_artifact.py \
  "$G17_PROOF"

uv run python scripts/release/prove_v3_production_like_bootstrap.py \
  --output "$G19_PROOF"
uv run python scripts/release/build_v3_evidence_manifest.py \
  --output "$MANIFEST"
uv run python scripts/release/build_v3_evidence_manifest.py \
  --output "$MANIFEST" \
  --require-valid
