#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OBS_DIR="$ROOT_DIR/deploy/observability"
PROJECT="operator-alert-smoke-${GITHUB_RUN_ID:-local}-$$"
TMP_DIR="$(mktemp -d)"
AM_NAME="${PROJECT}-receiver"
IMAGE_NAME="${PROJECT}-request-engine"
RECEIVER_PORT="${OPERATOR_ALERT_SMOKE_RECEIVER_PORT:-19188}"
SMOKE_ALERT="OperatorAlertSmoke_${GITHUB_RUN_ID:-local}_$$"
ARTIFACT_DIR="${OPERATOR_ALERT_SMOKE_ARTIFACT_DIR:-$ROOT_DIR/.ci/operator-alerts}"
mkdir -p "$ARTIFACT_DIR"
: > "$ARTIFACT_DIR/operator-alerts-smoke.txt"

cleanup() {
  local result=$?
  if (( result == 0 )); then
    printf 'result: passed\n' >> "$ARTIFACT_DIR/operator-alerts-smoke.txt"
  else
    printf 'result: failed (exit %s)\n' "$result" >> "$ARTIFACT_DIR/operator-alerts-smoke.txt"
  fi
  docker rm -f "$AM_NAME" >/dev/null 2>&1 || true
  docker image rm "$IMAGE_NAME" >/dev/null 2>&1 || true
  docker compose -p "$PROJECT" -f "$OBS_DIR/compose.otel.yaml" down --remove-orphans >/dev/null 2>&1 || true
  if [[ -n "${RECEIVER_PID:-}" ]]; then
    kill "$RECEIVER_PID" >/dev/null 2>&1 || true
    wait "$RECEIVER_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

PROM_IMAGE="quay.io/prometheus/prometheus:v3.8.1"
AM_IMAGE="quay.io/prometheus/alertmanager:v0.31.1"
docker build --quiet --build-arg REQUEST_ENGINE_ENABLE_OBSERVABILITY=1 \
  -f "$ROOT_DIR/deploy/reference/Dockerfile" -t "$IMAGE_NAME" "$ROOT_DIR"
printf 'Optional-observability reference image build passed.\n' \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm "$IMAGE_NAME" \
  python /app/scripts/observability/run_with_otel.py --service-name smoke --check \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm --env PYTHONPATH=/app/scripts/observability --entrypoint python "$IMAGE_NAME" -c \
  'import asyncpg, opentelemetry.sdk.metrics; from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter; from request_engine.platform.observability.worker_telemetry import OpenTelemetryWorkerMetrics; import operator_metrics_collector; print("optional collector and worker telemetry imports passed")' \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm -v "$OBS_DIR:/etc/prometheus:ro" --entrypoint /bin/promtool \
  "$PROM_IMAGE" check config /etc/prometheus/prometheus.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm -v "$OBS_DIR:/etc/prometheus:ro" --entrypoint /bin/promtool \
  "$PROM_IMAGE" check rules /etc/prometheus/alert-rules.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm -v "$OBS_DIR:/etc/prometheus:ro" --entrypoint /bin/promtool \
  "$PROM_IMAGE" test rules /etc/prometheus/tests/alert-rules.test.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"
docker run --rm -v "$OBS_DIR:/etc/alertmanager:ro" --entrypoint /bin/amtool \
  "$AM_IMAGE" check-config /etc/alertmanager/alertmanager.yaml \
  | tee -a "$ARTIFACT_DIR/operator-alerts-smoke.txt"

docker compose -p "$PROJECT" -f "$OBS_DIR/compose.otel.yaml" up -d
wait_http() {
  local url="$1" deadline=$((SECONDS + 90))
  while (( SECONDS < deadline )); do
    if curl --connect-timeout 2 --max-time 5 --fail --silent "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "service did not become ready: $url" >&2
  docker compose -p "$PROJECT" -f "$OBS_DIR/compose.otel.yaml" logs --no-color >&2 || true
  return 1
}
wait_http http://127.0.0.1:13133/
wait_http http://127.0.0.1:9090/-/ready
wait_http http://127.0.0.1:9093/-/ready

cd "$ROOT_DIR"
uv run --with-requirements deploy/observability/requirements.txt \
  python scripts/observability/operator_alerts_smoke_emit.py
deadline=$((SECONDS + 90))
required_metrics=(
  'request_engine_worker_cycles_total'
  'request_engine_worker_claims_total'
  'request_engine_worker_outcomes_total'
  'request_engine_worker_lease_lost_total'
  'request_engine_worker_processing_duration_seconds_bucket'
  'request_engine_scheduled_action_backlog'
)
while (( SECONDS < deadline )); do
  metrics="$(curl --connect-timeout 2 --max-time 5 --fail --silent \
    http://127.0.0.1:9464/metrics || true)"
  all_present=true
  for metric in "${required_metrics[@]}"; do
    if ! grep -q "^${metric}" <<<"$metrics"; then
      all_present=false
      break
    fi
  done
  if [[ "$all_present" == true ]] \
    && grep -q 'service_instance_id="smoke-unique"' <<<"$metrics"; then
    break
  fi
  sleep 1
done
for metric in "${required_metrics[@]}"; do
  if ! grep -q "^${metric}" <<<"${metrics:-}"; then
    echo "required OTLP metric missing from Collector scrape: $metric" >&2
    exit 1
  fi
done
if ! grep -q 'service_instance_id="smoke-unique"' <<<"${metrics:-}"; then
  echo "OTLP resource identity did not reach Collector Prometheus scrape" >&2
  exit 1
fi
grep -E '^request_engine_worker_(cycles|claims|outcomes|lease_lost)_total|^request_engine_worker_processing_duration_seconds_bucket|^request_engine_scheduled_action_backlog' \
  <<<"$metrics" | tee "$ARTIFACT_DIR/exported-metrics.txt" >/dev/null
deadline=$((SECONDS + 60))
while (( SECONDS < deadline )); do
  query="$(curl --connect-timeout 2 --max-time 5 --fail --silent --get \
    --data-urlencode 'query=request_engine_worker_cycles_total' \
    http://127.0.0.1:9090/api/v1/query || true)"
  if grep -q 'smoke-unique' <<<"$query"; then
    printf 'Prometheus scrape query returned worker metric series.\n' \
      >> "$ARTIFACT_DIR/operator-alerts-smoke.txt"
    break
  fi
  sleep 1
done
if ! grep -q 'smoke-unique' <<<"${query:-}"; then
  echo "Prometheus did not ingest the OTLP worker metric series" >&2
  exit 1
fi

# Route only to this local fixture. It cannot reach an operator-owned receiver.
python scripts/observability/operator_alerts_smoke_receiver.py \
  --port "$RECEIVER_PORT" --output "$TMP_DIR/received-statuses" >/dev/null 2>&1 &
RECEIVER_PID=$!
sed "s#https://replace-with-operator-receiver.invalid/alerts#http://127.0.0.1:${RECEIVER_PORT}/alerts#" \
  "$OBS_DIR/alertmanager.yaml" | sed -e 's/group_wait: 30s/group_wait: 1s/' \
    -e 's/group_interval: 5m/group_interval: 1s/' > "$TMP_DIR/alertmanager.yaml"
docker compose -p "$PROJECT" -f "$OBS_DIR/compose.otel.yaml" stop alertmanager
docker run --detach --name "$AM_NAME" --network host \
  -v "$TMP_DIR/alertmanager.yaml:/etc/alertmanager/alertmanager.yaml:ro" \
  "$AM_IMAGE" --config.file=/etc/alertmanager/alertmanager.yaml >/dev/null
wait_http http://127.0.0.1:9093/-/ready

started="$(date -u -d '5 seconds ago' +%Y-%m-%dT%H:%M:%SZ)"
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:9093/api/v2/alerts \
  --data "[{\"labels\":{\"alertname\":\"$SMOKE_ALERT\",\"severity\":\"warning\"},\"annotations\":{\"summary\":\"local transport fixture\"},\"startsAt\":\"$started\"}]" >/dev/null
deadline=$((SECONDS + 45))
while (( SECONDS < deadline )) && ! grep -Fxq "firing|${SMOKE_ALERT}" "$TMP_DIR/received-statuses" 2>/dev/null; do sleep 1; done
grep -Fxq "firing|${SMOKE_ALERT}" "$TMP_DIR/received-statuses"
ended="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
curl --connect-timeout 2 --max-time 5 --fail --silent --show-error -H 'Content-Type: application/json' \
  -X POST http://127.0.0.1:9093/api/v2/alerts \
  --data "[{\"labels\":{\"alertname\":\"$SMOKE_ALERT\",\"severity\":\"warning\"},\"annotations\":{\"summary\":\"local transport fixture\"},\"startsAt\":\"$started\",\"endsAt\":\"$ended\"}]" >/dev/null
deadline=$((SECONDS + 45))
while (( SECONDS < deadline )) && ! grep -Fxq "resolved|${SMOKE_ALERT}" "$TMP_DIR/received-statuses" 2>/dev/null; do sleep 1; done
grep -Fxq "resolved|${SMOKE_ALERT}" "$TMP_DIR/received-statuses"
cp "$TMP_DIR/received-statuses" "$ARTIFACT_DIR/receiver-statuses.txt"
cat >> "$ARTIFACT_DIR/operator-alerts-smoke.txt" <<'EOF'
Collector health, OTLP receiver export and Collector Prometheus scrape passed.
Alertmanager local fixture accepted both firing and resolved notifications.
The fixture proves local transport only; it is not production receiver acknowledgement.
EOF
echo "operator alert smoke passed: pinned config, rule fixtures, OTLP scrape,"
echo "and local firing/resolved webhook receipt"
