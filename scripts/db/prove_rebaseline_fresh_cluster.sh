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
ROLE_BOOTSTRAP="$ARTIFACT_DIR/rebaseline-role-bootstrap.sql"
PAYLOAD_DUMP="$ARTIFACT_DIR/rebaseline-candidate.sql"
FRESH_SCHEMA_CATALOG="$ARTIFACT_DIR/rebaseline-fresh-schema-catalog.json"
FRESH_ROLE_CATALOG="$ARTIFACT_DIR/rebaseline-fresh-role-catalog.json"
FRESH_ANALYSIS="$ARTIFACT_DIR/rebaseline-fresh-schema-cohesion-analysis.json"
SCHEMA_DIFF="$ARTIFACT_DIR/rebaseline-fresh-schema-diff.json"
ROLE_DIFF="$ARTIFACT_DIR/rebaseline-fresh-role-diff.json"
FRESH_CONTAINER="request-engine-rebaseline-fresh-${RANDOM}-${RANDOM}"

if [[ ! -f "$SOURCE_SCHEMA_CATALOG" || ! -f "$PAYLOAD_DUMP" ]]; then
  echo "same-cluster rebaseline evidence must exist before fresh-cluster proof" >&2
  exit 1
fi

cleanup() {
  docker rm --force "$FRESH_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

uv run python scripts/db/export_role_catalog.py --output "$SOURCE_ROLE_CATALOG"
uv run python scripts/db/render_role_bootstrap.py \
  --catalog "$SOURCE_ROLE_CATALOG" \
  --output "$ROLE_BOOTSTRAP"

# This PostgreSQL 18 instance is an independent cluster. It deliberately shares
# neither databases nor cluster-global roles with the canonical migration
# service container, so successful replay proves that the candidate is capable
# of bootstrapping its own audited role topology.
export POSTGRES_PASSWORD="${PGPASSWORD:?PGPASSWORD must be set}"
export POSTGRES_DB="$SOURCE_DB"
docker run --detach \
  --name "$FRESH_CONTAINER" \
  --env POSTGRES_PASSWORD \
  --env POSTGRES_DB \
  --env POSTGRES_USER=postgres \
  --publish 127.0.0.1::5432 \
  postgres:18 >/dev/null
unset POSTGRES_PASSWORD POSTGRES_DB

FRESH_PORT="$(docker port "$FRESH_CONTAINER" 5432/tcp | head -n 1 | awk -F: '{print $NF}')"
if [[ -z "$FRESH_PORT" ]]; then
  echo "failed to resolve fresh PostgreSQL host port" >&2
  exit 1
fi

ready=0
for _ in {1..30}; do
  if docker exec "$FRESH_CONTAINER" pg_isready -U postgres -d "$SOURCE_DB" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" -ne 1 ]]; then
  docker logs "$FRESH_CONTAINER" >&2 || true
  echo "fresh PostgreSQL cluster did not become ready" >&2
  exit 1
fi

fresh_psql=(
  psql
  --host=127.0.0.1
  --port="$FRESH_PORT"
  --username=postgres
  --dbname="$SOURCE_DB"
  --set=ON_ERROR_STOP=1
)
"${fresh_psql[@]}" --file="$ROLE_BOOTSTRAP"
"${fresh_psql[@]}" --file="$PAYLOAD_DUMP"

PGHOST=127.0.0.1 PGPORT="$FRESH_PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_schema_catalog.py --output "$FRESH_SCHEMA_CATALOG"
PGHOST=127.0.0.1 PGPORT="$FRESH_PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/export_role_catalog.py --output "$FRESH_ROLE_CATALOG"
PGHOST=127.0.0.1 PGPORT="$FRESH_PORT" PGDATABASE="$SOURCE_DB" PGUSER=postgres \
  uv run python scripts/db/analyze_schema_cohesion.py \
    --catalog "$FRESH_SCHEMA_CATALOG" \
    --output "$FRESH_ANALYSIS"

uv run python scripts/db/compare_schema_catalogs.py \
  --expected "$SOURCE_SCHEMA_CATALOG" \
  --actual "$FRESH_SCHEMA_CATALOG" \
  --output "$SCHEMA_DIFF"
uv run python scripts/db/compare_role_catalogs.py \
  --expected "$SOURCE_ROLE_CATALOG" \
  --actual "$FRESH_ROLE_CATALOG" \
  --output "$ROLE_DIFF"
