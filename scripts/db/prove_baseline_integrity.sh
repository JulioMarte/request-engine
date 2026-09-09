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

cleanup() {
  docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

export POSTGRES_PASSWORD="${PGPASSWORD:?PGPASSWORD must be set}"
export POSTGRES_DB="$SOURCE_DB"
docker run --detach \
  --name "$CONTAINER" \
  --env POSTGRES_PASSWORD \
  --env POSTGRES_DB \
  --env POSTGRES_USER=postgres \
  --publish 127.0.0.1::5432 \
  postgres:18 >/dev/null
unset POSTGRES_PASSWORD POSTGRES_DB

PORT="$(docker port "$CONTAINER" 5432/tcp | head -n 1 | awk -F: '{print $NF}')"
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
  docker logs "$CONTAINER" >&2 || true
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

PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_schema_catalog.py --output "$SCHEMA_CATALOG"
PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_role_catalog.py --output "$ROLE_CATALOG"
PGHOST=127.0.0.1 PGPORT="$PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/analyze_schema_cohesion.py \
    --catalog "$SCHEMA_CATALOG" \
    --output "$ANALYSIS"

uv run python scripts/db/verify_accepted_baseline.py \
  --schema-catalog "$SCHEMA_CATALOG" \
  --role-catalog "$ROLE_CATALOG" \
  --analysis "$ANALYSIS" \
  --output "$INTEGRITY"
