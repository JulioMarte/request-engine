#!/usr/bin/env bash
set -euo pipefail

operation="${1:?usage: p7_recovery_offsite_transfer.sh put|get FILE KEY}"
file="${2:?file path is required}"
key="${3:?object key is required}"
: "${P7_PYTHON_IMAGE:?P7_PYTHON_IMAGE is required}"
: "${P7_OBJECT_STORE_NETWORK:?P7_OBJECT_STORE_NETWORK is required}"
: "${P7_OBJECT_STORE_CA:?P7_OBJECT_STORE_CA is required}"
: "${P7_OBJECT_STORE_TOKEN:?P7_OBJECT_STORE_TOKEN is required}"
: "${P7_OBJECT_STORE_URL:?P7_OBJECT_STORE_URL is required}"
: "${P7_LAB_REPOSITORY_ROOT:?P7_LAB_REPOSITORY_ROOT is required}"

directory="$(dirname "$file")"
name="$(basename "$file")"
args=("$operation" --url "$P7_OBJECT_STORE_URL" --ca /ca.crt --key "$key")
args+=(--file "/artifact/$name")
artifact_mount="type=bind,src=$directory,dst=/artifact"
if [[ "$operation" == "put" ]]; then
  artifact_mount+=",readonly"
fi

docker run --rm --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  --network "$P7_OBJECT_STORE_NETWORK" \
  --mount "type=bind,src=$P7_LAB_REPOSITORY_ROOT/scripts/ci/offhost_object_client.py,dst=/client.py,readonly" \
  --mount "type=bind,src=$P7_OBJECT_STORE_CA,dst=/ca.crt,readonly" \
  --mount "$artifact_mount" \
  -e P7_OBJECT_STORE_TOKEN \
  "$P7_PYTHON_IMAGE" python /client.py "${args[@]}"
