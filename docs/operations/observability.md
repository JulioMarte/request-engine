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

For a deployable immutable image, enable the optional layer at image build time. The same
resulting image digest must be used for API, control-plane and worker surfaces; do not
install packages after deployment:

```bash
docker build \
  --build-arg REQUEST_ENGINE_ENABLE_OBSERVABILITY=1 \
  -f deploy/reference/Dockerfile \
  -t request-engine:<immutable-release-tag> .
docker run --rm request-engine:<immutable-release-tag> \
  python /app/scripts/observability/run_with_otel.py --check
```

The default build argument is `0` and leaves the optional dependency set out. The enabled
image includes the launcher and independent database collector under
`/app/scripts/observability/`. Use the same immutable image for worker processes and the
separate operator collector process.

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
traces and metrics to the configured OTLP/HTTP backend. It also exposes a Prometheus scrape
endpoint on port 9464 for private monitoring-network use; it has no application bearer-token
boundary.

The local Compose stack includes Prometheus (`127.0.0.1:9090`) and Alertmanager
(`127.0.0.1:9093`). Rules live in `deploy/observability/alert-rules.yaml`. The Alertmanager
receiver in `deploy/observability/alertmanager.yaml` intentionally uses an invalid
placeholder URL; replace it with an operator-owned HTTPS receiver before deployment.
Grouping, repeat delivery and resolved notifications are configured, but a webhook 2xx is
transport acceptance, not human acknowledgement.

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

The three central fenced worker pools emit the following metrics when the optional pinned
OpenTelemetry runtime is installed. Attributes are limited to worker kind and bounded
outcome; error text, work IDs and lease tokens are excluded:

Set `REQUEST_ENGINE_WORKER_INSTANCE_ID` to a stable unique value for each worker process.
The launcher adds it as `service.instance.id`, which the Collector exports as a resource
label so replica counters remain separate. Alerting detects a missing pool signal; detecting
one missing replica requires the operator to supply an expected instance inventory.

```text
request_engine.worker.claims
request_engine.worker.cycles
request_engine.worker.outcomes
request_engine.worker.lease_lost
request_engine.worker.processing.duration
```

Run the independent operational-state poller as a separate process, using the dedicated
deployment-created login inheriting only `request_operator_metrics`, and an operator-managed secret reference for
`REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL`:

```bash
python scripts/observability/operator_metrics_collector.py
```

Set `REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL` through the process secret store using
the `postgresql+asyncpg` SQLAlchemy URL driver, for example
`postgresql+asyncpg://<login>:<secret>@<private-db-host>/<database>`. Do not put credentials
in the command line. The collector rejects other URL drivers before opening a connection.
Connection attempts and pool acquisition are limited to three seconds; the complete login
check and each query have an eight-second async deadline, in addition to PostgreSQL's
statement and lock timeouts.

With the optional image, run the collector as its own deployment process. Configure
`REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL` in the platform secret store and mount the
accepted certification read-only at `/run/request-engine/recovery-certification.json`:

```bash
docker run --rm \
  --env REQUEST_ENGINE_OPERATOR_METRICS_DATABASE_URL \
  --env REQUEST_ENGINE_RECOVERY_CERTIFICATION_PATH=/run/request-engine/recovery-certification.json \
  --mount type=bind,src=/secure/evidence/recovery-certification.json,dst=/run/request-engine/recovery-certification.json,readonly \
  request-engine:<immutable-release-tag> \
  python /app/scripts/observability/operator_metrics_collector.py
```

The `--env` form passes the secret from the deployment environment without placing its
value in the process arguments. Keep this poller on a private network with the approved
metrics backend endpoint; it does not expose a public HTTP endpoint.

Migration 0039 creates `request_operator_metrics` as a `NOLOGIN` group, not a
credential. Provision a separate login through the deployment's secret workflow,
then grant only that group. For example, run this as a database administrator and
set the password through the secret manager rather than a checked-in SQL file:

```sql
CREATE ROLE request_operator_metrics_login LOGIN NOINHERIT NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT request_operator_metrics TO request_operator_metrics_login
    WITH INHERIT TRUE, SET FALSE;
```

Grant database CONNECT only if the database does not already grant it to `PUBLIC`.
Do not grant table reads or HTTP/HUMAN credentials. Set a unique
`REQUEST_ENGINE_WORKER_INSTANCE_ID` for every worker process to keep replica
counters separate. The stack detects a missing worker pool; a per-replica dead-man
alert requires the operator's explicit expected-instance inventory.

It calls only `request_admin.read_operator_metrics()` every 15 seconds, in a read-only
transaction with connection, statement and lock timeouts. That function returns capped
counts (up to 1,001 sampled rows), oldest age, and 10-minute provider/communication failure
counts; it exposes no tenant IDs, work IDs, payloads or error strings. Keep the login
credential only in this collector process. Query failures preserve the last values and
stop advancing the collector success timestamp, which has an independent stale alert.
Scheduled-action backlog/age counts only due pending actions and expired leases, using
`max(execute_at, next_attempt_at)` for pending due time and `lease_until` for leased work;
old rows intentionally scheduled for the future do not appear as overdue. Aggregate counts cap at 1,001, where 1,001 means
"at least 1,001" rather than an exact total.

Recovery evidence is read from a separately mounted, operator-controlled accepted
`request-engine/recovery-certification/v1` file created by
`scripts/operations/recovery_drill_evidence.py`. Mount the file read-only at a path readable
by the container's `request-engine` user (for example, owner `root:10001`, mode `0440`) and
set `REQUEST_ENGINE_RECOVERY_CERTIFICATION_PATH` to that path. The poller validates the
schema, accepted outcome, required proof inventory, bundle digest, protected file mode and
timestamp ordering. It exports only two verification bits and ages derived from
`backup_completed_at` and `service_recovered_at`; it never exports the digest, references,
source path or evidence payload. Missing, malformed, unaccepted or future-dated evidence
sets verification to zero and emits no age. This input is an operator-controlled
certification, not independent receiver acknowledgement.

Create the accepted file from a completed recovery drill using the existing certifier, then
install it into the read-only mount through the deployment's approved secret/evidence
workflow:

```bash
python scripts/operations/recovery_drill_evidence.py \
  /secure/evidence/recovery-drill.json \
  --output /secure/evidence/recovery-certification.json
```

The alert rules use sample thresholds of 30 days for backup evidence and 180 days for a
restore drill. Agree and approve the actual service objectives with operators before
deployment. A missing evidence-age gauge still fires as unknown, even when an older
verification bit is present.

The independent database poller also emits these operational metrics:

```text
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

P7 duration observations and alert thresholds reject non-finite, negative,
boolean and unrepresentable values before replacing a previous signal. Initial
zero-valued metrics do not prove that backup/drill evidence exists; readiness
must independently report verified evidence. Process-local API alerts do not
deliver notifications. See [operator alert acceptance](operator-alert-acceptance.md)
for missing-signal/export checks, reversible fault trials and actual receiver
evidence. Missing-signal rules intentionally remain firing until genuine observations are
exported. Backup/drill verification gauges must come from an independently governed
evidence source. This configuration is not evidence of an installed external receiver,
acknowledged receipt, or production monitoring uptime. The semantic metrics and their
monitoring route must be verified before claiming unattended operational alerting.

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
