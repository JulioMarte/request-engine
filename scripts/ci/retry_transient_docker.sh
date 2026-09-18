#!/usr/bin/env bash
set -uo pipefail

log_file="${1:?log file is required}"
shift
(($# > 0)) || {
  echo "retry_transient_docker.sh requires a command" >&2
  exit 2
}

attempts="${E2E_DOCKER_RETRY_ATTEMPTS:-3}"
delay_seconds="${E2E_DOCKER_RETRY_DELAY_SECONDS:-3}"
[[ "$attempts" =~ ^[1-9][0-9]*$ ]] || {
  echo "E2E_DOCKER_RETRY_ATTEMPTS must be a positive integer" >&2
  exit 2
}
[[ "$delay_seconds" =~ ^[0-9]+$ ]] || {
  echo "E2E_DOCKER_RETRY_DELAY_SECONDS must be a non-negative integer" >&2
  exit 2
}

mkdir -p "$(dirname "$log_file")"
transient_pattern='(TLS handshake timeout|i/o timeout|context deadline exceeded|unexpected EOF|connection reset by peer|temporary failure|network is unreachable|failed to fetch anonymous token|toomanyrequests|too many requests|429 Too Many Requests|500 Internal Server Error|502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout|unexpected status[^0-9]*(429|500|502|503|504)|status code[^0-9]*(429|500|502|503|504)|server returned[^0-9]*(429|500|502|503|504))'

for ((attempt = 1; attempt <= attempts; attempt++)); do
  attempt_log="$(mktemp)"
  echo "docker-attempt=$attempt/$attempts" | tee -a "$log_file"

  set +e
  "$@" 2>&1 | tee -a "$log_file" "$attempt_log"
  rc=${PIPESTATUS[0]}
  set -e

  if ((rc == 0)); then
    rm -f "$attempt_log"
    exit 0
  fi

  if ! grep -Eqi "$transient_pattern" "$attempt_log"; then
    echo "docker-retry=disabled reason=non-transient exit_code=$rc" | tee -a "$log_file" >&2
    rm -f "$attempt_log"
    exit "$rc"
  fi

  if ((attempt == attempts)); then
    echo "docker-retry=exhausted attempts=$attempts exit_code=$rc" | tee -a "$log_file" >&2
    rm -f "$attempt_log"
    exit "$rc"
  fi

  echo "docker-retry=scheduled next_attempt=$((attempt + 1)) delay_seconds=$delay_seconds" \
    | tee -a "$log_file" >&2
  rm -f "$attempt_log"
  sleep "$delay_seconds"
done
