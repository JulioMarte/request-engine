# HTTP entrypoint

The HTTP process exposes semantic Request Engine capabilities; it is not a table/CRUD gateway and it is not a second business taxonomy.

## Composition boundary

`entrypoints/http` owns process-level HTTP concerns only:

```text
app creation
shared authentication/trust boundary
middleware / transport-global errors
```

Business routers, transport DTOs and business-specific HTTP error mappings are owned by their modules:

```text
modules/requests/api/
modules/catalog/api/
modules/booking/api/
modules/queue/api/
```

`create_app()` composes those modules through each module's `install_http(...)` connection surface. It must not import module DB/provider adapters directly.

Conceptually:

```text
FastAPI process
     |
     | modules.<owner>.api.install_http
     |
module-owned HTTP adapter
     |
     | Command / Query
     |
module application/domain
```

See `docs/13-connection-surfaces.md`.

## Authentication boundary

`create_app()` requires an `ActorResolver`. The HTTP process has **no fallback identity mechanism** and must not trust caller-selected tenant/principal headers such as:

```text
X-Organization-Id
X-Principal-Id
```

A deployment adapter authenticates a bearer token, API key, mTLS identity, OIDC subject or equivalent and materializes an `ActorContext`:

```text
organization_id
principal_id
capabilities
```

The shared HTTP trust contract is `platform.security.http.ActorResolver`. The context is technical authenticated identity, not a replacement for tenancy `Representation` semantics. Public UUIDs never grant authority by themselves.

## Capability surfaces

Current V3 HTTP capabilities include:

```text
Requests
POST /v1/requests/definitions/{request_key}/submit
GET  /v1/requests/{request_id}
POST /v1/requests/{request_id}/result
POST /v1/requests/{request_id}/complete
POST /v1/requests/{request_id}/cancel
POST /v1/requests/{request_id}/fail

Catalog/business info
GET /v1/business
GET /v1/catalog/offerings
GET /v1/catalog/offerings/{offering_key}

Appointments
GET  /v1/appointments/slots
POST /v1/appointments
GET  /v1/appointments/{reservation_id}
POST /v1/appointments/{reservation_id}/cancel
POST /v1/appointments/{reservation_id}/reschedule

FIFO queue
GET  /v1/queues
POST /v1/queues/{queue_id}/join
GET  /v1/queues/{queue_id}/status
POST /v1/queues/{queue_id}/leave
POST /v1/queues/{queue_id}/call-next
```

Writes require `Idempotency-Key` where the underlying semantic command is idempotent. Reads and writes require the capability owned by the module.

## Errors

Business modules own mapping from their domain/application errors to HTTP. Transport-global database-integrity fallback remains at the process entrypoint.

Domain conflicts use machine-readable envelopes:

```json
{
  "error": {
    "code": "request_revision_conflict",
    "message": "...",
    "retryable": false,
    "details": {
      "expected_revision": 2,
      "current_revision": 3
    }
  }
}
```

Payload contract errors are `422`, missing resources are generally `404`, authority failures are `401/403`, and lifecycle/idempotency conflicts are generally `409`.
