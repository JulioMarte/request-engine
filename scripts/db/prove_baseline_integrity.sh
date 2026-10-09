#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <artifact-dir>" >&2
  exit 2
fi

ARTIFACT_DIR="$1"
SOURCE_DB="${PGDATABASE:?PGDATABASE must identify the current-product database}"
ALEMBIC_DIR="$ARTIFACT_DIR/baseline-alembic"
SCHEMA_CATALOG="$ARTIFACT_DIR/baseline-schema-catalog.json"
ROLE_CATALOG="$ARTIFACT_DIR/baseline-role-catalog.json"
SEED_CATALOG="$ARTIFACT_DIR/baseline-seed-data-catalog.json"
SEED_COMPARISON="$ARTIFACT_DIR/baseline-seed-data-comparison.json"
ANALYSIS="$ARTIFACT_DIR/baseline-schema-cohesion-analysis.json"
INTEGRITY="$ARTIFACT_DIR/baseline-integrity.json"
CONTAINER="request-engine-baseline-${RANDOM}-${RANDOM}"
BASELINE_ROOT="migrations/baseline"
BASELINE_REVISION="migrations/versions/0001_initial.py"

if [[ ! -f "$BASELINE_REVISION" ]]; then
  echo "accepted baseline revision is missing: $BASELINE_REVISION" >&2
  exit 1
fi
if [[ ! -f "$BASELINE_ROOT/loader.py" || ! -f "$BASELINE_ROOT/manifest.json" ]]; then
  echo "accepted baseline runtime is incomplete: $BASELINE_ROOT" >&2
  exit 1
fi

rm -rf "$ALEMBIC_DIR"
mkdir -p "$ALEMBIC_DIR/versions"
cp migrations/env.py "$ALEMBIC_DIR/env.py"
cp "$BASELINE_REVISION" "$ALEMBIC_DIR/versions/0001_initial.py"
cp -R "$BASELINE_ROOT" "$ALEMBIC_DIR/baseline"
cp alembic.ini "$ALEMBIC_DIR/alembic.ini"
sed -i "s#^script_location = migrations#script_location = ${ALEMBIC_DIR}#" \
  "$ALEMBIC_DIR/alembic.ini"

# Docker remains the canonical CI default. Native mode is explicit and creates
# its own clean cluster; it never verifies the baseline in the current database.
NATIVE_BIN="${REQUEST_ENGINE_BASELINE_PG_BIN:-}"
NATIVE_ROOT=""
cleanup() {
  local original_status=$?
  if [[ -n "$NATIVE_ROOT" ]]; then
    if [[ -f "$NATIVE_ROOT/data/postmaster.pid" ]] &&
       ! "$NATIVE_BIN/pg_ctl" -D "$NATIVE_ROOT/data" -m fast -w stop >/dev/null 2>&1; then
      echo "baseline PostgreSQL stop failed; retained temporary cluster: $NATIVE_ROOT" >&2
      if [[ "$original_status" -eq 0 ]]; then return 1; fi
      return "$original_status"
    fi
    rm -rf -- "$NATIVE_ROOT"
  elif [[ -z "$NATIVE_BIN" ]]; then
    docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
: "${PGPASSWORD:?PGPASSWORD must be set}"

if [[ -n "$NATIVE_BIN" ]]; then
  for executable in initdb pg_ctl postgres createdb; do
    if [[ ! -x "$NATIVE_BIN/$executable" ]]; then
      echo "native baseline PostgreSQL executable missing: $executable" >&2
      exit 1
    fi
  done
  if [[ "$("$NATIVE_BIN/postgres" --version)" != *" 18."* ]]; then
    echo "native baseline mode requires PostgreSQL 18" >&2
    exit 1
  fi
  NATIVE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/request-engine-baseline-XXXXXX")"
  chmod 700 "$NATIVE_ROOT"
  printf '%s\n' "$PGPASSWORD" > "$NATIVE_ROOT/password"
  chmod 600 "$NATIVE_ROOT/password"
  "$NATIVE_BIN/initdb" -D "$NATIVE_ROOT/data" --username=postgres \
    --auth=scram-sha-256 --pwfile="$NATIVE_ROOT/password" >/dev/null
  rm -- "$NATIVE_ROOT/password"
  PORT="$(python - <<'PORT_PY'
import socket
with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    print(listener.getsockname()[1])
PORT_PY
)"
  "$NATIVE_BIN/pg_ctl" -D "$NATIVE_ROOT/data" \
    -l "$NATIVE_ROOT/postgres.log" \
    -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories='' -p $PORT" \
    -w start >/dev/null
  "$NATIVE_BIN/createdb" --host=127.0.0.1 --port="$PORT" \
    --username=postgres "$SOURCE_DB"
else
  export POSTGRES_PASSWORD="$PGPASSWORD" POSTGRES_DB="$SOURCE_DB"
  docker run --detach \
    --name "$CONTAINER" \
    --env POSTGRES_PASSWORD \
    --env POSTGRES_DB \
    --env POSTGRES_USER=postgres \
    --publish 127.0.0.1::5432 \
    postgres:18 >/dev/null
  unset POSTGRES_PASSWORD POSTGRES_DB
  PORT="$(docker port "$CONTAINER" 5432/tcp | head -n 1 | awk -F: '{print $NF}')"
fi

if [[ -z "$PORT" ]]; then
  echo "failed to resolve accepted-baseline PostgreSQL host port" >&2
  exit 1
fi

baseline_psql=(
  psql
  --host=127.0.0.1
  --port="$PORT"
  --username=postgres
  --dbname="$SOURCE_DB"
  --set=ON_ERROR_STOP=1
)

ready=0
for _ in {1..30}; do
  if "${baseline_psql[@]}" --tuples-only --no-align --command="SELECT 1" \
    >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  if [[ -n "$NATIVE_ROOT" ]]; then
    cat "$NATIVE_ROOT/postgres.log" >&2 || true
  else
    docker logs "$CONTAINER" >&2 || true
  fi
  echo "accepted-baseline PostgreSQL cluster did not become externally ready" >&2
  exit 1
fi

# Exercise only the immutable root revision. Future 0002+ revisions belong to
# the current-product head and must not redefine what accepted 0001 means.
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PGPASSWORD}@127.0.0.1:${PORT}/${SOURCE_DB}"
uv run alembic -c "$ALEMBIC_DIR/alembic.ini" upgrade head
unset MIGRATION_DATABASE_URL

actual_head="$("${baseline_psql[@]}" --tuples-only --no-align \
  --command="SELECT version_num FROM alembic_version")"
if [[ "$actual_head" != "0001_initial" ]]; then
  echo "unexpected accepted-baseline head: $actual_head" >&2
  exit 1
fi

# Installation identity is generated at install time, not copied from the
# rebaseline proof database. Install immutable 0001 into a second clean database
# and require all three installation-local UUIDs to differ.
IDENTITY_PROBE_DB="request_engine_baseline_identity_probe"
admin_psql=(psql --host=127.0.0.1 --port="$PORT" --username=postgres --dbname=postgres --set=ON_ERROR_STOP=1)
"${admin_psql[@]}" --command="CREATE DATABASE \"${IDENTITY_PROBE_DB}\""
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PGPASSWORD}@127.0.0.1:${PORT}/${IDENTITY_PROBE_DB}"
uv run alembic -c "$ALEMBIC_DIR/alembic.ini" upgrade head
unset MIGRATION_DATABASE_URL

identity_query="SELECT instance.id::text, instance.built_in_native_authority_id::text, instance.built_in_workload_authority_id::text FROM request_engine.platform_instance AS instance WHERE instance.singleton_key = 1"
first_identity="$("${baseline_psql[@]}" --tuples-only --no-align --field-separator='|' --command="$identity_query")"
probe_psql=(psql --host=127.0.0.1 --port="$PORT" --username=postgres --dbname="$IDENTITY_PROBE_DB" --set=ON_ERROR_STOP=1)
second_identity="$("${probe_psql[@]}" --tuples-only --no-align --field-separator='|' --command="$identity_query")"
IFS='|' read -r first_instance first_native first_workload <<< "$first_identity"
IFS='|' read -r second_instance second_native second_workload <<< "$second_identity"
for value in "$first_instance" "$first_native" "$first_workload" "$second_instance" "$second_native" "$second_workload"; do
  [[ -n "$value" ]] || { echo "baseline installation identity probe returned an empty UUID" >&2; exit 1; }
done
if [[ "$first_instance" == "$second_instance" || "$first_native" == "$second_native" || "$first_workload" == "$second_workload" ]]; then
  echo "fresh 0001 installations reused an installation-local UUID" >&2
  printf 'first=%s second=%s\n' "$first_identity" "$second_identity" >&2
  exit 1
fi

PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_schema_catalog.py --output "$SCHEMA_CATALOG"
PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_role_catalog.py --output "$ROLE_CATALOG"
PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_seed_data_catalog.py --output "$SEED_CATALOG"
uv run python scripts/db/compare_seed_data_catalogs.py \
  --expected "$BASELINE_ROOT/seed-data-catalog.json" \
  --actual "$SEED_CATALOG" \
  --output "$SEED_COMPARISON"
PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/analyze_schema_cohesion.py \
    --catalog "$SCHEMA_CATALOG" \
    --output "$ANALYSIS"

uv run python scripts/db/verify_accepted_baseline.py \
  --schema-catalog "$SCHEMA_CATALOG" \
  --role-catalog "$ROLE_CATALOG" \
  --seed-data-catalog "$SEED_CATALOG" \
  --analysis "$ANALYSIS" \
  --output "$INTEGRITY"
