# HTTP authentication admission limits

Request Engine applies a PostgreSQL-shared rolling-window limit to mutating
native-authentication requests (`POST` below `/auth/native/` and
`PUT /auth/native/password`) and to `POST` requests below `/v1/setup/`. The default is
120 attempts in the preceding 60 seconds. Configure it with
`REQUEST_ENGINE_HTTP_MAX_AUTHENTICATION_PER_MINUTE`, an exact decimal integer
from 1 through 10,000. Invalid configuration fails process startup rather than
disabling the limit.

The authoritative window is stored as a single bounded PostgreSQL state row.
Admission locks that row briefly, prunes timestamps at least 60 seconds old,
and atomically records only admitted attempts. Attempts rejected while the
window is full remain blocked until an admitted timestamp expires. The array
cannot exceed the configured maximum of 10,000 entries. A rejected attempt
returns HTTP 429
with the standard error envelope (`request_rate_exceeded`) and a `Retry-After`
value rounded up from the remaining window for the oldest retained attempt.
Admission rejection happens before the middleware reads/parses the request
body, performs password hashing, or calls an owner operation.

The limit does not use IP addresses, headers, login handles, or other
caller-controlled buckets. GET session introspection and readiness/liveness
probes are excluded. The existing local active-authentication concurrency cap
of four also covers setup requests; it still applies alongside the shared rate
limit.

The first replica to reach the database binds the configured limit in shared
state; later replicas with a different limit fail closed until they are
configured consistently. The application role can call the narrow database
function but has no direct permission to reset its state. The database call is
bounded by a 100 ms lock timeout, 250 ms client statement timeout, and one
second total for pool checkout, query and commit. Database errors or unavailable
shared admission fail closed with HTTP 503 before the body is read. To change the shared limit, coordinate replicas,
then have a database operator update `configured_limit` and clear `attempts` in
the singleton state row. Set `REQUEST_ENGINE_HTTP_SHARED_AUTH_ADMISSION=false`
only for an explicitly accepted local-only deployment; the local fallback is
process-scoped and does not establish an ingress-wide rate. Configure the
deployment's ingress/gateway separately for client-aware controls and network
protections. The shared bucket is global across authentication/setup endpoints,
not per IP, login handle, or tenant; replicas must use the same configured limit.
