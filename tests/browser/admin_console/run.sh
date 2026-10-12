#!/usr/bin/env bash
set -euo pipefail
browser_fixture_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$browser_fixture_directory/../../.."
export ADMIN_BROWSER_ARTIFACTS="${ADMIN_BROWSER_ARTIFACTS:-$PWD/.ci/admin-visual}"
export ADMIN_BROWSER_BASE_URL="http://127.0.0.1:${ADMIN_BROWSER_PORT:-18422}"
export ADMIN_BROWSER_SESSION_DIRECTORY
ADMIN_BROWSER_SESSION_DIRECTORY="$(mktemp -d)"
mkdir -p "$ADMIN_BROWSER_ARTIFACTS"
uv run uvicorn --app-dir "$browser_fixture_directory" server:app --host 127.0.0.1 --port "${ADMIN_BROWSER_PORT:-18422}" > "$ADMIN_BROWSER_ARTIFACTS/server.log" 2>&1 &
browser_fixture_pid=$!
cleanup() {
  kill "$browser_fixture_pid" 2>/dev/null || true
  wait "$browser_fixture_pid" 2>/dev/null || true
  rm -rf -- "$ADMIN_BROWSER_SESSION_DIRECTORY"
}
trap cleanup EXIT
browser_fixture_ready=false
for attempt in $(seq 1 50); do
  kill -0 "$browser_fixture_pid" 2>/dev/null || exit 1
  if curl -sf "$ADMIN_BROWSER_BASE_URL/health/live" > /dev/null; then
    browser_fixture_ready=true
    break
  fi
  sleep 0.1
done
if [[ "$browser_fixture_ready" != true ]]; then
  echo "Browser fixture did not become ready; inspect server.log." >&2
  exit 1
fi
node "$browser_fixture_directory/verify.cjs" | tee "$ADMIN_BROWSER_ARTIFACTS/verification.json"
# A competing process on this port must never count as this fixture.
kill -0 "$browser_fixture_pid" 2>/dev/null
