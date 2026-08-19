#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGUSER:=postgres}"
: "${PGMAINTENANCE_DB:=postgres}"
: "${PGCONNECT_TIMEOUT:=5}"
: "${V3_EQUIVALENCE_PREFIX:=request_engine_v3_equivalence}"
export PGHOST PGPORT PGUSER PGCONNECT_TIMEOUT

if [[ ! "${V3_EQUIVALENCE_PREFIX}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "V3_EQUIVALENCE_PREFIX must be a simple PostgreSQL identifier" >&2
  exit 2
fi
if (( ${#V3_EQUIVALENCE_PREFIX} > 53 )); then
  echo "V3_EQUIVALENCE_PREFIX must be at most 53 characters" >&2
  exit 2
fi

candidate_db="${V3_EQUIVALENCE_PREFIX}_candidate"
initial_db="${V3_EQUIVALENCE_PREFIX}_initial"
if [[ "${candidate_db}" == "${PGMAINTENANCE_DB}" \
  || "${initial_db}" == "${PGMAINTENANCE_DB}" ]]; then
  echo "equivalence databases must not equal the maintenance database" >&2
  exit 2
fi
work_dir="$(mktemp -d)"
initial_sql="${work_dir}/0001_initial.sql"
freeze_json="${work_dir}/candidate-freeze.json"

resolve_output() {
  local value="$1"
  if [[ -z "$value" ]]; then
    return 0
  fi
  if [[ "$value" = /* ]]; then
    printf '%s\n' "$value"
  else
    printf '%s/%s\n' "$repo_root" "$value"
  fi
}

copy_artifact() {
  local source="$1"
  local configured="$2"
  local destination
  destination="$(resolve_output "$configured")"
  if [[ -z "$destination" ]]; then
    return 0
  fi
  mkdir -p "$(dirname "$destination")"
  cp "$source" "$destination"
}

cleanup() {
  local original_status=$?
  local cleanup_status=0
  local database_name
  local remaining

  trap - EXIT
  set +e
  for database_name in "${candidate_db}" "${initial_db}"; do
    if ! dropdb --if-exists --force --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}"; then
      echo "failed to drop V3 equivalence database ${database_name}" >&2
      cleanup_status=1
      continue
    fi
    remaining="$(psql --dbname="${PGMAINTENANCE_DB}" --set=ON_ERROR_STOP=1 \
      --tuples-only --no-align --command="
        SELECT count(*) FROM pg_database WHERE datname = '${database_name}';
      ")"
    if [[ $? -ne 0 || "${remaining}" != "0" ]]; then
      echo "could not verify removal of V3 equivalence database ${database_name}" >&2
      cleanup_status=1
    fi
  done
  if ! rm -rf -- "${work_dir}"; then
    echo "failed to remove V3 equivalence work directory ${work_dir}" >&2
    cleanup_status=1
  fi

  if (( original_status != 0 )); then
    exit "${original_status}"
  fi
  exit "${cleanup_status}"
}
trap cleanup EXIT

for database_name in "${candidate_db}" "${initial_db}"; do
  dropdb --if-exists --force --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}" >/dev/null
  createdb --maintenance-db="${PGMAINTENANCE_DB}" --template=template0 "${database_name}"
done

PGDATABASE="${candidate_db}" bash "${repo_root}/scripts/db/apply_v3_candidate.sh"
python "${repo_root}/scripts/db/build_v3_initial_candidate.py" \
  --database "${candidate_db}" \
  --freeze-output "${freeze_json}" \
  --output "${initial_sql}"
python "${repo_root}/scripts/release/validate_v3_candidate_freeze_artifact.py" "${freeze_json}"
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
  echo "generated final-initial candidate is not catalog-equivalent" \
    "to the frozen migration chain" >&2
  exit 1
fi

copy_artifact "$initial_sql" "${V3_EQUIVALENCE_INITIAL_SQL_OUTPUT:-}"
copy_artifact "$freeze_json" "${V3_EQUIVALENCE_FREEZE_OUTPUT:-}"
copy_artifact "${work_dir}/candidate.json" "${V3_EQUIVALENCE_CANDIDATE_SCHEMA_OUTPUT:-}"
copy_artifact "${work_dir}/candidate.sha256" "${V3_EQUIVALENCE_CANDIDATE_SHA_OUTPUT:-}"
copy_artifact "${work_dir}/initial.json" "${V3_EQUIVALENCE_INITIAL_SCHEMA_OUTPUT:-}"
copy_artifact "${work_dir}/initial.sha256" "${V3_EQUIVALENCE_INITIAL_SHA_OUTPUT:-}"

echo "==> generated final-initial candidate is catalog-equivalent to the frozen V3 candidate chain"
cat "${work_dir}/candidate.sha256"
