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
uv run python scripts/db/analyze_schema_cohesion.py \
  --catalog "$OUT/source-schema-catalog.json" \
  --output "$OUT/source-schema-cohesion.json"
uv run python scripts/db/materialize_rebaseline_roles.py \
  "$OUT/source-role-catalog.json" \
  --output "$OUT/0001_roles.sql"

# Materialize effective product truth, not a textual concatenation of 94 migrations.
# The Alembic bookkeeping table is deliberately excluded: a future 0001 migration
# owns the new baseline revision marker itself.
pg_dump \
  --schema-only \
  --no-comments \
  --exclude-table=alembic_version \
  --file="$OUT/0001_schema.sql" \
  "$PGDATABASE"

sha256sum "$OUT/0001_roles.sql" "$OUT/0001_schema.sql" > "$OUT/SHA256SUMS"

TARGET_DB="request_engine_rebaseline_0094_proof"
dropdb --if-exists "$TARGET_DB"
createdb "$TARGET_DB"

# Roles are cluster-global and already exist because the source chain created
# them. A separate clean-cluster CI job proves the generated role payload itself.
# This first pass proves that the materialized schema reproduces the effective
# 0094 catalog without replaying the historical migration chain.
PGDATABASE="$TARGET_DB" psql -v ON_ERROR_STOP=1 -f "$OUT/0001_schema.sql"
PGDATABASE="$TARGET_DB" uv run python scripts/db/export_schema_catalog.py \
  --output "$OUT/target-schema-catalog.json"
uv run python scripts/db/compare_schema_catalogs.py \
  --expected "$OUT/source-schema-catalog.json" \
  --actual "$OUT/target-schema-catalog.json" \
  --output "$OUT/schema-comparison.json"

cat > "$OUT/provenance.json" <<EOF
{
  "schema": "request-engine/rebaseline-candidate/v1",
  "source_head": "$EXPECTED_HEAD",
  "source_commit": "${GITHUB_SHA:-local}",
  "materialization": "effective-postgresql-18-schema",
  "alembic_history_collapsed": "0001..0094",
  "promoted": false
}
EOF

printf 'rebaseline candidate materialized from %s; promotion requires clean-cluster role+schema proof\n' "$EXPECTED_HEAD"
