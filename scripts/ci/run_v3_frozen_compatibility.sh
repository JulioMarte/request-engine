#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

RELEASED_V3_SHA="07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc"
V3_BASELINE_REVISION="0001_initial"
RELEASE_TREE="$ROOT_DIR/.ci/v3-released-tree"
RUNTIME_PROOF="$ROOT_DIR/.phase6/v3-frozen-compatibility-runtime.json"
RUNTIME_ENV="$ROOT_DIR/.ci/v3-frozen-compatibility-runtime.env"
RELEASED_TEST_SUMMARY="$ROOT_DIR/.phase6/v3-released-tests-steps.json"
RELEASED_JUNIT="$ROOT_DIR/.phase6/v3-released-tests-junit.xml"
FINAL_PROOF="$ROOT_DIR/.phase6/v3-frozen-compatibility-proof.json"
ALEMBIC_CURRENT="$ROOT_DIR/.phase6/v3-frozen-compatibility-alembic-current.txt"
BASELINE_DIFF="$ROOT_DIR/.phase6/v3-frozen-baseline-diff.txt"
API_PROOF="$ROOT_DIR/.phase6/v3-public-api-contract.json"

cleanup() {
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
  if git worktree list --porcelain | grep -Fqx "worktree $RELEASE_TREE"; then
    git worktree remove --force "$RELEASE_TREE"
  fi
  set -e

  if [[ $original_status -ne 0 ]]; then
    exit "$original_status"
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT

python scripts/ci/normalize_ci_line_endings.py
mkdir -p .phase6 .ci
uv sync --all-groups

# V3 release provenance is closed. Post-baseline work must never make a later
# feature green by rewriting released migration payloads or frozen evidence.
git cat-file -e "${RELEASED_V3_SHA}^{commit}"
IMMUTABLE_V3_PATHS=(
  migrations/versions/0001_initial.py
  migrations/v3_initial_payload.py
  migrations/sql/v3_initial
  migrations/sql/v3_candidate
  scripts/release/v3_public_api_contract_baseline.py
  docs/release/v3-candidate-freeze.json
)

git diff --name-status "$RELEASED_V3_SHA" -- "${IMMUTABLE_V3_PATHS[@]}" \
  | tee "$BASELINE_DIFF"
if [[ -s "$BASELINE_DIFF" ]]; then
  echo "released V3 baseline/provenance differs from ${RELEASED_V3_SHA}" >&2
  exit 1
fi

# The historical database is intentionally pinned to the released V3 schema.
# Current product behavior belongs to run_current_product.sh and Alembic head.
uv run alembic upgrade "$V3_BASELINE_REVISION"
uv run alembic current | tee "$ALEMBIC_CURRENT"
if ! grep -Eq '(^|[[:space:]])0001_initial([[:space:]]|$)' "$ALEMBIC_CURRENT"; then
  echo "historical V3 database is not pinned to released V3 revision" >&2
  exit 1
fi

uv run python scripts/release/provision_v3_release_runtime.py \
  --output "$RUNTIME_PROOF" \
  --env-output "$RUNTIME_ENV"
# shellcheck disable=SC1090
source "$RUNTIME_ENV"

# Preserve every released V3 API/capability contract exactly while allowing
# additive post-V3 operations and capabilities. Frozen evidence is provenance,
# not a ceiling on later product development.
uv run python scripts/release/prove_v3_public_api_compatibility.py \
  --output "$API_PROOF"

# Historical question: does the released V3 tree still reproduce its own
# PostgreSQL behavior on its own released schema? Run the released source/tests,
# not current post-V3 application code, so provenance cannot freeze the future.
rm -rf "$RELEASE_TREE"
git worktree add --detach "$RELEASE_TREE" "$RELEASED_V3_SHA"
(
  cd "$RELEASE_TREE"
  uv sync --all-groups
  python scripts/ci/ci_jobs.py postgres-v3-candidate \
    --step v3-tests \
    --summary-output "$RELEASED_TEST_SUMMARY" \
    --log-dir "$ROOT_DIR/.phase6/v3-released-test-logs"
)
cp "$RELEASE_TREE/.phase6/v3-tests-junit.xml" "$RELEASED_JUNIT"

export RELEASED_V3_SHA V3_BASELINE_REVISION
TESTED_SHA="$(git rev-parse HEAD)"
export TESTED_SHA
uv run python - <<'PY'
from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path

api_path = Path(".phase6/v3-public-api-contract.json")
junit_path = Path(".phase6/v3-released-tests-junit.xml")
output_path = Path(".phase6/v3-frozen-compatibility-proof.json")

api = json.loads(api_path.read_text(encoding="utf-8"))
if api.get("status") != "PASS":
    raise SystemExit("current V3 public API compatibility proof did not report PASS")

root = ET.parse(junit_path).getroot()
suites = [root] if root.tag.rsplit("}", 1)[-1] == "testsuite" else list(root)
suites = [suite for suite in suites if suite.tag.rsplit("}", 1)[-1] == "testsuite"]
if not suites:
    raise SystemExit("released V3 historical JUnit contains no test suite")

totals = {
    key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
    for key in ("tests", "failures", "errors", "skipped")
}
if totals["tests"] <= 0:
    raise SystemExit("released V3 historical suite collected no tests")
if any(totals[key] != 0 for key in ("failures", "errors", "skipped")):
    raise SystemExit(f"released V3 historical suite was not clean: {totals}")

payload = {
    "schema_version": 2,
    "proof": "v3-current-api-compatibility-and-historical-reproducibility",
    "status": "PASS",
    "released_v3_commit": os.environ["RELEASED_V3_SHA"],
    "tested_sha": os.environ["TESTED_SHA"],
    "baseline_revision": os.environ["V3_BASELINE_REVISION"],
    "release_evidence_regenerated": False,
    "current_public_api_contract": {
        "status": api.get("status"),
        "operation_count": api.get("operation_count"),
        "capability_count": api.get("capability_count"),
        "error_code_count": api.get("error_code_count"),
    },
    "released_v3_tests": totals,
}
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(output_path)
PY
