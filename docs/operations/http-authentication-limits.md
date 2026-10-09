# HTTP authentication admission limits

Request Engine applies a per-process rolling-window limit to `POST` requests
whose paths are `/auth/native` or below it, and to paths below `/v1/setup/`.
The default is 120 attempts in the preceding 60 seconds. Configure it with
`REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE`, an exact decimal integer
from 1 through 10,000. Invalid configuration fails process startup rather than
disabling the limit.

Each Request Engine process keeps a monotonic timestamp deque capped at the
configured limit. Every matching admission attempt is recorded, including
attempts rejected by the limit, so repeated over-limit attempts continue to
occupy the bounded window. The check and append contain no `await` and are safe
within the process's single event loop. A rejected attempt returns HTTP 429
with the standard error envelope (`request_rate_exceeded`) and a `Retry-After`
value rounded up from the remaining window for the oldest retained attempt.
Admission rejection happens before the middleware reads/parses the request
body, performs password hashing, or calls an owner operation.

The limit does not use IP addresses, headers, login handles, or other
caller-controlled buckets. GET session introspection and readiness/liveness
probes are excluded. Existing active-authentication concurrency remains capped
at four by default; the new rolling-window limit does not replace it.

This is a local per-process safeguard only. It is not a distributed limit and
does not establish an ingress-wide or deployment-wide rate. Configure the
deployment's ingress/gateway separately for global, client-aware controls and
network protections.
