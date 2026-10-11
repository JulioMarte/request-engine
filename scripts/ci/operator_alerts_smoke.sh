#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OBS_DIR="$ROOT_DIR/deploy/observability"
PROJECT="operator-alert-smoke-${GITHUB_RUN_ID:-local}-$$"
TMP_DIR="$(mktemp -d)"
IMAGE_NAME="${PROJECT}-request-engine"
RECEIVER_PORT="${OPERATOR_ALERT_SMOKE_RECEIVER_PORT:-19188}"
ARTIFACT_DIR="${OPERATOR_ALERT_SMOKE_ARTIFACT_DIR:-$ROOT_DIR/.ci/operator-alerts}"
mkdir -p "$ARTIFACT_DIR"
: > "$ARTIFACT_DIR/operator-alerts-smoke.txt"
COMPOSE_ARGS=()

cleanup() {
  local result=$?
  if (( result == 0 )); then
    printf 'result: passed\n' >> "$ARTIFACT_DIR/operator-alerts-smoke.txt"
  else
    printf 'result: failed (exit %s)\n' "$result" >> "$ARTIFACT_DIR/operator-alerts-smoke.txt"
  fi
  # Collect only explicit fixture observations/configs, never environment or
  # SQL connection material. Preserve diagnostics even on a causal-check failure.
  for observation in receiver-statuses.txt watchdog-monitor.txt alertmanager.yaml prometheus.yaml; do
    if [[ -f "$TMP_DIR/$observation" ]]; then
      cp "$TMP_DIR/$observation" "$ARTIFACT_DIR/$observation" 2>/dev/null || true
    fi
  done
  if [[ -f "${WORKER_CONTROL_DIR:-}/worker-results.txt" ]]; then
    cp "$WORKER_CONTROL_DIR/worker-results.txt" "$ARTIFACT_DIR/worker-outcomes.txt" 2>/dev/null || true
  fi
  if (( result != 0 && ${#COMPOSE_ARGS[@]} > 0 )); then
    # These two services contain only lab HTTP targets and alert labels;
    # worker/database logs are intentionally excluded from this projection.
    "${COMPOSE_ARGS[@]}" logs --no-color --timestamps prometheus alertmanager \
      > "$ARTIFACT_DIR/monitoring-services.log" 2>&1 || true
  fi
  for container in "${RECEIVER_CONTAINER:-}" "${WORKER_CONTAINER:-}" "${DB_COLLECTOR_CONTAINER:-}"; do
    if [[ -n "$container" ]]; then docker rm -f "$container" >/dev/null 2>&1 || true; fi
  done
  if [[ -n "${PROBE_PID:-}" ]]; then
    kill "$PROBE_PID" >/dev/null 2>&1 || true
    wait "$PROBE_PID" >/dev/null 2>&1 || true
  fi
  docker image rm "$IMAGE_NAME" >/dev/null 2>&1 || true
  if (( ${#COMPOSE_ARGS[@]} > 0 )); then
    "${COMPOSE_ARGS[@]}" down --remove-orphans >/dev/null 2>&1 || true
  else
    docker compose -p "$PROJECT" -f "$OBS_DIR/compose.otel.yaml" \
      -f "$OBS_DIR/compose.operator-smoke.yaml" down --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ -n "${RECEIVER_PID:-}" ]]; then
    kill "$RECEIVER_PID" >/dev/null 2>&1 || true
    wait "$RECEIVER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PG_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
PG_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
METRICS_SUFFIX="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
METRICS_ROLE="request_metrics_${METRICS_SUFFIX}"
METRICS_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
WORKER_SUFFIX="$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
WORKER_ROLE="request_worker_${WORKER_SUFFIX}"
WORKER_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
export OPERATOR_ALERT_SMOKE_PG_PASSWORD="$PG_PASSWORD"
export OPERATOR_ALERT_SMOKE_PG_PORT="$PG_PORT"
export OPERATOR_ALERT_SMOKE_METRICS_ROLE="$METRICS_ROLE"
export OPERATOR_ALERT_SMOKE_METRICS_PASSWORD="$METRICS_PASSWORD"
export OPERATOR_ALERT_SMOKE_WORKER_ROLE="$WORKER_ROLE"
export OPERATOR_ALERT_SMOKE_WORKER_PASSWORD="$WORKER_PASSWORD"

PROM_IMAGE="quay.io/prometheus/prometheus:v3.8.1"
AM_IMAGE="quay.io/prometheus/alertmanager:v0.31.1"
PYTHON_IMAGE="public.ecr.aws/docker/library/python:3.13-slim"
RECEIVER_CONTAINER="${PROJECT}-receiver"
WORKER_CONTAINER="${PROJECT}-worker"
DB_COLLECTOR_CONTAINER="${PROJECT}-operator-metrics"
PG_ADMIN_URL="postgresql://postgres:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/request_engine_operator_smoke"
MIGRATION_DATABASE_URL="postgresql+psycopg://postgres:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/request_engine_operator_smoke"
WORKER_DATABASE_URL="postgresql+asyncpg://${WORKER_ROLE}:${WORKER_PASSWORD}@postgres:5432/request_engine_operator_smoke"
METRICS_DATABASE_URL="postgresql+asyncpg://${METRICS_ROLE}:${METRICS_PASSWORD}@postgres:5432/request_engine_operator_smoke"
export OPERATOR_ALERT_SMOKE_ADMIN_URL="$PG_ADMIN_URL"
export OPERATOR_ALERT_SMOKE_WORKER_ROLE="$WORKER_ROLE"
export OPERATOR_ALERT_SMOKE_WORKER_DATABASE_URL="$WORKER_DATABASE_URL"
WORKER_CONTROL_DIR="$TMP_DIR/worker-control"
mkdir -m 0777 "$WORKER_CONTROL_DIR"
printf 'accept\n' > "$TMP_DIR/receiver-mode.txt"
export OPERATOR_ALERT_SMOKE_CONTROL_DIR=/run/operator-alert-smoke
export REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL="$METRICS_DATABASE_URL"
export OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318

cp "$OBS_DIR/prometheus.yaml" "$TMP_DIR/prometheus.yaml"
cp "$OBS_DIR/alert-rules.yaml" "$TMP_DIR/alert-rules.yaml"
cp -R "$OBS_DIR/tests" "$TMP_DIR/tests"
sed "s#https://replace-with-operator-receiver.invalid/alerts#http://operator-alert-receiver:19188/alerts#" \
  "$OBS_DIR/alertmanager.yaml" | sed -e 's/group_wait: 30s/group_wait: 1s/' \
    -e 's/group_interval: 5m/group_interval: 1s/' \
    -e '/^  repeat_interval: 2h$/a\
  routes:\
    - matchers: [\x27alertname="Watchdog"\x27]\
      receiver: operator-webhook\
      repeat_interval: 5s' > "$TMP_DIR/alertmanager.yaml"
cat > "$TMP_DIR/compose.override.yaml" <<EOF
services:
  prometheus:
    command:
      - "--config.file=/etc/prometheus/prometheus.yaml"
      - "--storage.tsdb.path=/prometheus"
      - "--storage.tsdb.retention.time=7d"
      - "--web.enable-lifecycle"
      # A restart loses Alertmanager's in-memory alert set. Prometheus normally
      # resends only after >1m, evaluated on the 30s rule-group boundary (up to
      # 90s). Shorten only lab resend cadence; retain the real fresh-receipt proof.
      - "--rules.alert.resend-delay=5s"
    volumes:
      - "$TMP_DIR/prometheus.yaml:/etc/prometheus/prometheus.yaml:ro"
      - "$TMP_DIR/alert-rules.yaml:/etc/prometheus/alert-rules.yaml:ro"
  alertmanager:
    volumes:
      - "$TMP_DIR/alertmanager.yaml:/etc/alertmanager/alertmanager.yaml:ro"
EOF
COMPOSE_ARGS=(docker compose -p "$PROJECT" -f "$OBS_DIR/compose.otel.yaml" \
  -f "$OBS_DIR/compose.operator-smoke.yaml" -f "$TMP_DIR/compose.override.yaml")

# Build once, then use the same optional image for worker, database collector and smoke tools.
docker build --quiet --build-arg REQUEST_ENGINE_ENABLE_OBSERVABILITY=1 \
  -f "$ROOT_DIR/deploy/reference/Dockerfile" -t "$IMAGE_NAME" "$ROOT_DIR"
printf 'Optional observability image build passed.\n' \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm "$IMAGE_NAME" \
  python /app/scripts/observability/run_with_otel.py --service-name smoke --check \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm --env PYTHONPATH=/app/scripts/observability --entrypoint python "$IMAGE_NAME" -c \
  'import asyncpg, opentelemetry.sdk.metrics; from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter; from request_engine.platform.observability.worker_telemetry import OpenTelemetryWorkerMetrics; import operator_metrics_collector; print("optional collector and worker telemetry imports passed")' \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"

"${COMPOSE_ARGS[@]}" up -d postgres
postgres_deadline=$((SECONDS + 90))
while (( SECONDS < postgres_deadline )); do
  if "${COMPOSE_ARGS[@]}" exec -T postgres pg_isready \
    -h 127.0.0.1 -U postgres -d request_engine_operator_smoke >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"${COMPOSE_ARGS[@]}" exec -T postgres pg_isready -h 127.0.0.1 \
  -U postgres -d request_engine_operator_smoke
MIGRATION_DATABASE_URL="$MIGRATION_DATABASE_URL" uv run alembic upgrade head \
  > "$TMP_DIR/migration.log" 2>&1 || {
    cat "$TMP_DIR/migration.log" >&2
    exit 1
  }
uv run python scripts/observability/operator_alerts_smoke_setup.py provision
uv run python scripts/observability/operator_alerts_smoke_setup.py create-event \
  --state-file "$WORKER_CONTROL_DIR/worker-state.json"

# Prometheus and Alertmanager rule/config fixtures are validated at their pinned versions.
docker run --rm --user "$(id -u):$(id -g)" -v "$TMP_DIR:/etc/prometheus:ro" --entrypoint /bin/promtool \
  "$PROM_IMAGE" check config /etc/prometheus/prometheus.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm --user "$(id -u):$(id -g)" -v "$TMP_DIR:/etc/prometheus:ro" --entrypoint /bin/promtool \
  "$PROM_IMAGE" check rules \
  /etc/prometheus/alert-rules.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm --user "$(id -u):$(id -g)" -v "$TMP_DIR:/etc/prometheus:ro" \
  --entrypoint /bin/promtool \
  "$PROM_IMAGE" test rules /etc/prometheus/tests/alert-rules.test.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm --user "$(id -u):$(id -g)" -v "$TMP_DIR:/etc/alertmanager:ro" --entrypoint /bin/amtool \
  "$AM_IMAGE" check-config /etc/alertmanager/alertmanager.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"

"${COMPOSE_ARGS[@]}" up -d otel-collector prometheus alertmanager
wait_http() {
  local url="$1" deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if curl --connect-timeout 2 --max-time 5 --fail --silent "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "service did not become ready: $url" >&2
  "${COMPOSE_ARGS[@]}" logs --no-color >&2 || true
  return 1
}
wait_http http://127.0.0.1:13133/
wait_http http://127.0.0.1:9090/-/ready
wait_http http://127.0.0.1:9093/-/ready

docker run --detach --name "$RECEIVER_CONTAINER" --network "${PROJECT}_default" \
  --network-alias operator-alert-receiver --publish "127.0.0.1:${RECEIVER_PORT}:19188" \
  --mount "type=bind,src=$ROOT_DIR/scripts/observability/operator_alerts_smoke_receiver.py,dst=/fixture/receiver.py,readonly" \
  --mount "type=bind,src=$TMP_DIR,dst=/state" "$PYTHON_IMAGE" \
  python /fixture/receiver.py --bind 0.0.0.0 --port 19188 \
  --output /state/receiver-statuses.txt --mode-file /state/receiver-mode.txt >/dev/null
wait_http "http://127.0.0.1:${RECEIVER_PORT}/healthz"

docker run --detach --name "$DB_COLLECTOR_CONTAINER" --network "${PROJECT}_default" \
  --env REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL \
  --env "OTEL_RESOURCE_ATTRIBUTES=service.instance.id=${DB_COLLECTOR_CONTAINER}" \
  --env OTEL_EXPORTER_OTLP_ENDPOINT "$IMAGE_NAME" \
  python /app/scripts/observability/operator_metrics_collector.py >/dev/null

# Every waiter has a finite deadline and every HTTP call has a finite timeout.
wait_receiver_status() {
  local wanted="$1" alert="$2" seconds="$3"
  local deadline=$((SECONDS + seconds))
  while (( SECONDS < deadline )); do
    if grep -Fq "${wanted}|${alert}" "$TMP_DIR/receiver-statuses.txt" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "receiver did not record ${wanted} for ${alert}" >&2
  return 1
}
wait_prom_alert() {
  local alert="$1" seconds="$2" response
  local deadline=$((SECONDS + seconds))
  while (( SECONDS < deadline )); do
    response="$(curl --connect-timeout 2 --max-time 5 --fail --silent --get \
      --data-urlencode "query=ALERTS{alertname=\"${alert}\",alertstate=\"firing\"}" \
      http://127.0.0.1:9090/api/v1/query || true)"
    if python3 -c 'import json,sys; p=json.load(sys.stdin); sys.exit(0 if p.get("status") == "success" and bool(p.get("data", {}).get("result")) else 1)' \
      <<<"$response" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Prometheus did not fire alert ${alert}" >&2
  return 1
}
wait_prom_metric_positive() {
  local metric="$1" seconds="$2" response
  local deadline=$((SECONDS + seconds))
  while (( SECONDS < deadline )); do
    response="$(curl --connect-timeout 2 --max-time 5 --fail --silent --get \
      --data-urlencode "query=${metric}>0" \
      http://127.0.0.1:9090/api/v1/query || true)"
    if python3 -c 'import json,sys; p=json.load(sys.stdin); sys.exit(0 if p.get("status") == "success" and bool(p.get("data", {}).get("result")) else 1)' \
      <<<"$response" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  echo "Prometheus did not observe positive ${metric}" >&2
  return 1
}

# Require a real successful database read through OTLP and the scrape before
# inducing failures. Container startup alone is not collector readiness.
wait_prom_metric_positive request_engine_operator_metrics_collector_last_success_timestamp 90
printf 'Collector database read reached Prometheus.\n' | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"

probe_file="$TMP_DIR/watchdog-monitor.txt"
python3 "$ROOT_DIR/scripts/observability/operator_alerts_watchdog_monitor.py" \
  --prometheus-url http://127.0.0.1:9090 \
  --receiver-url "http://127.0.0.1:${RECEIVER_PORT}" \
  --heartbeat-max-age-seconds 15 --output "$probe_file" --poll-seconds 2 &
PROBE_PID=$!
wait_receiver_status firing Watchdog 90
wait_for_watchdog_state() {
  local state="$1" seconds="$2" current
  local deadline=$((SECONDS + seconds))
  while (( SECONDS < deadline )); do
    current="$(python3 "$ROOT_DIR/scripts/observability/operator_alerts_watchdog_monitor.py" \
      --read-latest --output "$probe_file")"
    if [[ "$current" == "$state" ]]; then
      return 0
    fi
    sleep 1
  done
  echo "independent Watchdog monitor did not record state ${state}" >&2
  return 1
}
wait_for_watchdog_state present 30

# A firing rule alone cannot prove that notifications reach the receiver.
# The host probe also requires a recent Watchdog accepted by that receiver.
"${COMPOSE_ARGS[@]}" stop alertmanager >/dev/null
wait_for_watchdog_state heartbeat_stale 60
"${COMPOSE_ARGS[@]}" start alertmanager >/dev/null
wait_http http://127.0.0.1:9093/-/ready
wait_for_watchdog_state present 60

# Run the real provider-event store, router, fenced runtime and OTLP observer in the optional image.
# Reject notifications before inducing the failure: the first delivery-failure
# notification must exercise retry even when metric observation is slow.
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error \
  -X PUT "http://127.0.0.1:${RECEIVER_PORT}/control/fail" >/dev/null
docker run --detach --name "$WORKER_CONTAINER" --network "${PROJECT}_default" \
  --env OPERATOR_ALERT_SMOKE_WORKER_DATABASE_URL \
  --env OPERATOR_ALERT_SMOKE_WORKER_ROLE \
  --env OPERATOR_ALERT_SMOKE_CONTROL_DIR \
  --env OTEL_EXPORTER_OTLP_ENDPOINT \
  --mount "type=bind,src=$ROOT_DIR/scripts/observability/operator_alerts_smoke_worker.py,dst=/fixture/worker.py,readonly" \
  --mount "type=bind,src=$WORKER_CONTROL_DIR,dst=/run/operator-alert-smoke" "$IMAGE_NAME" \
  python /fixture/worker.py >/dev/null
worker_deadline=$((SECONDS + 90))
while (( SECONDS < worker_deadline )) && [[ ! -f "$WORKER_CONTROL_DIR/worker-ready" ]]; do sleep 1; done
test -f "$WORKER_CONTROL_DIR/worker-ready"
wait_prom_metric_positive request_engine_provider_event_failures_10m 90
wait_prom_alert RequestEngineDeliveryFailures 90
wait_receiver_status rejected RequestEngineDeliveryFailures 30
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error \
  -X PUT "http://127.0.0.1:${RECEIVER_PORT}/control/accept" >/dev/null
wait_receiver_status firing RequestEngineDeliveryFailures 60
uv run python scripts/observability/operator_alerts_smoke_setup.py replay-event \
  --state-file "$WORKER_CONTROL_DIR/worker-state.json"
printf 'recover\n' > "$WORKER_CONTROL_DIR/recover-worker"
wait_receiver_status resolved RequestEngineDeliveryFailures 90
grep -Fq 'failure|dead' "$WORKER_CONTROL_DIR/worker-results.txt"
grep -Fq 'recovery|completed' "$WORKER_CONTROL_DIR/worker-results.txt"
printf 'Worker failure, receiver retry and audited recovery notifications passed.\n' \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"

# Stopping the independent SQL collector makes its success timestamp stale; restart clears it.
docker stop --time 1 "$DB_COLLECTOR_CONTAINER" >/dev/null
wait_prom_alert RequestEngineOperatorMetricsCollectorStale 180
wait_receiver_status firing RequestEngineOperatorMetricsCollectorStale 60
collector_restart_timestamp="$(date +%s)"
docker start "$DB_COLLECTOR_CONTAINER" >/dev/null
wait_prom_metric_positive "request_engine_operator_metrics_collector_last_success_timestamp-${collector_restart_timestamp}" 90
wait_receiver_status resolved RequestEngineOperatorMetricsCollectorStale 90
printf 'SQL collector outage and fresh read after restart reached the receiver.\n' \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"

# The independent host probe detects a missing dead-man rule and a stopped Prometheus process.
awk '
  /^      - alert: Watchdog$/ { skip = 1; next }
  skip && /^      - alert:/ { skip = 0 }
  !skip { print }
' "$OBS_DIR/alert-rules.yaml" > "$TMP_DIR/alert-rules.yaml"
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error \
  -X POST http://127.0.0.1:9090/-/reload >/dev/null
wait_for_watchdog_state missing 30
cp "$OBS_DIR/alert-rules.yaml" "$TMP_DIR/alert-rules.yaml"
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error \
  -X POST http://127.0.0.1:9090/-/reload >/dev/null
wait_for_watchdog_state present 60

"${COMPOSE_ARGS[@]}" stop prometheus >/dev/null
wait_for_watchdog_state unreachable 30
"${COMPOSE_ARGS[@]}" start prometheus >/dev/null
wait_http http://127.0.0.1:9090/-/ready
wait_for_watchdog_state present 90

# A real Collector outage traverses the same scrape rule and receiver retry path.
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error \
  -X PUT "http://127.0.0.1:${RECEIVER_PORT}/control/fail" >/dev/null
"${COMPOSE_ARGS[@]}" stop otel-collector >/dev/null
wait_prom_alert RequestEngineCollectorMissing 210
wait_receiver_status rejected RequestEngineCollectorMissing 30
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error \
  -X PUT "http://127.0.0.1:${RECEIVER_PORT}/control/accept" >/dev/null
wait_receiver_status firing RequestEngineCollectorMissing 60
"${COMPOSE_ARGS[@]}" start otel-collector >/dev/null
wait_http http://127.0.0.1:13133/
wait_receiver_status resolved RequestEngineCollectorMissing 90

cp "$TMP_DIR/receiver-statuses.txt" "$ARTIFACT_DIR/receiver-statuses.txt"
cp "$WORKER_CONTROL_DIR/worker-results.txt" "$ARTIFACT_DIR/worker-outcomes.txt"
cp "$TMP_DIR/watchdog-monitor.txt" "$ARTIFACT_DIR/watchdog-monitor.txt"
cat >> "$ARTIFACT_DIR/operator-alerts-smoke.txt" <<'EOF'
Actual PostgreSQL provider-event failure flowed through the fenced worker and SQL collector,
Prometheus RequestEngineDeliveryFailures rule, Alertmanager, and an independent local receiver.
The event was replayed through the existing administrative function and processed; Alertmanager
sent the resolved notification. A stopped SQL collector fired its stale rule and recovered.
An independent host-side Watchdog probe recorded Prometheus unavailability and restoration.
Stopping Alertmanager made the receiver Watchdog heartbeat stale even while Prometheus stayed
healthy; restarting Alertmanager restored a recent accepted receiver heartbeat.
A temporary removal of the Watchdog rule was independently reported as missing and its restoration as present.
A stopped OpenTelemetry Collector fired RequestEngineCollectorMissing; the receiver returned
503 and Alertmanager retried until the fixture accepted firing and resolved notifications.
All acknowledgements were local test-receiver HTTP responses; no production receiver was used.
EOF
printf 'operator alert integration smoke passed: real worker/database, rule firing/recovery, '
printf 'receiver retry, collector outage, and independent Watchdog monitoring\n'
