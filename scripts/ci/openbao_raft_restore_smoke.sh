#!/usr/bin/env bash
set -euo pipefail

IMAGE="${OPENBAO_IMAGE:-openbao/openbao:2.6.1}"
SOURCE_CONTAINER="p7-raft-source-${GITHUB_RUN_ID:-local}-$$"
TARGET_CONTAINER="p7-raft-target-${GITHUB_RUN_ID:-local}-$$"
SOURCE_VOLUME="${SOURCE_CONTAINER}-data"
TARGET_VOLUME="${TARGET_CONTAINER}-data"
HOST_PORT="${OPENBAO_RAFT_SMOKE_PORT:-18200}"
OUTPUT="${1:-.ci/openbao-raft-restore-smoke.json}"
TMPDIR_ROOT="$(mktemp -d)"
CONFIG="$TMPDIR_ROOT/openbao.hcl"
SNAPSHOT="$TMPDIR_ROOT/source.snap"

cleanup() {
  docker rm -f "$SOURCE_CONTAINER" "$TARGET_CONTAINER" >/dev/null 2>&1 || true
  docker volume rm -f "$SOURCE_VOLUME" "$TARGET_VOLUME" >/dev/null 2>&1 || true
  rm -rf "$TMPDIR_ROOT"
}
trap cleanup EXIT

cat >"$CONFIG" <<'EOF'
ui = false
disable_mlock = true

storage "raft" {
  path    = "/openbao/data"
  node_id = "p7-raft-restore-node"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

api_addr     = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"
EOF

wait_for_openbao() {
  local container="$1"
  for _ in $(seq 1 60); do
    if docker exec "$container" sh -c '
      export BAO_ADDR=http://127.0.0.1:8200
      bao status >/dev/null 2>&1
      code=$?
      [ "$code" -eq 0 ] || [ "$code" -eq 2 ]
    '; then
      return 0
    fi
    sleep 1
  done
  docker logs "$container"
  return 1
}

prepare_volume() {
  local volume="$1"
  docker run --rm \
    --user 0:0 \
    -v "$volume:/openbao/data" \
    "$IMAGE" \
    sh -ec 'mkdir -p /openbao/data && chown -R openbao:openbao /openbao/data && chmod 700 /openbao/data'
}

start_openbao() {
  local container="$1"
  local volume="$2"
  docker run -d \
    --name "$container" \
    --cap-add IPC_LOCK \
    -p "127.0.0.1:$HOST_PORT:8200" \
    -v "$volume:/openbao/data" \
    -v "$CONFIG:/openbao/config/openbao.hcl:ro" \
    "$IMAGE" \
    server -config=/openbao/config/openbao.hcl >/dev/null
  wait_for_openbao "$container"
}

docker volume create "$SOURCE_VOLUME" >/dev/null
docker volume create "$TARGET_VOLUME" >/dev/null
prepare_volume "$SOURCE_VOLUME"
prepare_volume "$TARGET_VOLUME"

start_openbao "$SOURCE_CONTAINER" "$SOURCE_VOLUME"
SOURCE_INIT="$(docker exec "$SOURCE_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao operator init -key-shares=1 -key-threshold=1 -format=json
')"
SOURCE_KEY="$(printf '%s' "$SOURCE_INIT" | jq -er '.unseal_keys_b64[0]')"
SOURCE_ROOT_TOKEN="$(printf '%s' "$SOURCE_INIT" | jq -er '.root_token')"

docker exec "$SOURCE_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao operator unseal "$1" >/dev/null
' sh "$SOURCE_KEY"
docker exec -e BAO_TOKEN="$SOURCE_ROOT_TOKEN" "$SOURCE_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao secrets enable -path=secret -version=2 kv >/dev/null
  bao kv put secret/request-engine/acceptance marker=p7-raft-restored >/dev/null
  bao operator raft snapshot save /tmp/source.snap
'
docker cp "$SOURCE_CONTAINER:/tmp/source.snap" "$SNAPSHOT"
test -s "$SNAPSHOT"

docker rm -f "$SOURCE_CONTAINER" >/dev/null
docker volume rm -f "$SOURCE_VOLUME" >/dev/null

start_openbao "$TARGET_CONTAINER" "$TARGET_VOLUME"
TARGET_INIT="$(docker exec "$TARGET_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao operator init -key-shares=1 -key-threshold=1 -format=json
')"
TARGET_KEY="$(printf '%s' "$TARGET_INIT" | jq -er '.unseal_keys_b64[0]')"
TARGET_ROOT_TOKEN="$(printf '%s' "$TARGET_INIT" | jq -er '.root_token')"

docker exec "$TARGET_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao operator unseal "$1" >/dev/null
' sh "$TARGET_KEY"
docker cp "$SNAPSHOT" "$TARGET_CONTAINER:/tmp/source.snap"
docker exec -e BAO_TOKEN="$TARGET_ROOT_TOKEN" "$TARGET_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao operator raft snapshot restore -force /tmp/source.snap
'

docker restart "$TARGET_CONTAINER" >/dev/null
wait_for_openbao "$TARGET_CONTAINER"
docker exec "$TARGET_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao operator unseal "$1" >/dev/null
' sh "$SOURCE_KEY"

RESTORED_MARKER="$(docker exec -e BAO_TOKEN="$SOURCE_ROOT_TOKEN" "$TARGET_CONTAINER" sh -c '
  export BAO_ADDR=http://127.0.0.1:8200
  bao kv get -field=marker secret/request-engine/acceptance
')"
test "$RESTORED_MARKER" = "p7-raft-restored"

mkdir -p "$(dirname "$OUTPUT")"
cat >"$OUTPUT" <<EOF
{
  "schema": "request-engine/openbao-raft-restore-smoke/v1",
  "outcome": "accepted",
  "image": "$IMAGE",
  "clean_target_volume": true,
  "fresh_target_initialized_with_distinct_seal_material": true,
  "forced_snapshot_restore_applied": true,
  "target_restarted_after_restore": true,
  "source_unseal_key_required_after_restore": true,
  "restored_kv_marker_verified": true,
  "secret_material_persisted_in_evidence": false
}
EOF
