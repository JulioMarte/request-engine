# 15 — API design and usability standards

Status: **normative** for current Request Engine HTTP/OpenAPI work.

This document defines the house HTTP/usability rules. `16-canonical-operation-and-tool-projection-pattern.md` owns the higher-level relationship between owner operations, capability policy, OpenAPI operations and agent/MCP tool projections.

Current semantic authority comes from the owning module/capability contract plus `docs/testing/current-guarantees.toml`; historical V2/V3/Fx documents may preserve rationale but do not override this current standard solely because they predate it.

## 1. Purpose

Request Engine should feel like one coherent API to public clients, staff/admin UX, integrations and agents even though business truth is owned by separate modules.

Consistency must not erase domain meaning. The API should make common resource behavior predictable while keeping correctness-sensitive commands explicit.

## 2. Canonical API style

Request Engine uses **resource-oriented HTTP** as the canonical machine-facing API style.

Choose operation shape in this order:

1. standard resource semantics when the operation honestly is Create/Get/List/Update/Delete;
2. batch/aggregate resource semantics when appropriate;
3. semantic custom method when a business action cannot be represented cleanly as a standard resource mutation.

Examples:

```text
POST  /v1/locations
GET   /v1/locations/{location_id}
PATCH /v1/locations/{location_id}

POST /v1/reservations/{reservation_id}:reschedule
POST /v1/service-queues/{queue_id}:call-next
POST /v1/recovery-incidents/{incident_id}:execute
```

Exact route spelling is CONTROLLED and may evolve. Business intent must not be degraded into generic CRUD merely to satisfy a style rule.

Never use GET for state changes.

Never expose a generic canonical HTTP command bus such as:

```text
POST /v1/commands {"operation": "...", "payload": {...}}
```

## 3. Resource naming and addressing

- Collections use plural nouns.
- Path segments use kebab-case; query/body field names use snake_case.
- Tenant identity/authority comes from trusted `ActorContext`; do not make caller-selected tenant IDs the source of authority merely by placing them in the URL.
- One aggregate should converge on one canonical addressing scheme. Multiple path roots for the same resource require explicit justification/migration.
- Avoid deeply nested paths. Prefer stable resource identity plus explicit filters/relationships.
- The API is not a mirror of PostgreSQL tables. A table, view or function does not automatically become an API resource.

## 4. Standard methods vs semantic actions

Use standard resource operations when their semantics are truthful.

Creation:

```text
POST /v1/<collection>
```

Read/list:

```text
GET /v1/<collection>/{id}
GET /v1/<collection>
```

Partial user-controlled update:

```text
PATCH /v1/<collection>/{id}
```

Use semantic POST custom methods for lifecycle transitions or commands where a generic update would hide intent, locking, authority or idempotency semantics.

Examples include booking, rescheduling, check-in, call-next, intake control, recovery execution and publication transitions.

## 5. Operation identity, owner and capability

These are distinct concepts.

### Owner

The owner is the module that owns semantic validation and authoritative execution.

### Capability

The capability key is authorization policy. One capability may authorize more than one operation.

### OpenAPI `operationId`

Every consumer-facing operation must converge on a unique stable `operationId`.

`operationId` is transport/tooling identity, not an authorization grant.

Do not assume that `capability.replace('.', '_')` is permanently sufficient. Existing routes may use that fallback during migration, but any tool-projected operation must have an explicit `operationId`.

### Tool identity

Optional agent tool names are projections of owner operations. See doc 16. Tool names never replace owner/capability checks.

## 6. Canonical OpenAPI metadata

Capability-guarded routes registered via `add_capability_route` expose Request Engine metadata including:

```text
x-request-engine-operation-id
x-request-engine-owner                 # when inferable/declared
x-request-engine-capability
x-request-engine-kind
x-request-engine-schema-version
x-request-engine-idempotency
x-request-engine-expected-revision
x-request-engine-exposure
x-request-engine-party-scope           # when applicable
x-request-engine-override-capability   # when applicable
x-request-engine-tool-name             # tool projection only
x-request-engine-tool-audiences        # tool projection only
```

Do not copy these facts into a second hand-maintained operation registry.

OpenAPI metadata is descriptive/contractual; execution authorization still occurs through trusted Request Engine policy and owner validation.

## 7. Public/operator/admin separation

Public, operator and admin are **audience/trust profiles**, not three duplicated business APIs.

Prefer one owner operation with authority-sensitive availability over three independently implemented variants.

A staff/admin client may have broader discovery and capabilities than a public patient/customer client, but every invocation still validates:

```text
Principal
Organization / Representation
capability
affected Party/resource relationship
owner-specific authority
revision/idempotency/concurrency
```

Hiding a route/tool is defense in depth, not authorization.

## 8. Methods and status codes

House defaults:

| Outcome | Status | Notes |
|---|---:|---|
| successful query | 200 | typed body |
| resource creation | 201 | return created resource/view |
| synchronous semantic mutation | 200 | typed result/receipt |
| malformed request | 400 | prefer for new malformed/invalid request surfaces |
| unauthenticated | 401 | include appropriate authentication metadata |
| authenticated but unauthorized | 403 | machine-readable missing capability/authority details |
| resource absent or cross-tenant opaque | 404 | do not disclose foreign existence |
| semantic/current-state conflict | 409 | lifecycle/idempotency/revision conflict according to owner contract |
| schema validation where current contract uses it | 422 | do not invent per-module divergence |
| rate limited | 429 | `Retry-After` when meaningful |
| unavailable/overloaded | 503 | `Retry-After` when meaningful |

Changing an established owner error/status contract requires an explicit migration decision; do not “standardize” by silently changing behavior.

## 9. Errors

Current error-envelope authority remains the current platform/error contract until explicitly superseded.

Hard requirements:

- stable machine-readable error code;
- human message is not machine protocol;
- dynamic values needed for recovery also appear in structured details;
- no stack traces, SQL text or provider secrets cross the boundary;
- retryability and caller resolution are explicit where supported;
- cross-tenant objects remain opaque;
- agents and UX must not parse prose to determine next action.

RFC 9457 `application/problem+json` is a candidate protocol improvement, not silently adopted by this document. Evaluate/migrate it coherently if it materially improves the existing house envelope.

## 10. Idempotency

Every mutating capability command currently requires the capability registry's idempotency policy.

For `REQUIRED` operations:

- trusted `Idempotency-Key` transport identity is required;
- same key + same fingerprint replays the original semantic result;
- same key + different fingerprint fails closed;
- agent/MCP projection must preserve exactly the same identity and behavior;
- tool gateways may not invent a weaker retry model.

Read-only queries do not require idempotency merely because an agent calls them.

## 11. Concurrency and revisions

Revision policy belongs to the capability/owner contract.

When a mutation requires an expected revision:

- the client receives current revision/state from a supported read;
- the mutation carries the expected revision through the typed command path;
- stale state fails with the owner-defined conflict semantics;
- a tool adapter preserves rather than removes that concurrency guard.

HTTP ETag/If-Match may later project the same revision semantics where useful, but ETag must not become a second independent concurrency authority.

## 12. Pagination, filtering and sorting

For finite collections that can grow materially:

- use bounded page size;
- prefer opaque cursor pagination;
- return an object envelope rather than a bare top-level array;
- define deterministic default ordering and stable tie-breaker;
- reject unsupported/unknown filters rather than silently ignoring them;
- do not add expensive total counts by default under multi-tenant/RLS workloads.

Existing unpaginated/bare-array endpoints are migration debt, not precedent for new endpoints.

## 13. Time and units

- absolute timestamps use RFC 3339 with timezone/UTC semantics;
- local wall-clock schedule values are valid only when explicitly bound to an owning IANA timezone;
- intervals use half-open `[start, end)` semantics unless an owner contract explicitly states otherwise;
- durations include units in their names;
- monetary values are amount + currency, never context-free numbers.

## 14. OpenAPI quality bar

Every consumer-facing operation should converge on:

- unique stable `operationId`;
- typed request/response models;
- one-line summary plus useful description for non-obvious operations;
- explicit security/error responses;
- canonical Request Engine operation/capability metadata;
- documented idempotency/revision behavior;
- no untyped `object` response on a public/operator/admin surface unless it is a deliberately opaque payload contract.

Existing E2E surface tests remain the current route inventory proof. They should verify metadata relationships, not become a permanent ban on legitimate additive API evolution.

## 15. Capability and operation discovery

`GET /v1/capabilities` remains capability-policy discovery.

It answers questions such as whether a capability is known/enabled/granted/runtime-available; it is not automatically a full operation/tool catalog.

Future authorized operation/tool discovery follows doc 16 and must distinguish:

```text
known
mounted
visible
authorized
```

Those states are not interchangeable.

## 16. Agent/MCP projection

HTTP/OpenAPI remains the canonical UX/SDK API description.

Agent/MCP surfaces project selected operations; they do not create new domain implementations.

Tool projection requires:

- explicit stable operation identity;
- owner identity;
- capability policy preserved;
- typed input/output schema;
- closed audience vocabulary;
- trusted authority injected server-side;
- same idempotency/revision/failure semantics as owner operation.

See `16-canonical-operation-and-tool-projection-pattern.md` for the full design and migration plan.

## 17. Versioning and deprecation

`/v1` remains the current prefix.

Within a supported compatibility window, treat as breaking unless explicitly governed otherwise:

- removing/renaming response fields;
- incompatible type changes;
- adding newly required request fields;
- changing semantic meaning of existing error/enum values;
- changing a stable externally consumed `operationId` or tool name without migration.

Before production/external compatibility obligations trigger, controlled breaking cleanup remains possible under the evolution policies.

Deprecation must be observable and intentional: documentation/OpenAPI deprecation metadata, migration path and removal criteria are preferred over silent disappearance.

## 18. Current migration priorities

These are categories of current drift, not frozen file/path obligations:

1. converge duplicate addressing for the same aggregate;
2. paginate unbounded collection reads;
3. normalize error vocabulary where current owners disagree;
4. complete OpenAPI auth/security/error metadata;
5. replace remaining untyped consumer/operator response surfaces;
6. add health/readiness/version process surfaces where operationally required;
7. add supported list-my-* reads needed by real clients;
8. reconcile creation/status/revision-conflict inconsistencies;
9. audit every current operation for explicit stable `operationId` and owner metadata;
10. classify which existing operations should be public/operator/admin/system tools;
11. migrate the historical `operational_copilot` surface according to doc 16 rather than adding another parallel tool system.

## 19. Anti-patterns

Never introduce:

1. API shape that mechanically mirrors database tables;
2. generic `operation + payload` business command bus;
3. GET requests with business side effects;
4. route/tool hiding as the only authorization control;
5. untyped agent command payloads that can inject tenant/principal/authority identity;
6. capability key assumed to uniquely identify every HTTP operation;
7. a second registry copying capability policy;
8. MCP handlers that bypass owner commands;
9. public/operator/admin business logic forks for the same semantic operation;
10. per-module error/idempotency/concurrency semantics invented without owner/governance disposition.

## 20. References

Primary external guidance used by the current pattern:

- Google AIP-121 — https://google.aip.dev/121
- Google AIP-130 — https://google.aip.dev/130
- Google AIP-136 — https://google.aip.dev/136
- OpenAPI 3.1.1 — https://spec.openapis.org/oas/v3.1.1.html
- NIST SP 800-162 — https://csrc.nist.gov/pubs/sp/800/162/upd2/final
- RFC 9396 — https://www.rfc-editor.org/rfc/rfc9396.html
- MCP Tools 2025-11-25 — https://modelcontextprotocol.io/specification/2025-11-25/server/tools

Request Engine adopts these principles selectively. Its current owner contracts, guarantee inventory, tenant authority, idempotency and concurrency semantics remain authoritative for the product.
