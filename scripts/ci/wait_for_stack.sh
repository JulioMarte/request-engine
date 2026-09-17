#!/usr/bin/env bash
set -euo pipefail
compose=(docker compose -f deploy/reference/compose.e2e.yaml)
deadline=$((SECONDS + ${STACK_READY_TIMEOUT_SECONDS:-180}))
while (( SECONDS < deadline )); do
  if curl -fsS http://127.0.0.1:58000/health/ready >/dev/null 2>&1 && curl -fsS http://127.0.0.1:58001/health/ready >/dev/null 2>&1; then
    echo 'reference stack is ready'; exit 0
  fi
  sleep 3
done
echo 'reference stack did not become ready before timeout' >&2
"${compose[@]}" ps >&2 || true
"${compose[@]}" logs --no-color --timestamps >&2 || true
exit 1
