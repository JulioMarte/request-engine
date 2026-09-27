#!/usr/bin/env bash
set -euo pipefail

IMAGE="${POSTGRES_IMAGE:-postgres:18}"
SOURCE="p7-pg-source-${GITHUB_RUN_ID:-local}-$$"
TARGET="p7-pg-target-${GITHUB_RUN_ID:-local}-$$"
SOURCE_PORT="${P7_PG_SOURCE_PORT:-15432}"
TARGET_PORT="${P7_PG_TARGET_PORT:-25432}"
PASSWORD="ci-p7-restore-only"
DATABASE="request_engine"
OUTPUT="${1:-.ci/postgres-clean-restore-smoke.json}"
TMP="$(mktemp -d)"
DUMP="$TMP/request-engine.dump"
SOURCE_ROLES="$TMP/source-role-catalog.json"
TARGET_ROLES="$TMP/target-role-catalog.json"
ROLE_COMPARISON="$TMP/role-catalog-comparison.json"

cleanup() {
  docker rm -f "$SOURCE" "$TARGET" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

wait_pg() {
  local container="$1"
  for _ in $(seq 1 60); do
    if docker exec "$container" pg_isready -U postgres -d "$DATABASE" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  docker logs "$container"
  return 1
}

start_pg() {
  local container="$1" port="$2"
  docker run -d --name "$container" \
    -e POSTGRES_DB="$DATABASE" \
    -e POSTGRES_USER=postgres \
    -e POSTGRES_PASSWORD="$PASSWORD" \
    -p "127.0.0.1:$port:5432" \
    "$IMAGE" >/dev/null
  wait_pg "$container"
}

export_role_catalog() {
  local port="$1" output="$2"
  PGHOST=127.0.0.1 \
  PGPORT="$port" \
  PGDATABASE="$DATABASE" \
  PGUSER=postgres \
  PGPASSWORD="$PASSWORD" \
    uv run python scripts/db/export_role_catalog.py --output "$output"
}

bootstrap_audited_roles() {
  local port="$1"
  PGHOST=127.0.0.1 \
  PGPORT="$port" \
  PGDATABASE="$DATABASE" \
  PGUSER=postgres \
  PGPASSWORD="$PASSWORD" \
    uv run python - <<'PY'
import psycopg
from migrations.baseline.loader import ensure_exact_roles

with psycopg.connect("") as connection:
    ensure_exact_roles(connection)
PY
}

start_pg "$SOURCE" "$SOURCE_PORT"
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PASSWORD}@127.0.0.1:${SOURCE_PORT}/${DATABASE}"
uv run alembic upgrade head
expected_head="$(uv run alembic heads | awk 'NF {print $1}')"
source_head="$(docker exec "$SOURCE" psql -U postgres -d "$DATABASE" -Atc 'SELECT version_num FROM alembic_version')"
test "$source_head" = "$expected_head"

# Roles are cluster-global PostgreSQL objects and are deliberately not part of
# pg_dump. Capture their audited topology separately so a clean-cluster restore
# proves that the prerequisite roles are reconstructed before database objects
# (notably RLS policies) refer to them.
export_role_catalog "$SOURCE_PORT" "$SOURCE_ROLES"

# Add a restore oracle that cannot be recreated by migrations alone.
docker exec "$SOURCE" psql -U postgres -d "$DATABASE" -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE public.p7_restore_oracle(marker text PRIMARY KEY); INSERT INTO public.p7_restore_oracle VALUES ('p7-postgres-restored');" >/dev/null
docker exec "$SOURCE" pg_dump -U postgres -d "$DATABASE" \
  --format=custom --no-owner --no-privileges --file=/tmp/request-engine.dump
docker cp "$SOURCE:/tmp/request-engine.dump" "$DUMP"
test -s "$DUMP"

# Destroy the source before the target exists. A successful read therefore must
# come from the dump, not from a shared volume or still-running source database.
docker rm -f "$SOURCE" >/dev/null
start_pg "$TARGET" "$TARGET_PORT"

# A database dump cannot restore cluster-global roles. Recreate the exact,
# checksum-verified Request Engine baseline role topology before pg_restore.
# This is the same audited bootstrap used by migration 0001, without creating
# application schemas that would conflict with the database restore.
bootstrap_audited_roles "$TARGET_PORT"
export_role_catalog "$TARGET_PORT" "$TARGET_ROLES"
uv run python scripts/db/compare_role_catalogs.py \
  --expected "$SOURCE_ROLES" \
  --actual "$TARGET_ROLES" \
  --output "$ROLE_COMPARISON"

docker cp "$DUMP" "$TARGET:/tmp/request-engine.dump"
docker exec "$TARGET" pg_restore -U postgres -d "$DATABASE" \
  --clean --if-exists --no-owner --no-privileges --exit-on-error \
  /tmp/request-engine.dump

target_head="$(docker exec "$TARGET" psql -U postgres -d "$DATABASE" -Atc 'SELECT version_num FROM alembic_version')"
marker="$(docker exec "$TARGET" psql -U postgres -d "$DATABASE" -Atc 'SELECT marker FROM public.p7_restore_oracle')"
test "$target_head" = "$expected_head"
test "$marker" = "p7-postgres-restored"

# Verify the database restore did not mutate the cluster-global role topology.
export_role_catalog "$TARGET_PORT" "$TARGET_ROLES"
uv run python scripts/db/compare_role_catalogs.py \
  --expected "$SOURCE_ROLES" \
  --actual "$TARGET_ROLES" \
  --output "$ROLE_COMPARISON"

mkdir -p "$(dirname "$OUTPUT")"
cat >"$OUTPUT" <<EOF
{
  "schema": "request-engine/postgres-clean-restore-smoke/v1",
  "outcome": "accepted",
  "image": "$IMAGE",
  "source_destroyed_before_target_restore": true,
  "clean_target_container": true,
  "cluster_role_topology_bootstrapped": true,
  "cluster_role_topology_equivalent": true,
  "custom_format_dump_restored": true,
  "alembic_head_preserved": true,
  "restore_oracle_verified": true,
  "credentials_persisted_in_evidence": false
}
EOF
