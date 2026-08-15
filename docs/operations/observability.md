# Request Engine observability

Status: production observability contract for V3.

## Architecture

Request Engine uses OpenTelemetry as the telemetry boundary.

```text
Request Engine API / workers
        |
        | OTLP/HTTP
        v
OpenTelemetry Collector
        |
        | OTLP/HTTP
        v
Observability backend
```

The application sends telemetry to a Collector instead of binding product code to a
specific vendor. The backend can therefore change without changing domain or module code.

Python traces and metrics are release-grade signals. Python OpenTelemetry logs remain a
development signal, so Request Engine keeps normal application logs and injects trace
correlation fields instead of making OTel log export a V3 production dependency.

## Pinned runtime

Install the zero-code runtime layer:

```bash
python -m pip install -r deploy/observability/requirements.txt
```

The deployment layer pins the OpenTelemetry SDK/exporter and the FastAPI, SQLAlchemy, and
logging instrumentations. These packages intentionally live outside the core Request
Engine dependency lock: observability is process/deployment composition and modules must
not import the OpenTelemetry SDK.

## Local Collector

Start the backend-neutral local Collector:

```bash
docker compose -f deploy/observability/compose.otel.yaml up -d
```

It accepts:

- OTLP/gRPC on `127.0.0.1:4317`;
- OTLP/HTTP on `127.0.0.1:4318`;
- Collector health on `127.0.0.1:13133`.

The local Collector uses the debug exporter. It is for local validation, not production
storage.

Validate health from the host:

```bash
curl --fail http://127.0.0.1:13133/
```

## Run Request Engine with telemetry

Use the cross-platform launcher for every API or worker process:

```bash
python scripts/observability/run_with_otel.py \
  --service-name request-engine-api \
  --service-version <immutable-release-version> \
  -- <request-engine-api-command>
```

For a worker:

```bash
python scripts/observability/run_with_otel.py \
  --service-name request-engine-worker \
  --service-version <immutable-release-version> \
  -- <request-engine-worker-command>
```

The wrapper uses zero-code instrumentation and defaults to OTLP/HTTP at
`http://127.0.0.1:4318`. Existing environment variables always win over wrapper defaults.
It maps `--service-version` to the standard `service.version` resource attribute.

The default signals are:

```text
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=none
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_PROPAGATORS=tracecontext,baggage
```

The logging instrumentation injects `trace_id`, `span_id`, and sampling state into normal
Python log records. It does not make OTel log export authoritative.

## Production Collector

Use `deploy/observability/otel-collector.production.yaml`.

Required secrets/configuration:

```text
REQUEST_ENGINE_OTEL_BACKEND_ENDPOINT=https://<backend-otlp-endpoint>
REQUEST_ENGINE_OTEL_BACKEND_AUTHORIZATION=<backend-authorization-value>
```

Keep the backend endpoint on TLS. Do not set `insecure: true` in the production Collector.

The production Collector receives OTLP, applies memory limiting and batching, then exports
traces and metrics to the configured OTLP/HTTP backend.

## Production process environment

Recommended baseline:

```text
OTEL_SERVICE_NAME=request-engine-api
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production,service.version=<immutable-release-version>
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=none
OTEL_PROPAGATORS=tracecontext,baggage
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=<approved-production-ratio>
OTEL_PYTHON_LOG_CORRELATION=true
```

Use a different `OTEL_SERVICE_NAME` for materially different process roles such as API,
scheduled workers, provider-event workers, and outbox workers.

Do not use a low production trace sampling ratio until error and high-value transaction
coverage has been validated. Sampling must never affect business behavior.

## Data policy

Never capture these values in telemetry:

- Authorization/Cookie headers;
- API keys, provider credentials, signing keys, or database credentials;
- request/response bodies by default;
- payment or clinical payloads;
- raw provider payloads;
- secrets embedded in URLs or query strings.

Do not enable broad HTTP header capture. If a future integration captures selected headers,
configure the OpenTelemetry sanitization list before enabling it.

High-cardinality business identifiers can be useful on traces when incident diagnosis
requires them, but they must not become metric dimensions. In particular, do not use
`organization_id`, `principal_id`, `request_id`, `reservation_id`, `scheduled_action_id`,
or provider event IDs as metric labels.

Keep metric dimensions bounded. Suitable dimensions include:

- service name/version;
- deployment environment;
- HTTP route and status class;
- worker kind;
- terminal worker outcome;
- bounded provider name;
- bounded action/event type.

## Required production signals

Automatic instrumentation provides the first layer:

- HTTP server spans and request metrics from FastAPI/ASGI;
- SQLAlchemy database spans;
- trace context propagation;
- correlated Python logs.

Request Engine still needs semantic application metrics for business-operational state.
Those metrics must be added at the process/application boundary, not in domain entities.

Required semantic metrics before the final production gate:

```text
request_engine.worker.claims
request_engine.worker.outcomes
request_engine.worker.lease_lost
request_engine.worker.processing.duration
request_engine.scheduled_action.backlog
request_engine.scheduled_action.oldest_age
request_engine.outbox.backlog
request_engine.provider_event.backlog
request_engine.provider_event.failures
request_engine.communication.failures
request_engine.communication.ambiguous
```

Backlog gauges should come from bounded database observations or a dedicated collector,
not from per-request queries.

## CI proof

`tests/architecture/test_observability_contract.py` prevents:

- unpinned observability runtime packages;
- removal of OTLP, batching, memory limiting, or Collector health;
- insecure production Collector transport;
- accidental OpenTelemetry imports inside business modules;
- accidental loss of log correlation and W3C propagation defaults;
- unpinned Collector images.

The `Observability runtime contract` CI job installs the pinned runtime, checks the
zero-code launcher, and runs an SDK/exporter smoke test without requiring an external
backend.

## Operational checks

Before deployment:

1. Validate Collector configuration.
2. Verify the Collector health endpoint.
3. Run the runtime smoke test.
4. Start one instrumented process.
5. Confirm one trace and metric arrive in the backend.
6. Confirm logs contain matching trace/span IDs.
7. Confirm secrets and request bodies are absent.
8. Confirm telemetry loss cannot fail an API request or worker transaction.

OpenTelemetry is an observability subsystem. PostgreSQL and Request Engine remain the
business authority.
