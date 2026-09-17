#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f deploy/reference/compose.e2e.yaml)
expected="request-engine:${REQUEST_ENGINE_IMAGE_TAG:-e2e}"
expected_id="$(docker image inspect "$expected" --format '{{.Id}}')"

printf 'expected_image=%s\nexpected_id=%s\n' "$expected" "$expected_id"

for service in api control-plane; do
  cid="$(${compose[@]} ps -q "$service")"
  test -n "$cid"
  actual_id="$(docker inspect "$cid" --format '{{.Image}}')"
  printf '%s=%s\n' "$service" "$actual_id"
  if [[ "$actual_id" != "$expected_id" ]]; then
    echo "$service is not running the built Request Engine image" >&2
    exit 1
  fi
done

# These execution surfaces must also resolve to exactly the same image reference.
for service in migrate worker; do
  configured="$(${compose[@]} config | awk -v service="$service:" '
    $1 == service {in_service=1; next}
    in_service && $1 == "image:" {print $2; exit}
    in_service && /^[^[:space:]]/ {exit}
  ')"
  if [[ "$configured" != "$expected" ]]; then
    echo "$service resolves to '$configured', expected '$expected'" >&2
    exit 1
  fi
done

echo 'all Request Engine execution surfaces resolve to one immutable local image id'
