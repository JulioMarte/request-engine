#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
design_dir="${repo_root}/migrations/sql/design_chain"

files=(
  "03-postgresql-schema.sql"
  "04-postgresql-v2.7-hardening.sql"
  "05-postgresql-v2.8-hardening.sql"
  "06-postgresql-v2.9-integrity.sql"
  "08-postgresql-v2.10-access-surface.sql"
)

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGDATABASE:=request_engine}"
: "${PGUSER:=request_engine}"

export PGHOST PGPORT PGDATABASE PGUSER

for file in "${files[@]}"; do
  echo "==> Applying ${file}"
  psql --set=ON_ERROR_STOP=1 --file="${design_dir}/${file}"
done

echo "==> Request Engine PostgreSQL design chain applied successfully"
