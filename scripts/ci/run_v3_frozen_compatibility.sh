#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

RELEASED_V3_SHA="07da8be8625cf67a44e8a0e2ebd8c42f7b6206fc"
V3_BASELINE_REVISION="0001_initial"
RUNTIME_PROOF=".phase6/v3-frozen-compatibility-runtime.json"
RUNTIME_ENV=".ci/v3-frozen-compatibility-runtime.env"
STEP_SUMMARY=".phase6/v3-frozen-compatibility-steps.json"
FINAL_PROOF=".phase6/v3-frozen-compatibility-proof.json"
ALEMBIC_CURRENT=".phase6/v3-frozen-compatibility-alembic-current.txt"
BASELINE_DIFF=".phase6/v3-frozen-baseline-diff.txt"

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
uv sync --all-groups

# V3 release provenance is closed. Post-baseline compatibility must never make a
# later feature green by rewriting the released migration payload, frozen SQL,
# or public-contract baseline. Compare those inputs directly with released main.
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

# Install exactly the released production baseline. Never use Alembic head here:
# head is the current post-baseline product and therefore includes F1 revisions.
uv run alembic upgrade "$V3_BASELINE_REVISION"
uv run alembic current | tee "$ALEMBIC_CURRENT"
if ! grep -Eq '(^|[[:space:]])0001_initial([[:space:]]|$)' "$ALEMBIC_CURRENT"; then
  echo "compatibility database is not pinned to released V3 revision" >&2
  exit 1
fi

uv run python scripts/release/provision_v3_release_runtime.py \
  --output "$RUNTIME_PROOF" \
  --env-output "$RUNTIME_ENV"
# shellcheck disable=SC1090
source "$RUNTIME_ENV"

# These are compatibility checks, not a second release ceremony. The public API
# proof requires every frozen V3 operation/capability/error to remain present,
# while permitting additive post-V3 error codes. The PostgreSQL suite then runs
# current application code against the exact released V3 database.
python scripts/ci/ci_jobs.py postgres-v3-candidate \
  --step public-api-contract \
  --step v3-tests \
  --summary-output "$STEP_SUMMARY" \
  --log-dir .phase6/v3-frozen-compatibility-logs

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
junit_path = Path(".phase6/v3-tests-junit.xml")
output_path = Path(".phase6/v3-frozen-compatibility-proof.json")

api = json.loads(api_path.read_text(encoding="utf-8"))
if api.get("status") != "PASS":
    raise SystemExit("frozen V3 public API compatibility proof did not report PASS")

root = ET.parse(junit_path).getroot()
suites = [root] if root.tag.rsplit("}", 1)[-1] == "testsuite" else list(root)
suites = [suite for suite in suites if suite.tag.rsplit("}", 1)[-1] == "testsuite"]
if not suites:
    raise SystemExit("frozen V3 compatibility JUnit contains no test suite")

totals = {
    key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
    for key in ("tests", "failures", "errors", "skipped")
}
if totals["tests"] <= 0:
    raise SystemExit("frozen V3 compatibility suite collected no tests")
if any(totals[key] != 0 for key in ("failures", "errors", "skipped")):
    raise SystemExit(f"frozen V3 compatibility suite was not clean: {totals}")

payload = {
    "schema_version": 1,
    "proof": "v3-post-baseline-compatibility",
    "status": "PASS",
    "released_v3_commit": os.environ["RELEASED_V3_SHA"],
    "tested_sha": os.environ["TESTED_SHA"],
    "baseline_revision": os.environ["V3_BASELINE_REVISION"],
    "release_evidence_regenerated": False,
    "public_api_contract": {
        "status": api.get("status"),
        "operation_count": api.get("operation_count"),
        "capability_count": api.get("capability_count"),
        "error_code_count": api.get("error_code_count"),
    },
    "v3_tests": totals,
}
output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(output_path)
PY
