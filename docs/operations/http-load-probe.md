# Bounded HTTP load probe

`scripts/operations/http_load_probe.py` measures a declared HTTP operation with
real TCP requests. It uses only the existing `httpx` dependency. It does not
discover routes, invent SLOs, generate production certification, follow
redirects, or record response bodies, request bodies, or header values.

Every plan must declare an exact `target_origin` that appears in the exact
`allowed_target_origins` list, and an exact request path that appears in
`allowed_paths`. The method is limited to `GET` or `POST`. Concurrency is capped
at 128, the request count at 10,000, and the finite total per-request deadline
at 60 seconds. The deadline covers connect, headers, and the complete response
body, even when a peer sends data often enough to avoid a per-read idle timeout.
TLS certificate verification is enabled; `production_claimed` plans require an
HTTPS origin. That label describes the operator's target claim only: evidence
always records `production_certified: false`.

The plan must include explicit `max_p95_ms` and `max_error_rate` measurement
budgets. These are operator-supplied test limits, not values approved by the
repository. The probe exits nonzero if either measured value exceeds the
declared budget. Operators must not describe passing those limits as production
acceptance or an approved SLO without separate approval and deployment evidence.

## Example plan

This example measures a simple readiness GET against a local Uvicorn instance.
Replace the origin only with an operator-authorized test target and retain its
exact value in the allowlist. Pick limits from an approved test plan; the sample
values below are illustrative laboratory limits, not production SLOs.

```json
{
  "schema": "request-engine/http-load-plan/v1",
  "mode": "lab",
  "target_origin": "http://127.0.0.1:8000",
  "allowed_target_origins": ["http://127.0.0.1:8000"],
  "allowed_paths": ["/health/ready"],
  "request": {
    "method": "GET",
    "path": "/health/ready",
    "headers_env": {}
  },
  "total_requests": 500,
  "concurrency": 16,
  "timeout_seconds": 5,
  "max_p95_ms": 250,
  "max_error_rate": 0.01
}
```

Run from the repository root:

```bash
uv run python scripts/operations/http_load_probe.py /tmp/request-engine-load-plan.json \
  --output /tmp/request-engine-load-evidence.json
```

For a controlled operation-options POST, declare `method: "POST"`, an exact
options path in `allowed_paths`, and a JSON `json_body` appropriate for that
operation. The body and response are never written into evidence or printed.
Optional headers may reference environment variable names through `headers_env`,
for example `{ "Authorization": "REQUEST_ENGINE_LOAD_AUTHORIZATION" }`. Only
the reference names are in the plan; the probe never records or prints their
values. Avoid placing secrets or personal data in a plan body.

Each request's latency runs from connection/request start through the complete
response body. Receiving headers alone never counts as success. The probe sends
`Accept-Encoding: identity` and drains raw response bytes in 64 KiB chunks
without retaining them. It rejects any response with a non-identity
`Content-Encoding`, so decompression cannot inflate memory before the byte cap.
It enforces a fixed 1 MiB per-response cap. A response that exceeds the cap is a
`response_too_large` error; a truncated body or timeout while reading the body
is a `transport_error`. Either contributes to the measured error rate. The
evidence reports aggregate `response_bytes_total` and the per-response cap.

Evidence includes the request count, terminal status/error counts, p50/p95/p99
latency, error rate, elapsed time, aggregate bytes read, and declared budgets.
It excludes response content and header values. Network exceptions are counted
as `transport_error` without recording exception text, which could contain URLs
or provider details. Successful latency therefore includes full body transfer;
failed body reads still contribute their observed time and count as errors.

## Interpretation and limits

Use a dedicated isolated target. A probe can add load and change observed
behavior; never point it at an unapproved external or production system. This
tool is a single-process HTTP measurement, not a capacity certification: it
does not model multiple machines, realistic user arrival distributions,
database growth, ingress/TLS termination, or background workers. A successful run says only that this one run stayed within the budgets
written in its plan. It does not approve those budgets, certify production, or
replace end-to-end SMTP, backup/restore, alert delivery, network isolation, or
operator acceptance evidence.

## Sustained trials

Add `duration_seconds` (finite, 1 through 3600) to keep a fixed number of
workers issuing requests until the deadline. `total_requests` remains a hard
10,000-request safety cap. Exhausting that cap before the deadline fails the
trial, even when latency and errors pass; increase the cap within its bound or
reduce the duration/concurrency in the approved plan. This is closed-loop load:
a slow server reduces achieved throughput. It does not promise a fixed arrival
rate. Evidence includes actual requests, peak active requests, throughput,
last request start, and `duration_completed`; draining slow responses alone
does not satisfy a cap-exhausted duration.

For productive capacity acceptance, run the plan on the installed candidate
with background workers and intended replicas, retain host CPU/RSS, database
pool/wait observations, and concurrent readiness evidence from an independent
client. Compare the measured throughput to the approved workload. The probe
still emits `production_certified: false`; loopback success cannot establish
deployment capacity.

Request JSON is limited to 1 MiB after compact UTF-8 serialization. Plan input
is capped at 2 MiB before parsing. At most 64 environment-referenced headers
may contribute at most 16 KiB in aggregate; invalid control characters are
rejected before connecting. These bounds apply in count and sustained modes.
