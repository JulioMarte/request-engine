#!/usr/bin/env bash
set -euo pipefail

IMAGE="${POSTGRES_IMAGE:-public.ecr.aws/docker/library/postgres:18}"
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

restore_role_catalog() {
  local port="$1" catalog="$2"
  PGHOST=127.0.0.1 \
  PGPORT="$port" \
  PGDATABASE="$DATABASE" \
  PGUSER=postgres \
  PGPASSWORD="$PASSWORD" \
  ROLE_CATALOG="$catalog" \
    uv run python - <<'PY'
import json
import os

import psycopg
from psycopg import sql

catalog = json.loads(open(os.environ["ROLE_CATALOG"], encoding="utf-8").read())

# The sidecar catalog intentionally records credential presence but never the
# credential itself. Request Engine service/definer roles are NOLOGIN roles; a
# password-bearing managed role would require a separately protected credential
# backup and must not be silently reconstructed with a different secret.
password_roles = [role["role_name"] for role in catalog["roles"] if role["has_password"]]
if password_roles:
    raise SystemExit(
        "role catalog contains password-bearing managed roles that cannot be restored "
        "from non-secret evidence: " + ", ".join(password_roles)
    )

with psycopg.connect("") as connection:
    with connection.cursor() as cursor:
        for role in catalog["roles"]:
            exists = cursor.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s",
                (role["role_name"],),
            ).fetchone()
            if exists:
                # The target candidate migrations should already provision the
                # accepted NOLOGIN service/definer roles. The later catalog
                # comparison proves they match the source attributes.
                continue
            attributes = [
                "SUPERUSER" if role["superuser"] else "NOSUPERUSER",
                "INHERIT" if role["inherit"] else "NOINHERIT",
                "CREATEROLE" if role["create_role"] else "NOCREATEROLE",
                "CREATEDB" if role["create_db"] else "NOCREATEDB",
                "LOGIN" if role["can_login"] else "NOLOGIN",
                "REPLICATION" if role["replication"] else "NOREPLICATION",
                "BYPASSRLS" if role["bypass_rls"] else "NOBYPASSRLS",
                f"CONNECTION LIMIT {int(role['connection_limit'])}",
            ]
            if role["valid_until"] is not None:
                attributes.append("VALID UNTIL " + sql.Literal(role["valid_until"]).as_string(connection))
            cursor.execute(
                sql.SQL("CREATE ROLE {} WITH ").format(sql.Identifier(role["role_name"]))
                + sql.SQL(" ".join(attributes))
            )

        for membership in catalog["role_memberships"]:
            cursor.execute(
                sql.SQL("GRANT {} TO {} WITH ADMIN {}, INHERIT {}, SET {}").format(
                    sql.Identifier(membership["parent_role"]),
                    sql.Identifier(membership["member_role"]),
                    sql.SQL("TRUE" if membership["admin_option"] else "FALSE"),
                    sql.SQL("TRUE" if membership["inherit_option"] else "FALSE"),
                    sql.SQL("TRUE" if membership["set_option"] else "FALSE"),
                )
            )

        for role_setting in catalog["role_settings"]:
            role = sql.Identifier(role_setting["role_name"])
            database_name = role_setting["database_name"]
            for setting in role_setting["settings"] or []:
                name, separator, value = setting.partition("=")
                if not separator:
                    raise SystemExit(f"invalid role setting in catalog: {setting!r}")
                if database_name:
                    statement = sql.SQL("ALTER ROLE {} IN DATABASE {} SET {} TO {}").format(
                        role,
                        sql.Identifier(database_name),
                        sql.Identifier(name),
                        sql.Literal(value),
                    )
                else:
                    statement = sql.SQL("ALTER ROLE {} SET {} TO {}").format(
                        role,
                        sql.Identifier(name),
                        sql.Literal(value),
                    )
                cursor.execute(statement)
PY
}

persist_role_diagnostics() {
  mkdir -p "$(dirname "$OUTPUT")"
  cp "$SOURCE_ROLES" "$(dirname "$OUTPUT")/source-role-catalog.json"
  cp "$TARGET_ROLES" "$(dirname "$OUTPUT")/target-role-catalog.json"
  cp "$ROLE_COMPARISON" "$(dirname "$OUTPUT")/role-catalog-comparison.json"
}

start_pg "$SOURCE" "$SOURCE_PORT"
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PASSWORD}@127.0.0.1:${SOURCE_PORT}/${DATABASE}"
uv run alembic upgrade head
expected_head="$(uv run alembic heads | awk 'NF {print $1}')"
source_head="$(docker exec "$SOURCE" psql -U postgres -d "$DATABASE" -Atc 'SELECT version_num FROM alembic_version')"
test "$source_head" = "$expected_head"

# Roles are cluster-global PostgreSQL objects and are deliberately not part of
# pg_dump. Capture the complete managed topology as a non-secret sidecar. The
# clean target reconstructs this topology before database objects (notably RLS
# policies and SECURITY DEFINER ownership references) are restored.
docker exec -i "$SOURCE" psql -U postgres -d "$DATABASE" -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE request_engine_p7_restore_owner NOLOGIN NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE request_engine_p7_restore_executor NOLOGIN NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE SCHEMA p7_restore_privilege_probe AUTHORIZATION request_engine_p7_restore_owner;
CREATE TABLE p7_restore_privilege_probe.payload (marker text PRIMARY KEY);
ALTER TABLE p7_restore_privilege_probe.payload OWNER TO request_engine_p7_restore_owner;
ALTER TABLE p7_restore_privilege_probe.payload ENABLE ROW LEVEL SECURITY;
ALTER TABLE p7_restore_privilege_probe.payload FORCE ROW LEVEL SECURITY;
CREATE POLICY executor_select ON p7_restore_privilege_probe.payload
  FOR SELECT TO request_engine_p7_restore_executor USING (true);
REVOKE ALL ON SCHEMA p7_restore_privilege_probe FROM PUBLIC;
GRANT USAGE ON SCHEMA p7_restore_privilege_probe TO request_engine_p7_restore_executor;
REVOKE ALL ON p7_restore_privilege_probe.payload FROM PUBLIC;
GRANT SELECT ON p7_restore_privilege_probe.payload TO request_engine_p7_restore_executor;
INSERT INTO p7_restore_privilege_probe.payload VALUES ('restore-proof');
CREATE FUNCTION p7_restore_privilege_probe.owner_identity() RETURNS text
  LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog
  AS $$ SELECT current_user::text $$;
ALTER FUNCTION p7_restore_privilege_probe.owner_identity()
  OWNER TO request_engine_p7_restore_owner;
REVOKE ALL ON FUNCTION p7_restore_privilege_probe.owner_identity() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION p7_restore_privilege_probe.owner_identity()
  TO request_engine_p7_restore_executor;
SQL
export_role_catalog "$SOURCE_PORT" "$SOURCE_ROLES"

# Add a restore oracle that cannot be recreated by migrations alone.
docker exec "$SOURCE" psql -U postgres -d "$DATABASE" -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE public.p7_restore_oracle(marker text PRIMARY KEY); INSERT INTO public.p7_restore_oracle VALUES ('p7-postgres-restored');" >/dev/null
docker exec "$SOURCE" pg_dump -U postgres -d "$DATABASE" \
  --format=custom --file=/tmp/request-engine.dump
docker cp "$SOURCE:/tmp/request-engine.dump" "$DUMP"
test -s "$DUMP"

# Destroy the source before the target exists. A successful read therefore must
# come from the dump, not from a shared volume or still-running source database.
docker rm -f "$SOURCE" >/dev/null
start_pg "$TARGET" "$TARGET_PORT"

# Apply candidate migrations to a disposable bootstrap database. Roles are
# cluster-global, so they remain when this database is dropped; the restore DB
# stays empty until the custom dump is applied.
docker exec "$TARGET" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE DATABASE request_engine_role_bootstrap' >/dev/null
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PASSWORD}@127.0.0.1:${TARGET_PORT}/request_engine_role_bootstrap"
uv run alembic upgrade head

restore_role_catalog "$TARGET_PORT" "$SOURCE_ROLES"
export_role_catalog "$TARGET_PORT" "$TARGET_ROLES"
if ! uv run python scripts/db/compare_role_catalogs.py \
  --expected "$SOURCE_ROLES" \
  --actual "$TARGET_ROLES" \
  --output "$ROLE_COMPARISON"; then
  persist_role_diagnostics
  exit 1
fi
docker exec "$TARGET" dropdb -U postgres request_engine_role_bootstrap

docker cp "$DUMP" "$TARGET:/tmp/request-engine.dump"
docker exec "$TARGET" pg_restore -U postgres -d "$DATABASE" \
  --clean --if-exists --exit-on-error --single-transaction \
  /tmp/request-engine.dump

target_head="$(docker exec "$TARGET" psql -U postgres -d "$DATABASE" -Atc 'SELECT version_num FROM alembic_version')"
marker="$(docker exec "$TARGET" psql -U postgres -d "$DATABASE" -Atc 'SELECT marker FROM public.p7_restore_oracle')"
test "$target_head" = "$expected_head"
test "$marker" = "p7-postgres-restored"

# Owner metadata, ACLs, RLS policy and SECURITY DEFINER behavior must survive
# restore. These assertions are independent SQL observations on the clean DB.
PRIVILEGE_FACTS="$(docker exec "$TARGET" psql -U postgres -d "$DATABASE" -AtF '|' -c \
  "SELECT pg_get_userbyid(c.relowner), has_table_privilege('request_engine_p7_restore_executor', 'p7_restore_privilege_probe.payload', 'SELECT'), c.relrowsecurity, EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname='p7_restore_privilege_probe' AND p.tablename='payload' AND p.policyname='executor_select'), pg_get_userbyid(f.proowner), has_function_privilege('request_engine_p7_restore_executor', 'p7_restore_privilege_probe.owner_identity()', 'EXECUTE'), p7_restore_privilege_probe.owner_identity() FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN pg_proc f JOIN pg_namespace fn ON fn.oid=f.pronamespace WHERE n.nspname='p7_restore_privilege_probe' AND c.relname='payload' AND fn.nspname='p7_restore_privilege_probe' AND f.proname='owner_identity'")"
EXPECTED_PRIVILEGE_FACTS="request_engine_p7_restore_owner|t|t|t|request_engine_p7_restore_owner|t|request_engine_p7_restore_owner"
test "$PRIVILEGE_FACTS" = "$EXPECTED_PRIVILEGE_FACTS"

# Verify the database restore did not mutate the cluster-global role topology.
export_role_catalog "$TARGET_PORT" "$TARGET_ROLES"
if ! uv run python scripts/db/compare_role_catalogs.py \
  --expected "$SOURCE_ROLES" \
  --actual "$TARGET_ROLES" \
  --output "$ROLE_COMPARISON"; then
  persist_role_diagnostics
  exit 1
fi

# The clean target gets a fresh least-privilege runtime LOGIN after NOLOGIN
# object-owner topology is restored. The source-side credential is neither
# exported nor needed; this target-only secret is ephemeral smoke-test data.
TARGET_RUNTIME_PASSWORD="restore-target-only-$$"
docker exec "$TARGET" psql -U postgres -d "$DATABASE" -v ON_ERROR_STOP=1 -c \
  "CREATE ROLE request_engine_p7_restore_runtime LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '$TARGET_RUNTIME_PASSWORD' IN ROLE request_engine_app" >/dev/null
docker exec -e PGPASSWORD="$TARGET_RUNTIME_PASSWORD" "$TARGET" psql \
  -h 127.0.0.1 -U request_engine_p7_restore_runtime -d "$DATABASE" -v ON_ERROR_STOP=1 -Atc \
  "SELECT current_user, pg_has_role(current_user, 'request_engine_app', 'member'), (SELECT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolreplication AND NOT rolbypassrls FROM pg_roles WHERE rolname=current_user)" \
  | grep -qx 'request_engine_p7_restore_runtime|t|t'

persist_role_diagnostics
cat >"$OUTPUT" <<EOF
{
  "schema": "request-engine/postgres-clean-restore-smoke/v1",
  "outcome": "accepted",
  "image": "$IMAGE",
  "source_destroyed_before_target_restore": true,
  "clean_target_container": true,
  "cluster_role_topology_sidecar_restored": true,
  "cluster_role_topology_equivalent": true,
  "custom_format_dump_restored": true,
  "postgres_object_owner_acl_and_rls_preserved": true,
  "target_only_runtime_login_verified": true,
  "alembic_head_preserved": true,
  "restore_oracle_verified": true,
  "credentials_persisted_in_evidence": false
}
EOF
