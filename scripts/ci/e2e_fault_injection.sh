#!/usr/bin/env bash
set -euo pipefail

fault="${1:?fault specification is required}"
compose_file="${E2E_COMPOSE_FILE:-deploy/reference/compose.e2e.yaml}"
profiles_raw="${E2E_COMPOSE_PROFILES:-}"
runtime_raw="${E2E_RUNTIME_SERVICES:-}"

IFS=':' read -r target action extra <<<"$fault"
[[ -n "$target" && -n "$action" && -z "${extra:-}" ]] || {
  echo "invalid E2E fault specification '$fault'; expected service:action" >&2
  exit 2
}

case " $runtime_raw " in
  *" $target "*) ;;
  *) echo "fault target '$target' is not an active runtime service" >&2; exit 2 ;;
esac

compose=(docker compose -f "$compose_file" --profile runner)
if [[ -n "$profiles_raw" ]]; then
  IFS=',' read -ra profiles <<<"$profiles_raw"
  for profile in "${profiles[@]}"; do
    [[ -n "$profile" ]] && compose+=(--profile "$profile")
  done
fi

case "$action" in
  kill-restart)
    echo "fault.begin target=$target action=$action"
    "${compose[@]}" kill "$target"
    stopped="$("${compose[@]}" ps -q "$target")"
    [[ -n "$stopped" ]] || {
      echo "fault target '$target' disappeared after kill" >&2
      exit 1
    }
    "${compose[@]}" up -d --no-build --wait \
      --wait-timeout "${FAULT_READY_TIMEOUT_SECONDS:-180}" "$target"
    echo "fault.end target=$target action=$action status=recovered"
    ;;
  *)
    echo "unsupported E2E fault action '$action'" >&2
    exit 2
    ;;
esac
