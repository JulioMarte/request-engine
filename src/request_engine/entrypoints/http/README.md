# HTTP entrypoint

The HTTP layer exposes semantic Request Engine capabilities; it is not a table/CRUD gateway.

## Authentication boundary

`create_app()` requires an `ActorResolver`. The HTTP process has **no fallback identity mechanism** and must not trust caller-selected tenant/principal headers such as:

```text
X-Organization-Id
X-Principal-Id
```

A deployment adapter is responsible for authenticating a bearer token, API key, mTLS identity, OIDC subject or equivalent and materializing an `ActorContext`:

```text
organization_id
principal_id
capabilities
```

The context is technical authenticated identity, not a replacement for tenancy `Representation` semantics. A production resolver must derive capabilities from the tenant authority model/policy; public UUIDs never grant authority by themselves.

## Request surface

Initial V3 routes are capability-oriented:

```text
POST /v1/requests/definitions/{request_key}/submit
GET  /v1/requests/{request_id}
POST /v1/requests/{request_id}/result
POST /v1/requests/{request_id}/complete
POST /v1/requests/{request_id}/cancel
POST /v1/requests/{request_id}/fail
```

Writes require `Idempotency-Key` and the corresponding capability:

```text
requests.submit
requests.record_result
requests.complete
requests.cancel
requests.fail
```

Reads require `requests.read`.

Submit accepts an optional positive `definition_version`. When omitted, the resolver selects the highest version currently present under the active tenant `RequestDefinition`, then passes the exact immutable version ID to the command. The created Request always persists that exact version ID; later processing does not depend on a moving `latest` alias.

## Errors

Domain conflicts are exposed as machine-readable envelopes:

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

Payload contract errors are `422`, missing resources are `404`, authority failures are `401/403`, and lifecycle/idempotency conflicts are `409`. Stored Request schema configuration errors are server errors because they are operator/configuration defects, not caller payload mistakes.
