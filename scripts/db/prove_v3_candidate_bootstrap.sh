#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

: "${PGHOST:=127.0.0.1}"
: "${PGPORT:=5432}"
: "${PGUSER:=request_engine}"
: "${PGMAINTENANCE_DB:=postgres}"
: "${PGCONNECT_TIMEOUT:=5}"
: "${V3_PROOF_DATABASE_PREFIX:=request_engine_v3_phase6}"

export PGHOST PGPORT PGUSER PGCONNECT_TIMEOUT

if [[ ! "${V3_PROOF_DATABASE_PREFIX}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "V3_PROOF_DATABASE_PREFIX must be a simple PostgreSQL identifier" >&2
  exit 2
fi
if (( ${#V3_PROOF_DATABASE_PREFIX} > 61 )); then
  echo "V3_PROOF_DATABASE_PREFIX must be at most 61 characters" >&2
  exit 2
fi

proof_db_a="${V3_PROOF_DATABASE_PREFIX}_a"
proof_db_b="${V3_PROOF_DATABASE_PREFIX}_b"

for command in psql createdb dropdb diff mktemp; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "required command not found: ${command}" >&2
    exit 2
  fi
done

if [[ "${proof_db_a}" == "${PGMAINTENANCE_DB}" || "${proof_db_b}" == "${PGMAINTENANCE_DB}" ]]; then
  echo "proof databases must not equal the maintenance database" >&2
  exit 2
fi

work_dir="$(mktemp -d)"

cleanup() {
  local original_status=$?
  local cleanup_status=0
  local database_name
  local remaining

  trap - EXIT
  set +e
  for database_name in "${proof_db_a}" "${proof_db_b}"; do
    if ! dropdb --if-exists --force --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}"; then
      echo "failed to drop V3 proof database ${database_name}" >&2
      cleanup_status=1
      continue
    fi
    remaining="$(psql --dbname="${PGMAINTENANCE_DB}" --set=ON_ERROR_STOP=1 \
      --tuples-only --no-align --command="
        SELECT count(*) FROM pg_database WHERE datname = '${database_name}';
      ")"
    if [[ $? -ne 0 || "${remaining}" != "0" ]]; then
      echo "could not verify removal of V3 proof database ${database_name}" >&2
      cleanup_status=1
    fi
  done
  if ! rm -rf -- "${work_dir}"; then
    echo "failed to remove V3 proof work directory ${work_dir}" >&2
    cleanup_status=1
  fi

  if (( original_status != 0 )); then
    exit "${original_status}"
  fi
  exit "${cleanup_status}"
}
trap cleanup EXIT

reset_database() {
  local database_name="$1"
  dropdb --if-exists --force --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}" >/dev/null
  createdb --maintenance-db="${PGMAINTENANCE_DB}" "${database_name}"
}

assert_application_surface_absent() {
  local database_name="$1"
  local schema_count

  schema_count="$(PGDATABASE="${database_name}" psql --set=ON_ERROR_STOP=1 --tuples-only --no-align --command="
    SELECT count(*)
      FROM pg_namespace
     WHERE nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin');
  ")"

  if [[ "${schema_count}" != "0" ]]; then
    echo "${database_name} is not a clean V3 application database" >&2
    exit 1
  fi
}

apply_candidate() {
  local database_name="$1"
  echo "==> Applying V3 candidate to ${database_name}"
  PGDATABASE="${database_name}" bash "${repo_root}/scripts/db/apply_v3_candidate.sh"
}

assert_post_bootstrap_contract() {
  local database_name="$1"

  PGDATABASE="${database_name}" psql --set=ON_ERROR_STOP=1 --quiet <<'SQL'
DO $proof$
DECLARE
    missing_schemas text[];
    application_relations bigint;
    unvalidated_constraints bigint;
BEGIN
    SELECT array_agg(expected_schema ORDER BY expected_schema)
      INTO missing_schemas
      FROM unnest(ARRAY['request_admin', 'request_cmd', 'request_engine', 'request_read']) AS expected(expected_schema)
     WHERE NOT EXISTS (
        SELECT 1 FROM pg_namespace n WHERE n.nspname = expected.expected_schema
     );

    IF missing_schemas IS NOT NULL THEN
        RAISE EXCEPTION 'missing V3 schemas: %', missing_schemas;
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_extension
         WHERE extname = 'btree_gist'
    ) THEN
        RAISE EXCEPTION 'required extension btree_gist is missing';
    END IF;

    SELECT count(*)
      INTO application_relations
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')
       AND c.relkind IN ('r', 'p', 'v', 'm', 'S');

    IF application_relations = 0 THEN
        RAISE EXCEPTION 'V3 bootstrap produced no application relations';
    END IF;

    SELECT count(*)
      INTO unvalidated_constraints
      FROM pg_constraint con
      JOIN pg_namespace n ON n.oid = con.connamespace
     WHERE n.nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')
       AND NOT con.convalidated;

    IF unvalidated_constraints <> 0 THEN
        RAISE EXCEPTION 'V3 bootstrap contains % NOT VALID constraints', unvalidated_constraints;
    END IF;
END
$proof$;
SQL
}

write_bootstrap_inventory() {
  local database_name="$1"
  local output_path="$2"

  PGDATABASE="${database_name}" psql \
    --set=ON_ERROR_STOP=1 \
    --tuples-only \
    --no-align \
    --field-separator=$'\t' \
    --output="${output_path}" <<'SQL'
WITH application_namespaces AS (
    SELECT oid, nspname
      FROM pg_namespace
     WHERE nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')
), inventory AS (
    SELECT 'schema'::text AS object_kind,
           n.nspname::text AS identity,
           ''::text AS detail
      FROM application_namespaces n

    UNION ALL

    SELECT 'relation',
           format('%I.%I', n.nspname, c.relname),
           concat('kind=', c.relkind, ';rls=', c.relrowsecurity, ';force_rls=', c.relforcerowsecurity)
      FROM pg_class c
      JOIN application_namespaces n ON n.oid = c.relnamespace
     WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S')

    UNION ALL

    SELECT 'column',
           format('%I.%I.%I', n.nspname, c.relname, a.attname),
           concat(
               'position=', a.attnum,
               ';type=', pg_catalog.format_type(a.atttypid, a.atttypmod),
               ';not_null=', a.attnotnull,
               ';default=', coalesce(pg_get_expr(d.adbin, d.adrelid), '')
           )
      FROM pg_attribute a
      JOIN pg_class c ON c.oid = a.attrelid
      JOIN application_namespaces n ON n.oid = c.relnamespace
      LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
     WHERE c.relkind IN ('r', 'p', 'v', 'm')
       AND a.attnum > 0
       AND NOT a.attisdropped

    UNION ALL

    SELECT 'constraint',
           format('%I.%I', n.nspname, con.conname),
           concat('type=', con.contype, ';validated=', con.convalidated, ';def=', pg_get_constraintdef(con.oid, true))
      FROM pg_constraint con
      JOIN application_namespaces n ON n.oid = con.connamespace

    UNION ALL

    SELECT 'index',
           format('%I.%I', n.nspname, idx.relname),
           pg_get_indexdef(i.indexrelid)
      FROM pg_index i
      JOIN pg_class idx ON idx.oid = i.indexrelid
      JOIN pg_namespace n ON n.oid = idx.relnamespace
     WHERE n.nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')

    UNION ALL

    SELECT 'function',
           format('%I.%I(%s)', n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)),
           concat('language=', l.lanname, ';security_definer=', p.prosecdef, ';volatility=', p.provolatile)
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
      JOIN pg_language l ON l.oid = p.prolang
     WHERE n.nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')

    UNION ALL

    SELECT 'trigger',
           format('%I.%I.%I', n.nspname, c.relname, t.tgname),
           pg_get_triggerdef(t.oid, true)
      FROM pg_trigger t
      JOIN pg_class c ON c.oid = t.tgrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')
       AND NOT t.tgisinternal

    UNION ALL

    SELECT 'policy',
           format('%I.%I.%I', n.nspname, c.relname, p.polname),
           concat(
               'command=', p.polcmd,
               ';permissive=', p.polpermissive,
               ';using=', coalesce(pg_get_expr(p.polqual, p.polrelid), ''),
               ';check=', coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')
           )
      FROM pg_policy p
      JOIN pg_class c ON c.oid = p.polrelid
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname IN ('request_engine', 'request_read', 'request_cmd', 'request_admin')

    UNION ALL

    SELECT 'extension', extname, extversion
      FROM pg_extension
     WHERE extname = 'btree_gist'
)
SELECT object_kind, identity, detail
  FROM inventory
 ORDER BY object_kind, identity, detail;
SQL
}

for proof_db in "${proof_db_a}" "${proof_db_b}"; do
  echo "==> Creating empty proof database ${proof_db}"
  reset_database "${proof_db}"
  assert_application_surface_absent "${proof_db}"
  apply_candidate "${proof_db}"
  assert_post_bootstrap_contract "${proof_db}"
done

inventory_a="${work_dir}/inventory-a.tsv"
inventory_b="${work_dir}/inventory-b.tsv"
write_bootstrap_inventory "${proof_db_a}" "${inventory_a}"
write_bootstrap_inventory "${proof_db_b}" "${inventory_b}"

if ! diff --unified "${inventory_a}" "${inventory_b}"; then
  echo "V3 candidate bootstrap inventories differ" >&2
  exit 1
fi

object_count="$(wc -l < "${inventory_a}" | tr -d ' ')"
echo "==> V3 candidate bootstrap proof passed: two clean databases produced ${object_count} identical inventory rows"
