#!/usr/bin/env bash
set -euo pipefail

# Destructive, disposable Docker-host integration proof. It exercises the real
# recovery_bundle.py CLI and an HTTPS object-store fixture; it is not an S3,
# cloud durability, or production network-isolation claim.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_ID="${GITHUB_RUN_ID:-local}-$$"
PG_IMAGE="${P7_PG_IMAGE:-public.ecr.aws/docker/library/postgres:18}"
PYTHON_IMAGE="${P7_PYTHON_IMAGE:-public.ecr.aws/docker/library/python:3.13-slim}"
BAO_IMAGE="${P7_OPENBAO_IMAGE:-ghcr.io/openbao/openbao:2.6.1}"
OUTPUT="${1:-.ci/offhost-recovery-smoke.json}"
LAB="$(mktemp -d "${TMPDIR:-/tmp}/p7-offhost-${RUN_ID}-XXXXXX")"
TLS_DIR="$LAB/tls"
PG_SOURCE="p7-offhost-pg-source-$RUN_ID"
PG_TARGET="p7-offhost-pg-target-$RUN_ID"
BAO_SOURCE="p7-offhost-bao-source-$RUN_ID"
BAO_TARGET="p7-offhost-bao-target-$RUN_ID"
STORE="p7-offhost-store-$RUN_ID"
PG_SOURCE_VOL="${PG_SOURCE}-data"
PG_TARGET_VOL="${PG_TARGET}-data"
BAO_SOURCE_VOL="${BAO_SOURCE}-data"
BAO_TARGET_VOL="${BAO_TARGET}-data"
STORE_VOL="${STORE}-objects"
STORE_NET="${STORE}-net"
SOURCE_NET="p7-offhost-source-$RUN_ID"
TARGET_NET="p7-offhost-target-$RUN_ID"
PG_SOURCE_PORT=""
MIGRATION_IMAGE="p7-recovery-cli:$RUN_ID"
DATABASE="request_engine"
PASSWORD="$(openssl rand -hex 24)"
STORE_TOKEN="$(openssl rand -hex 32)"
export P7_OBJECT_STORE_TOKEN="$STORE_TOKEN"
export POSTGRES_PASSWORD="$PASSWORD"
SOURCE_KEY=""
SOURCE_ROOT_TOKEN=""
TARGET_KEY=""
TARGET_ROOT_TOKEN=""

cleanup() {
  docker rm -f "$PG_SOURCE" "$PG_TARGET" "$BAO_SOURCE" "$BAO_TARGET" "$STORE" >/dev/null 2>&1 || true
  docker volume rm -f "$PG_SOURCE_VOL" "$PG_TARGET_VOL" "$BAO_SOURCE_VOL" "$BAO_TARGET_VOL" "$STORE_VOL" >/dev/null 2>&1 || true
  docker network rm "$STORE_NET" "$SOURCE_NET" "$TARGET_NET" >/dev/null 2>&1 || true
  docker image rm "p7-age-cli:$RUN_ID" >/dev/null 2>&1 || true
  docker image rm "$MIGRATION_IMAGE" >/dev/null 2>&1 || true
  rm -rf "$LAB"
}
trap cleanup EXIT

die() { echo "off-host recovery smoke: $*" >&2; exit 1; }
wait_pg() {
  local container="$1"
  for _ in $(seq 1 90); do
    if docker exec "$container" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  docker logs "$container" >&2 || true
  return 1
}
wait_bao() {
  local container="$1"
  for _ in $(seq 1 90); do
    if docker exec "$container" sh -c 'BAO_ADDR=http://127.0.0.1:8200 bao status >/dev/null 2>&1; code=$?; [ "$code" -eq 0 ] || [ "$code" -eq 2 ]'; then return 0; fi
    sleep 1
  done
  docker logs "$container" >&2 || true
  return 1
}
start_bao() {
  local container="$1" volume="$2" network="$3" config="$4"
  docker volume create "$volume" >/dev/null
  docker run --rm --user 0:0 --mount "type=volume,src=$volume,dst=/openbao/data" "$BAO_IMAGE" \
    sh -ec 'mkdir -p /openbao/data && chown -R openbao:openbao /openbao/data && chmod 700 /openbao/data'
  docker run -d --name "$container" --network "$network" --cap-add IPC_LOCK \
    --mount "type=volume,src=$volume,dst=/openbao/data" \
    --mount "type=bind,src=$config,dst=/openbao/config/lab.hcl,readonly" \
    "$BAO_IMAGE" server -config=/openbao/config/lab.hcl >/dev/null
  wait_bao "$container"
}
init_bao() {
  local container="$1" key_var="$2" token_var="$3"
  local raw key token
  raw="$(docker exec "$container" sh -c 'BAO_ADDR=http://127.0.0.1:8200 bao operator init -key-shares=1 -key-threshold=1 -format=json')"
  key="$(printf '%s' "$raw" | jq -er '.unseal_keys_b64[0]')"
  token="$(printf '%s' "$raw" | jq -er '.root_token')"
  P7_LAB_UNSEAL_KEY="$key" docker exec -e P7_LAB_UNSEAL_KEY "$container" \
    sh -c 'BAO_ADDR=http://127.0.0.1:8200 bao operator unseal "$P7_LAB_UNSEAL_KEY" >/dev/null'
  printf -v "$key_var" '%s' "$key"
  printf -v "$token_var" '%s' "$token"
}

for tool in docker jq openssl uv; do command -v "$tool" >/dev/null || die "required host tool missing: $tool"; done
docker info >/dev/null 2>&1 || die 'Docker daemon is unavailable'
mkdir -p "$LAB" "$(dirname "$OUTPUT")"
bash "$ROOT/scripts/ci/create_lab_tls.sh" "$TLS_DIR" objectstore-lab
for required in ca.crt objectstore-lab.crt objectstore-lab.key; do [[ -s "$TLS_DIR/$required" ]] || die "missing lab TLS file $TLS_DIR/$required"; done
chmod 0600 "$TLS_DIR/ca.key" 2>/dev/null || true

docker build -f "$ROOT/scripts/ci/Dockerfile.p7-age-cli" -t "p7-age-cli:$RUN_ID" "$ROOT" >/dev/null
docker build -f "$ROOT/deploy/reference/Dockerfile" -t "$MIGRATION_IMAGE" "$ROOT" >/dev/null
AGE_IMAGE="p7-age-cli:$RUN_ID"
docker network create "$STORE_NET" --internal >/dev/null
docker network create "$SOURCE_NET" >/dev/null
docker network create "$TARGET_NET" --internal >/dev/null

# A storage volume is the only durable state the object-store container sees.
docker volume create "$STORE_VOL" >/dev/null
docker run --rm --user 0:0 --mount "type=volume,src=$STORE_VOL,dst=/objects" "$PYTHON_IMAGE" \
  python -c 'import os; os.chown("/objects", 10001, 10001); os.chmod("/objects", 0o700)'
mkdir -p "$LAB/store-tls"
cp "$TLS_DIR/objectstore-lab.crt" "$TLS_DIR/objectstore-lab.key" "$LAB/store-tls/"
chmod 0644 "$LAB/store-tls/objectstore-lab.crt" "$LAB/store-tls/objectstore-lab.key"
docker run -d --name "$STORE" --network "$STORE_NET" --network-alias objectstore-lab --user 10001:10001 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount "type=volume,src=$STORE_VOL,dst=/objects" \
  --mount "type=bind,src=$ROOT/scripts/ci/offhost_object_store.py,dst=/server.py,readonly" \
  --mount "type=bind,src=$LAB/store-tls/objectstore-lab.crt,dst=/server.crt,readonly" \
  --mount "type=bind,src=$LAB/store-tls/objectstore-lab.key,dst=/server.key,readonly" \
  -e P7_OBJECT_STORE_TOKEN "$PYTHON_IMAGE" \
  python /server.py --root /objects --tls-cert /server.crt --tls-key /server.key >/dev/null
store_ready=false
for _ in $(seq 1 30); do
  if docker run --rm --network "$STORE_NET" --mount "type=bind,src=$TLS_DIR/ca.crt,dst=/ca.crt,readonly" \
      "$PYTHON_IMAGE" python -c \
      'import ssl,urllib.request; r=urllib.request.urlopen("https://objectstore-lab:8443/healthz",context=ssl.create_default_context(cafile="/ca.crt"),timeout=2); raise SystemExit(0 if r.status==204 else 1)' 2>/dev/null; then store_ready=true; break; fi
  sleep 1
done
[[ "$store_ready" == true ]] || die 'new object store did not become ready'

# Distinct PostgreSQL source container/volume; migration schemas and test rows
# originate here and are later destroyed before any destination is created.
docker volume create "$PG_SOURCE_VOL" >/dev/null
docker run -d --name "$PG_SOURCE" --network "$SOURCE_NET" -e POSTGRES_PASSWORD \
  -e POSTGRES_DB="$DATABASE" -p '127.0.0.1::5432' \
  --mount "type=volume,src=$PG_SOURCE_VOL,dst=/var/lib/postgresql" "$PG_IMAGE" >/dev/null
PG_SOURCE_PORT="$(docker port "$PG_SOURCE" 5432/tcp | sed 's/.*://')"
wait_pg "$PG_SOURCE"
export MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:$PASSWORD@127.0.0.1:$PG_SOURCE_PORT/$DATABASE"
uv run alembic upgrade head
docker exec -i "$PG_SOURCE" psql -U postgres -d "$DATABASE" -v ON_ERROR_STOP=1 <<'SQL'
CREATE SCHEMA p7_offhost_probe AUTHORIZATION request_engine_app;
CREATE TABLE p7_offhost_probe.payload(tenant text NOT NULL, marker text NOT NULL);
ALTER TABLE p7_offhost_probe.payload OWNER TO request_engine_app;
ALTER TABLE p7_offhost_probe.payload ENABLE ROW LEVEL SECURITY;
ALTER TABLE p7_offhost_probe.payload FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_read ON p7_offhost_probe.payload FOR SELECT TO request_engine_worker
  USING (tenant = current_setting('p7.tenant', true));
GRANT USAGE ON SCHEMA p7_offhost_probe TO request_engine_worker;
GRANT SELECT ON p7_offhost_probe.payload TO request_engine_worker;
INSERT INTO p7_offhost_probe.payload VALUES
 ('tenant-a', 'offhost-data-restored'), ('tenant-b', 'must-stay-hidden');
CREATE FUNCTION p7_offhost_probe.owner_identity() RETURNS text
  LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$ SELECT current_user::text $$;
ALTER FUNCTION p7_offhost_probe.owner_identity() OWNER TO request_engine_app;
REVOKE ALL ON FUNCTION p7_offhost_probe.owner_identity() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION p7_offhost_probe.owner_identity() TO request_engine_worker;
CREATE TABLE public.p7_offhost_restore_oracle(marker text PRIMARY KEY);
INSERT INTO public.p7_offhost_restore_oracle VALUES ('offhost-data-restored');
SQL

cat >"$LAB/openbao.hcl" <<'HCL'
ui = false
disable_mlock = true
storage "raft" {
  path = "/openbao/data"
  node_id = "p7-offhost-restore"
}
listener "tcp" {
  address = "0.0.0.0:8200"
  tls_disable = true
}
api_addr = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"
HCL
docker volume create "$BAO_SOURCE_VOL" >/dev/null
start_bao "$BAO_SOURCE" "$BAO_SOURCE_VOL" "$SOURCE_NET" "$LAB/openbao.hcl"
init_bao "$BAO_SOURCE" SOURCE_KEY SOURCE_ROOT_TOKEN
BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN="$SOURCE_ROOT_TOKEN" docker exec \
  -e BAO_ADDR -e BAO_TOKEN "$BAO_SOURCE" sh -c \
  'bao secrets enable -path=secret -version=2 kv >/dev/null && bao kv put secret/request-engine/offhost marker=p7-offhost-secret-restored >/dev/null'

# Build ephemeral encryption identity, then expose only its paths to the
# recovery CLI. Identity, tokens, TLS material and bundles are erased by trap.
docker run --rm --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$LAB,dst=/workspace" "$AGE_IMAGE" sh -ec \
  'age-keygen -o /workspace/identity.txt 2>/dev/null; chmod 600 /workspace/identity.txt; age-keygen -y /workspace/identity.txt > /workspace/recipient.txt'
RECIPIENT="$(cat "$LAB/recipient.txt")"
mkdir -p "$LAB/bin" "$LAB/artifact" "$LAB/download" "$LAB/tmp"
export TMPDIR="$LAB/tmp"
for tool in age pg_dump pg_restore bao; do ln -s "$ROOT/scripts/ci/p7_recovery_lab_tool.sh" "$LAB/bin/$tool"; done
export PATH="$LAB/bin:$PATH"
export P7_AGE_IMAGE="$AGE_IMAGE" P7_AGE_WORKSPACE="$LAB"
export P7_PG_SOURCE_CONTAINER="$PG_SOURCE" P7_PG_DATABASE="$DATABASE"
export P7_OPENBAO_SOURCE_CONTAINER="$BAO_SOURCE" P7_OPENBAO_SOURCE_TOKEN="$SOURCE_ROOT_TOKEN"
export P7_PYTHON_IMAGE="$PYTHON_IMAGE" P7_OBJECT_STORE_NETWORK="$STORE_NET"
export P7_OBJECT_STORE_CA="$TLS_DIR/ca.crt" P7_OBJECT_STORE_TOKEN="$STORE_TOKEN"
export P7_OBJECT_STORE_URL="https://objectstore-lab:8443"
export P7_LAB_REPOSITORY_ROOT="$ROOT"
export REQUEST_ENGINE_BACKUP_DATABASE_URL="postgresql://postgres:$PASSWORD@127.0.0.1:$PG_SOURCE_PORT/$DATABASE"
export REQUEST_ENGINE_BACKUP_AGE_RECIPIENT="$RECIPIENT"
export REQUEST_ENGINE_BACKUP_OFFSITE_COMMAND="$ROOT/scripts/ci/p7_recovery_offsite_transfer.sh put {artifact} {name}"
uv run python scripts/operations/recovery_bundle.py backup --output-dir "$LAB/artifact" --bao-command bao
BUNDLE="$(find "$LAB/artifact" -maxdepth 1 -name 'request-engine-recovery-*.tar.gz.age' -print -quit)"
[[ -n "$BUNDLE" && -s "$BUNDLE" ]] || die 'recovery CLI did not create an encrypted bundle'
BUNDLE_NAME="$(basename "$BUNDLE")"
cp "$BUNDLE" "$LAB/tampered.age"
python - "$LAB/tampered.age" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
b = bytearray(p.read_bytes())
if not b:
    raise SystemExit("empty encrypted bundle")
b[len(b) // 2] ^= 1
p.write_bytes(b)
PY
P7_OBJECT_STORE_URL="https://objectstore-lab:8443" \
  "$ROOT/scripts/ci/p7_recovery_offsite_transfer.sh" put "$LAB/tampered.age" "tampered-$BUNDLE_NAME"

# Prove loss of source persistence before retrieving anything; storage itself
# is also recreated against its distinct volume before the new client fetches.
docker rm -f "$PG_SOURCE" "$BAO_SOURCE" >/dev/null
docker volume rm -f "$PG_SOURCE_VOL" "$BAO_SOURCE_VOL" >/dev/null
docker volume inspect "$PG_SOURCE_VOL" >/dev/null 2>&1 && die 'source PostgreSQL volume survived destruction'
docker volume inspect "$BAO_SOURCE_VOL" >/dev/null 2>&1 && die 'source OpenBao volume survived destruction'
rm -rf "$LAB/artifact"
rm -f "$LAB/tampered.age"
[[ ! -e "$BUNDLE" ]] || die 'original local backup survived destruction'
docker rm -f "$STORE" >/dev/null
docker run -d --name "$STORE" --network "$STORE_NET" --network-alias objectstore-lab --user 10001:10001 --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --mount "type=volume,src=$STORE_VOL,dst=/objects" \
  --mount "type=bind,src=$ROOT/scripts/ci/offhost_object_store.py,dst=/server.py,readonly" \
  --mount "type=bind,src=$LAB/store-tls/objectstore-lab.crt,dst=/server.crt,readonly" \
  --mount "type=bind,src=$LAB/store-tls/objectstore-lab.key,dst=/server.key,readonly" \
  -e P7_OBJECT_STORE_TOKEN "$PYTHON_IMAGE" \
  python /server.py --root /objects --tls-cert /server.crt --tls-key /server.key >/dev/null
store_ready=false
for _ in $(seq 1 30); do
  if docker run --rm --network "$STORE_NET" --mount "type=bind,src=$TLS_DIR/ca.crt,dst=/ca.crt,readonly" \
      "$PYTHON_IMAGE" python -c \
      'import os,ssl,urllib.request; r=urllib.request.urlopen("https://objectstore-lab:8443/healthz",context=ssl.create_default_context(cafile="/ca.crt"),timeout=2); raise SystemExit(0 if r.status==204 else 1)' 2>/dev/null; then store_ready=true; break; fi
  sleep 1
done
[[ "$store_ready" == true ]] || die 'retained object store did not become ready'
if P7_OBJECT_STORE_TOKEN="invalid-lab-token-which-is-not-authorized" \
  P7_OBJECT_STORE_URL="https://objectstore-lab:8443" \
  "$ROOT/scripts/ci/p7_recovery_offsite_transfer.sh" get "$LAB/download/unauthorized.age" "$BUNDLE_NAME"; then
  die 'object-store accepted an invalid bearer token'
fi
[[ ! -e "$LAB/download/unauthorized.age" ]] || die 'unauthorized GET created a local artifact'
bash "$ROOT/scripts/ci/create_lab_tls.sh" "$LAB/untrusted-tls" objectstore-lab
if P7_OBJECT_STORE_CA="$LAB/untrusted-tls/ca.crt" \
  P7_OBJECT_STORE_URL="https://objectstore-lab:8443" \
  "$ROOT/scripts/ci/p7_recovery_offsite_transfer.sh" get "$LAB/download/untrusted.age" "$BUNDLE_NAME"; then
  die 'object-store TLS validation accepted an untrusted CA'
fi
[[ ! -e "$LAB/download/untrusted.age" ]] || die 'untrusted TLS GET created a local artifact'
P7_OBJECT_STORE_URL="https://objectstore-lab:8443" \
  "$ROOT/scripts/ci/p7_recovery_offsite_transfer.sh" get "$LAB/download/tampered.age" "tampered-$BUNDLE_NAME"
if REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE="$LAB/identity.txt" \
  uv run python scripts/operations/recovery_bundle.py verify "$LAB/download/tampered.age" >/dev/null 2>&1; then
  die 'tampered encrypted bundle unexpectedly verified'
fi
P7_OBJECT_STORE_URL="https://objectstore-lab:8443" \
  "$ROOT/scripts/ci/p7_recovery_offsite_transfer.sh" get "$LAB/download/$BUNDLE_NAME" "$BUNDLE_NAME"
REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE="$LAB/identity.txt" \
  uv run python scripts/operations/recovery_bundle.py verify "$LAB/download/$BUNDLE_NAME"

# Create clean restore targets only after source deletion and HTTPS download.
docker volume create "$PG_TARGET_VOL" >/dev/null
docker run -d --name "$PG_TARGET" --network "$TARGET_NET" -e POSTGRES_PASSWORD \
  -e POSTGRES_DB="$DATABASE" \
  --mount "type=volume,src=$PG_TARGET_VOL,dst=/var/lib/postgresql" "$PG_IMAGE" >/dev/null
wait_pg "$PG_TARGET"
docker exec "$PG_TARGET" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c \
  'CREATE DATABASE request_engine_role_bootstrap' >/dev/null
# Docker internal networks deliberately do not publish host ports. Bootstrap
# target cluster roles from a short-lived installer on that isolated network;
# never open an egress network just to make host migration convenient.
MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:$PASSWORD@$PG_TARGET:5432/request_engine_role_bootstrap" \
  docker run --rm --network "$TARGET_NET" -e MIGRATION_DATABASE_URL \
    "$MIGRATION_IMAGE" alembic upgrade head
docker exec "$PG_TARGET" dropdb -U postgres request_engine_role_bootstrap
docker volume create "$BAO_TARGET_VOL" >/dev/null
start_bao "$BAO_TARGET" "$BAO_TARGET_VOL" "$TARGET_NET" "$LAB/openbao.hcl"
init_bao "$BAO_TARGET" TARGET_KEY TARGET_ROOT_TOKEN

unset P7_PG_SOURCE_CONTAINER P7_OPENBAO_SOURCE_CONTAINER P7_OPENBAO_SOURCE_TOKEN
export P7_PG_TARGET_CONTAINER="$PG_TARGET" P7_OPENBAO_TARGET_CONTAINER="$BAO_TARGET"
export P7_OPENBAO_TARGET_TOKEN="$TARGET_ROOT_TOKEN"
export REQUEST_ENGINE_RESTORE_DATABASE_URL="postgresql://postgres:$PASSWORD@$PG_TARGET:5432/$DATABASE"
export REQUEST_ENGINE_BACKUP_AGE_IDENTITY_FILE="$LAB/identity.txt"
export REQUEST_ENGINE_OUTBOUND_FENCED=true
uv run python scripts/operations/recovery_bundle.py restore "$LAB/download/$BUNDLE_NAME" \
  --bao-command bao --confirm-destructive --evidence-output "$LAB/restore-evidence.json"

TARGET_HEAD="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -Atc 'SELECT version_num FROM alembic_version')"
EXPECTED_HEAD="$(uv run alembic heads | awk 'NF {print $1; exit}')"
[[ "$TARGET_HEAD" == "$EXPECTED_HEAD" ]] || die 'restored schema head differs from migrations'
RESTORED_MARKER="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -Atc 'SELECT marker FROM public.p7_offhost_restore_oracle')"
[[ "$RESTORED_MARKER" == offhost-data-restored ]] || die 'PostgreSQL restore oracle mismatch'
PRIVILEGES="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -AtF '|' -c \
  "SELECT pg_get_userbyid(c.relowner), c.relrowsecurity, c.relforcerowsecurity, has_table_privilege('request_engine_worker','p7_offhost_probe.payload','SELECT'), pg_get_userbyid(f.proowner), has_function_privilege('request_engine_worker','p7_offhost_probe.owner_identity()','EXECUTE') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace CROSS JOIN pg_proc f JOIN pg_namespace fn ON fn.oid=f.pronamespace WHERE n.nspname='p7_offhost_probe' AND c.relname='payload' AND fn.nspname='p7_offhost_probe' AND f.proname='owner_identity'")"
[[ "$PRIVILEGES" == 'request_engine_app|t|t|t|request_engine_app|t' ]] || die 'owner/ACL/RLS restore facts differ'
POLICY="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -Atc \
  "SELECT count(*) FROM pg_policies WHERE schemaname='p7_offhost_probe' AND tablename='payload' AND policyname='tenant_read'")"
[[ "$POLICY" == 1 ]] || die 'tenant RLS policy missing after restore'
VISIBLE="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -qAtc \
  "SET ROLE request_engine_worker; SET p7.tenant='tenant-a'; SELECT marker FROM p7_offhost_probe.payload")"
[[ "$VISIBLE" == offhost-data-restored ]] || die 'RLS tenant-a visibility mismatch'
HIDDEN="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -qAtc \
  "SET ROLE request_engine_worker; SET p7.tenant='tenant-a'; SELECT count(*) FROM p7_offhost_probe.payload WHERE tenant='tenant-b'")"
[[ "$HIDDEN" == 0 ]] || die 'RLS exposed another tenant row'
OWNER="$(docker exec "$PG_TARGET" psql -U postgres -d "$DATABASE" -qAtc \
  "SET ROLE request_engine_worker; SELECT p7_offhost_probe.owner_identity()")"
[[ "$OWNER" == request_engine_app ]] || die 'SECURITY DEFINER owner was not preserved'

docker restart "$BAO_TARGET" >/dev/null
wait_bao "$BAO_TARGET"
P7_LAB_UNSEAL_KEY="$SOURCE_KEY" docker exec -e P7_LAB_UNSEAL_KEY "$BAO_TARGET" \
  sh -c 'BAO_ADDR=http://127.0.0.1:8200 bao operator unseal "$P7_LAB_UNSEAL_KEY" >/dev/null'
SECRET_MARKER="$(BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN="$SOURCE_ROOT_TOKEN" docker exec \
  -e BAO_ADDR -e BAO_TOKEN "$BAO_TARGET" bao kv get -field=marker secret/request-engine/offhost)"
[[ "$SECRET_MARKER" == p7-offhost-secret-restored ]] || die 'OpenBao restored marker mismatch'

cp "$LAB/restore-evidence.json" "$LAB/evidence.json"
python - "$LAB/evidence.json" "$OUTPUT" "$TARGET_HEAD" "$BUNDLE_NAME" <<'PY'
import json
import sys
from pathlib import Path
restore = json.loads(Path(sys.argv[1]).read_text())
evidence = {
    "schema": "request-engine/offhost-recovery-lab/v1",
    "outcome": "accepted",
    "recovery_bundle_name": sys.argv[4],
    "restored_migration_head": sys.argv[3],
    "source_postgres_container_and_volume_destroyed_before_download": True,
    "source_openbao_container_and_volume_destroyed_before_download": True,
    "original_local_backup_deleted_before_download": True,
    "object_store_recreated_from_distinct_retained_volume": True,
    "fresh_client_downloaded_over_authenticated_https": True,
    "invalid_bearer_token_rejected": True,
    "untrusted_ca_rejected_before_download": True,
    "corrupted_bundle_rejected_by_recovery_cli": True,
    "clean_postgres_and_openbao_targets_restored": True,
    "owner_acl_force_rls_policy_and_tenant_visibility_verified": True,
    "openbao_secret_marker_verified_after_restore_restart": True,
    "restore_cli_evidence": restore,
    "storage_fixture": "authenticated HTTPS file service; not S3 or a cloud provider",
    "network_scope": "Docker lab networks only; outbound fence env is declarative, host isolation not certified",
    "secret_material_in_evidence": False,
}
Path(sys.argv[2]).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
PY
echo "off-host recovery lab evidence: $OUTPUT"
