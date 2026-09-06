#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 <artifact-dir>" >&2
  exit 2
fi

ARTIFACT_DIR="$1"
SOURCE_DB="${PGDATABASE:?PGDATABASE must identify the upgraded source database}"
CANDIDATE_DB="${REBASELINE_CANDIDATE_DB:-request_engine_rebaseline_candidate}"
RAW_DUMP="$ARTIFACT_DIR/rebaseline-candidate.raw.sql"
PAYLOAD_DUMP="$ARTIFACT_DIR/rebaseline-candidate.sql"
SOURCE_CATALOG="$ARTIFACT_DIR/schema-catalog.json"
CANDIDATE_CATALOG="$ARTIFACT_DIR/rebaseline-schema-catalog.json"
CANDIDATE_ANALYSIS="$ARTIFACT_DIR/rebaseline-schema-cohesion-analysis.json"
DIFF="$ARTIFACT_DIR/rebaseline-catalog-diff.json"

mkdir -p "$ARTIFACT_DIR"

# GitHub's Ubuntu image can carry an older PostgreSQL client than the PostgreSQL
# 18 service. Dump through the PostgreSQL 18 image so server/client major
# versions match without changing the workflow runner image or package state.
# Keep ownership and ACL statements; exclude only Alembic bookkeeping.
docker run --rm --network host \
  --env PGPASSWORD \
  postgres:18 \
  pg_dump \
    --host="${PGHOST:-127.0.0.1}" \
    --port="${PGPORT:-5432}" \
    --username="${PGUSER:-postgres}" \
    --dbname="$SOURCE_DB" \
    --schema-only \
    --exclude-table=public.alembic_version \
  > "$RAW_DUMP"

# PostgreSQL 17+ plain dumps may contain psql-only session guard meta-commands
# such as \restrict/\unrestrict. The eventual Alembic baseline is executed via
# Psycopg's simple query protocol, so strip only backslash meta-command lines.
# SQL statements, comments, ownership, grants, RLS, default ACLs and extension
# declarations remain untouched.
uv run python - "$RAW_DUMP" "$PAYLOAD_DUMP" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
lines = source.read_text(encoding="utf-8").splitlines()
meta = [line for line in lines if line.startswith("\\")]
clean = [line for line in lines if not line.startswith("\\")]
if any(not (line.startswith("\\restrict") or line.startswith("\\unrestrict")) for line in meta):
    raise SystemExit(f"unexpected psql meta-command in baseline dump: {meta}")
target.write_text("\n".join(clean) + "\n", encoding="utf-8")
PY

# Replay into a second empty database in the same PostgreSQL cluster. Roles are
# cluster-global and therefore already exist at this stage; a separate clean-
# cluster bootstrap proof is required before the candidate becomes 0001.
psql --dbname=postgres --set=ON_ERROR_STOP=1 \
  --command="DROP DATABASE IF EXISTS ${CANDIDATE_DB} WITH (FORCE)"
psql --dbname=postgres --set=ON_ERROR_STOP=1 \
  --command="CREATE DATABASE ${CANDIDATE_DB}"
trap 'psql --dbname=postgres --command="DROP DATABASE IF EXISTS '"$CANDIDATE_DB"' WITH (FORCE)" >/dev/null 2>&1 || true' EXIT

PGDATABASE="$CANDIDATE_DB" psql --set=ON_ERROR_STOP=1 --file="$PAYLOAD_DUMP"

PGDATABASE="$CANDIDATE_DB" uv run python scripts/db/export_schema_catalog.py \
  --output "$CANDIDATE_CATALOG"
PGDATABASE="$CANDIDATE_DB" uv run python scripts/db/analyze_schema_cohesion.py \
  --catalog "$CANDIDATE_CATALOG" \
  --output "$CANDIDATE_ANALYSIS"

uv run python scripts/db/compare_schema_catalogs.py \
  --expected "$SOURCE_CATALOG" \
  --actual "$CANDIDATE_CATALOG" \
  --output "$DIFF"

rm -f "$RAW_DUMP"
