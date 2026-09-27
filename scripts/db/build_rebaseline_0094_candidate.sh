#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OUT="${REBASELINE_ARTIFACT_DIR:-.ci/rebaseline-0094}"
EXPECTED_HEAD="0094_managed_oidc_readiness"
mkdir -p "$OUT"

uv sync --all-groups

mapfile -t heads < <(uv run alembic heads | awk 'NF {print $1}')
if [[ ${#heads[@]} -ne 1 || "${heads[0]}" != "$EXPECTED_HEAD" ]]; then
  printf 'rebaseline is pinned to %s; repository heads: %s\n' "$EXPECTED_HEAD" "${heads[*]:-<none>}" >&2
  exit 1
fi

uv run alembic upgrade head
actual_head="$(psql -Atc 'SELECT version_num FROM alembic_version')"
[[ "$actual_head" == "$EXPECTED_HEAD" ]]

uv run python scripts/db/export_role_catalog.py --output "$OUT/source-role-catalog.json"
uv run python scripts/db/export_schema_catalog.py --output "$OUT/source-schema-catalog.json"
uv run python scripts/db/export_seed_data_catalog.py --output "$OUT/source-seed-data-catalog.json"
uv run python scripts/db/analyze_schema_cohesion.py \
  --catalog "$OUT/source-schema-catalog.json" \
  --output "$OUT/source-schema-cohesion.json"
uv run python scripts/db/materialize_rebaseline_roles.py \
  "$OUT/source-role-catalog.json" \
  --output "$OUT/0001_roles.sql"

if [[ -n "${REBASELINE_POSTGRES_CONTAINER:-}" ]]; then
  pg_dump_version="$(docker exec "$REBASELINE_POSTGRES_CONTAINER" pg_dump --version)"
else
  pg_dump_version="$(pg_dump --version)"
fi
if [[ "$pg_dump_version" != *" 18."* ]]; then
  printf 'rebaseline requires PostgreSQL 18 pg_dump, got: %s\n' "$pg_dump_version" >&2
  exit 1
fi

dump_pg18() {
  local database="$1"
  local target="$2"
  shift 2
  local raw="${target}.raw"
  if [[ -n "${REBASELINE_POSTGRES_CONTAINER:-}" ]]; then
    docker exec \
      -e "PGUSER=${PGUSER:-postgres}" \
      -e "PGPASSWORD=${PGPASSWORD:-}" \
      "$REBASELINE_POSTGRES_CONTAINER" \
      pg_dump "$@" "$database" > "$raw"
  else
    pg_dump "$@" --file="$raw" "$database"
  fi
  uv run python scripts/db/sanitize_plain_pg_dump.py "$raw" "$target"
  rm -f "$raw"
}

# Materialize the effective product truth from a clean database that contains
# only migration-owned state. This is intentionally a full dump: schema-only
# loses policy/capability/reference rows inserted by migrations.
dump_pg18 "$PGDATABASE" "$OUT/0001_schema.sql" \
  --no-comments \
  --exclude-table=alembic_version \
  --inserts \
  --rows-per-insert=1

# Independent canonical DDL evidence covers every schema/object pg_dump sees,
# including request_auth/request_platform, types, sequences and ACL-bearing DDL.
dump_pg18 "$PGDATABASE" "$OUT/source-schema-ddl.sql" \
  --schema-only \
  --no-comments \
  --exclude-table=alembic_version

sha256sum "$OUT/0001_roles.sql" "$OUT/0001_schema.sql" > "$OUT/SHA256SUMS"

TARGET_DB="request_engine_rebaseline_0094_proof"
dropdb --if-exists "$TARGET_DB"
createdb "$TARGET_DB"

# Roles are cluster-global and already exist because the historical chain
# created them. The separate clean-cluster job proves the generated role payload.
PGDATABASE="$TARGET_DB" psql -v ON_ERROR_STOP=1 -f "$OUT/0001_schema.sql"

PGDATABASE="$TARGET_DB" uv run python scripts/db/export_schema_catalog.py \
  --output "$OUT/target-schema-catalog.json"
PGDATABASE="$TARGET_DB" uv run python scripts/db/export_seed_data_catalog.py \
  --output "$OUT/target-seed-data-catalog.json"
dump_pg18 "$TARGET_DB" "$OUT/target-schema-ddl.sql" \
  --schema-only \
  --no-comments \
  --exclude-table=alembic_version

uv run python scripts/db/compare_schema_catalogs.py \
  --expected "$OUT/source-schema-catalog.json" \
  --actual "$OUT/target-schema-catalog.json" \
  --output "$OUT/schema-comparison.json"
uv run python scripts/db/compare_seed_data_catalogs.py \
  --expected "$OUT/source-seed-data-catalog.json" \
  --actual "$OUT/target-seed-data-catalog.json" \
  --output "$OUT/seed-data-comparison.json"
uv run python scripts/db/compare_exact_files.py \
  --expected "$OUT/source-schema-ddl.sql" \
  --actual "$OUT/target-schema-ddl.sql" \
  --output "$OUT/schema-ddl-comparison.json"

cat > "$OUT/provenance.json" <<EOF
{
  "schema": "request-engine/rebaseline-candidate/v2",
  "source_head": "$EXPECTED_HEAD",
  "source_commit": "${GITHUB_SHA:-local}",
  "materialization": "effective-postgresql-18-schema-and-migration-owned-data",
  "pg_dump_version": "$pg_dump_version",
  "alembic_history_collapsed": "0001..0094",
  "promoted": false
}
EOF

printf 'rebaseline candidate materialized from %s; schema, DDL and seed/reference state reproduced exactly\n' "$EXPECTED_HEAD"
