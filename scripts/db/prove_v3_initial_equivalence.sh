#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGUSER:=postgres}"
: "${PGMAINTENANCE_DB:=postgres}"
: "${V3_EQUIVALENCE_PREFIX:=request_engine_v3_equivalence}"
export PGHOST PGPORT PGUSER

candidate_db="${V3_EQUIVALENCE_PREFIX}_candidate"
initial_db="${V3_EQUIVALENCE_PREFIX}_initial"
work_dir="$(mktemp -d)"
initial_sql="${work_dir}/0001_initial.sql"

cleanup() {
  dropdb --if-exists --maintenance-db="${PGMAINTENANCE_DB}" "${candidate_db}" >/dev/null 2>&1 || true
  dropdb --if-exists --maintenance-db="${PGMAINTENANCE_DB}" "${initial_db}" >/dev/null 2>&1 || true
  rm -rf "${work_dir}"
}
trap cleanup EXIT

for database_name in "${candidate_db}" "${initial_db}"; do
  dropdb --if-exists --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}" >/dev/null
  createdb --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}"
done

python "${repo_root}/scripts/db/build_v3_initial_candidate.py" --output "${initial_sql}"
PGDATABASE="${candidate_db}" bash "${repo_root}/scripts/db/apply_v3_candidate.sh"
PGDATABASE="${initial_db}" psql --set=ON_ERROR_STOP=1 --file="${initial_sql}"

python "${repo_root}/scripts/db/v3_schema_fingerprint.py" \
  --database "${candidate_db}" \
  --json-output "${work_dir}/candidate.json" \
  --sha-output "${work_dir}/candidate.sha256"
python "${repo_root}/scripts/db/v3_schema_fingerprint.py" \
  --database "${initial_db}" \
  --json-output "${work_dir}/initial.json" \
  --sha-output "${work_dir}/initial.sha256"

if ! diff --unified "${work_dir}/candidate.json" "${work_dir}/initial.json"; then
  echo "generated 0001_initial candidate is not catalog-equivalent to the migration chain" >&2
  exit 1
fi

echo "==> generated 0001_initial candidate is catalog-equivalent to the V3 candidate chain"
cat "${work_dir}/candidate.sha256"
