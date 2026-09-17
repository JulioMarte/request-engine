#!/usr/bin/env bash
set -euo pipefail

compose=(docker compose -f deploy/reference/compose.e2e.yaml)
expected="request-engine:${REQUEST_ENGINE_IMAGE_TAG:-e2e}"
expected_id="$(docker image inspect "$expected" --format '{{.Id}}')"

printf 'expected_image=%s\nexpected_id=%s\n' "$expected" "$expected_id"

for service in api control-plane; do
  cid="$(${compose[@]} ps -q "$service")"
  if [[ -z "$cid" ]]; then
    echo "$service is not running" >&2
    exit 1
  fi
  actual_id="$(docker inspect "$cid" --format '{{.Image}}')"
  printf '%s=%s\n' "$service" "$actual_id"
  if [[ "$actual_id" != "$expected_id" ]]; then
    echo "$service is not running the built Request Engine image" >&2
    exit 1
  fi
done

"${compose[@]}" --profile worker config --format json | python -c '
import json, sys
expected=sys.argv[1]
config=json.load(sys.stdin)
for service in ("migrate", "api", "control-plane", "worker"):
    configured=config["services"][service]["image"]
    print(f"configured.{service}={configured}")
    if configured != expected:
        raise SystemExit(f"{service} resolves to {configured!r}, expected {expected!r}")
' "$expected"

echo 'all Request Engine execution surfaces resolve to one immutable local image artifact'
