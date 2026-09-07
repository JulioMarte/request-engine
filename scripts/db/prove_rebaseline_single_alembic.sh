#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <artifact-dir>" >&2
  exit 2
fi

ARTIFACT_DIR="$1"
SOURCE_DB="${PGDATABASE:?PGDATABASE must identify the upgraded source database}"
SOURCE_SCHEMA_CATALOG="$ARTIFACT_DIR/schema-catalog.json"
SOURCE_ROLE_CATALOG="$ARTIFACT_DIR/rebaseline-source-role-catalog.json"
MATERIALIZED_DIR="$ARTIFACT_DIR/rebaseline-single-alembic-candidate"
ALEMBIC_DIR="$ARTIFACT_DIR/rebaseline-single-alembic"
SCHEMA_CATALOG="$ARTIFACT_DIR/rebaseline-single-alembic-schema-catalog.json"
ROLE_CATALOG="$ARTIFACT_DIR/rebaseline-single-alembic-role-catalog.json"
ANALYSIS="$ARTIFACT_DIR/rebaseline-single-alembic-schema-cohesion-analysis.json"
SCHEMA_DIFF="$ARTIFACT_DIR/rebaseline-single-alembic-schema-diff.json"
ROLE_DIFF="$ARTIFACT_DIR/rebaseline-single-alembic-role-diff.json"
CONTAINER="request-engine-rebaseline-alembic-${RANDOM}-${RANDOM}"
MANIFEST="migrations/rebaseline_candidate/manifest.json"

if [[ ! -f "$SOURCE_SCHEMA_CATALOG" || ! -f "$SOURCE_ROLE_CATALOG" ]]; then
  echo "fresh-cluster source catalogs must exist before single-Alembic proof" >&2
  exit 1
fi

rm -rf "$MATERIALIZED_DIR" "$ALEMBIC_DIR"
mkdir -p "$MATERIALIZED_DIR" "$ALEMBIC_DIR/versions"

# This is intentionally a verification operation, not a generator. The
# materializer refuses any artifact whose complete bytes or SHA256 differ from
# the committed manifest, then verifies every materialized schema part.
uv run python scripts/db/materialize_rebaseline_candidate.py \
  --artifact-dir "$ARTIFACT_DIR" \
  --output-dir "$MATERIALIZED_DIR" \
  --manifest "$MANIFEST"
cp "$MANIFEST" "$MATERIALIZED_DIR/manifest.json"

cp migrations/env.py "$ALEMBIC_DIR/env.py"
cp migrations/rebaseline_candidate/0001_initial.py \
  "$ALEMBIC_DIR/versions/0001_initial.py"
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
  echo "failed to resolve single-Alembic PostgreSQL host port" >&2
  exit 1
fi

candidate_psql=(
  psql
  --host=127.0.0.1
  --port="$PORT"
  --username=postgres
  --dbname="$SOURCE_DB"
  --set=ON_ERROR_STOP=1
)

ready=0
for _ in {1..30}; do
  if "${candidate_psql[@]}" --tuples-only --no-align --command="SELECT 1" \
    >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  docker logs "$CONTAINER" >&2 || true
  echo "single-Alembic PostgreSQL cluster did not become externally ready" >&2
  exit 1
fi

"${candidate_psql[@]}" --file="$MATERIALIZED_DIR/0001_roles.sql"

export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PGPASSWORD}@127.0.0.1:${PORT}/${SOURCE_DB}"
export REQUEST_ENGINE_REBASELINE_CANDIDATE_DIR="$MATERIALIZED_DIR"
uv run alembic -c "$ALEMBIC_DIR/alembic.ini" upgrade head
unset MIGRATION_DATABASE_URL REQUEST_ENGINE_REBASELINE_CANDIDATE_DIR

actual_head="$("${candidate_psql[@]}" --tuples-only --no-align \
  --command="SELECT version_num FROM alembic_version")"
if [[ "$actual_head" != "0001_initial" ]]; then
  echo "unexpected single-Alembic head: $actual_head" >&2
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

uv run python scripts/db/compare_schema_catalogs.py \
  --expected "$SOURCE_SCHEMA_CATALOG" \
  --actual "$SCHEMA_CATALOG" \
  --output "$SCHEMA_DIFF"
uv run python scripts/db/compare_role_catalogs.py \
  --expected "$SOURCE_ROLE_CATALOG" \
  --actual "$ROLE_CATALOG" \
  --output "$ROLE_DIFF"
