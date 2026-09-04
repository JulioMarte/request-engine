# 15 — API design and usability standards

Status: normative design/usability standards for current product API work, compiled from authoritative external guidelines (Zalando RESTful API Guidelines, Azure REST API Guidelines, Google AIP, Stripe, OWASP API Security Top 10) and audited against the current surface. Subordinate to the normative owners of each boundary: `v3/11-product-api-contract.md`, `v3/06-capability-registry.md`, `v3/08-error-recovery-contract.md`, `v3/07-optimistic-concurrency.md` and `13-connection-surfaces.md`. Where this document and an owner contract disagree, the owner contract wins and this document must be amended.

## 1. Purpose

These standards exist so that every consumer-facing surface (public app, operations app, discovery app, copilot tool surface) behaves as **one API** from the consumer's point of view, regardless of which module owns the route. They are written for agents and engineers building module `api/` packages, and they encode what "usable" means: a developer who has integrated one module can predict the other modules.

## 2. Resource naming and endpoint shape

- Collections are plural nouns (`/v1/appointments`, `/v1/queues`); items are addressed by opaque UUID path segments. Do not re-encode tenancy in the path — the tenant comes from the authenticated actor, not the URL.
- One entity, one addressing scheme. Every route that acts on the same aggregate must use the same path root (see backlog item D1: QueueEntry is currently addressed both as `/v1/queues/{queue_id}/entries/{entry_id}/...` and `/v1/queue-entries/{entry_id}/...`).
- Semantic commands are POST action endpoints. Prefer `POST /v1/<resource>/{id}:<verb>` (Google AIP-136 style) or the existing kebab action-subpath style consistently; never mix bare-verb URLs into resource collections. Do not use GET for state changes, ever.
- Nesting depth: maximum two levels of relationship in a path; deeper relationships become filters on a flatter collection.
- Path segments are kebab-case; query params and body fields are snake_case. Path parameters use one parameter-naming style repo-wide.

## 3. Methods and status codes

| Outcome | Status | Notes |
|---|---|---|
| Query returns data | 200 | List endpoints return the pagination envelope (§5), never a bare array. |
| Command creates an aggregate | 201 | Return the created resource (or an explicit wrapper when the operation has extra facts, used consistently). |
| Command mutates/acts | 200 | Always with a body; never a silent 200 carrying an error payload. |
| Malformed/invalid request | 400 | Schema errors, unknown fields, unknown query parameters (never silently ignored), impossible values. |
| Unauthenticated | 401 | With `WWW-Authenticate`. |
| Authenticated but not allowed | 403 | Must name the missing capability/scope in `details` (§8). |
| Semantic conflict with current state | 409 | Slot gone, lifecycle conflict, idempotency fingerprint conflict. |
| Stale revision | 409 (`revision_conflict`) | Current owner contract is 409, not 412; keep the mapping uniform across modules and change it only in the owner contract. Newer surfaces ship per-aggregate conflict codes instead — see backlog D10. |
| Payload contract violation | 422 | Only where the owner contract already uses it; prefer 400 for new surface. |
| Not found (absent or cross-tenant) | 404 | Default across tenant boundaries — existence is not disclosed (RLS-safe). |
| Rate limited / overloaded | 429 / 503 | With `Retry-After`. |

Create-status discipline: every creation endpoint in the same app returns the same status (201 on the public app). Do not return 200 for creations on one surface and 201 on another.

## 4. Error responses

The house envelope is owned by `v3/08-error-recovery-contract.md` and implemented in `platform/http/errors.py`:

```json
{ "error": { "code": "...", "message": "...", "retryable": false,
             "resolution": "...", "details": { } } }
```

Standards layered on top of the owner contract:

- Every error carries one stable machine-readable `code` and a closed `resolution` vocabulary. Codes are contract: never repurpose an existing code; adding is allowed, changing meaning is not. New codes must be added to the code inventory in the owner contract, not invented ad hoc per module.
- Codes are `snake_case` everywhere. Mixed-case or parallel codes for the same failure class (see backlog D3) are defects, not style.
- Any dynamic value a human message mentions (an id, a limit, a revision) must also exist in `details`. Clients must never parse messages.
- Internal errors map to a generic 500 with the correlation id; stack traces, SQL text and provider exceptions never leave the process.
- `retryable` and `resolution` are distinct: retryable describes transport/timeout behavior, resolution tells the caller what action could fix the problem. A 403 with `resolution: fix_request` or a 422 with `resolution: refresh_and_retry` is a defect (backlog D3).

## 5. Pagination, filtering, sorting

- Every collection endpoint paginates from day one; adding pagination later is a breaking change. Cursor-based, opaque, server-issued cursors; end of collection is signaled by absence of `next_cursor` (or explicit `has_more: false`), never a null.
- The envelope is an object: `{"data": [...], "next_cursor": "...", "has_more": true}` — identical shape in every module. Bare top-level arrays are forbidden for list endpoints (existing endpoints migrate per backlog D2).
- Total counts are opt-in and expensive under RLS; do not add a `total` by default.
- Sorting uses one syntax (`sort=field,-other`), always tie-broken by id so cursors stay stable; every list documents its default order.
- Equality/status filters are simple snake_case query params. Unknown query parameters are rejected with 400, never silently ignored — a dropped `status=cancelled` filter returns wrong bookings.
- List endpoints have hard page-size caps (existing caps 100–500) and every list endpoint declares one.

## 6. Idempotency and concurrency

- Every mutating command requires `Idempotency-Key` (owned by `v3/01-capability-contracts.md`). The key is scoped per tenant; a replay returns the original response verbatim, even if the resource has since changed.
- Reusing a key with a different request fingerprint must fail with 409 `idempotency_conflict` — never a raw database error, never a silent re-execution. Validation failures that occur before execution do not consume the key.
- Mutations of revisioned aggregates take `expected_revision`; stale revision maps to the owner contract's `revision_conflict` 409 with `aggregate_kind`, `expected_revision`, `current_revision` in `details`. Some newer onboarding surfaces use per-aggregate codes with narrower details instead (backlog D10).
- Read-only operations never require an idempotency key unless they durably persist an interpretation (and then the OpenAPI metadata must say so explicitly).

## 7. Time, timezone and units

- All timestamps are RFC 3339 in UTC. Local wall-clock time is only accepted when it is bound to an explicit timezone at the owning resource: the reminder-plan pattern pairs windows with an explicit IANA timezone field, and Location-declared availability windows inherit the Location's declared IANA timezone (doc `v3/44` §6.3). A wall-clock value with no such binding is a DST correctness bug, not a style issue — window/range parameters must reject tz-naive values (backlog D11).
- Range filters are half-open `[start, end)` and documented as such.
- Durations carry the unit in the field name (`duration_minutes`); money is amount + currency, never a bare number.

## 8. Authentication and capability discovery

- Capabilities are owned by `v3/06-capability-registry.md`. Every capability-guarded route must be registered through `add_capability_route` so that its `x-request-engine-capability`, `x-request-engine-idempotency` and schema-version metadata are present and machine-checked; a route that bypasses the registry is a defect.
- A 403 always says which capability or authority the caller lacks (`capability_required` with the capability key, `party_authority_required` with party/anchor/scope, `operational_authority_required` on the operations app) — one detail shape per code, uniformly.
- `GET /v1/capabilities` remains the per-actor discovery surface (`tenant_enabled` / `actor_granted` / `runtime_available`). Every capability that can be granted must be backed by a mounted route or an explicit, documented reason; a capability advertising `actor_granted: true` for a route the deployment does not mount is a defect (backlog D4).
- Authentication mechanics (scheme, headers, token acquisition) are deployment-supplied, but the OpenAPI document must still declare them: define the bearer security scheme in `entrypoints/http`, mark each operation's security requirement, and declare 401/403 responses on operations (backlog D5). `/docs` must be able to answer "how do I make my first request".
- Authorization is checked before existence: permission failure on the parent yields 403 even when the target row does not exist; absence/other-tenant yields 404.

## 9. OpenAPI quality bar

- Every operation has a response model; `-> object` / untyped handlers are not acceptable on consumer or operator surfaces — a schema-less response cannot generate clients (backlog D6).
- Every operation declares its error responses (at minimum the envelope schema for 400/401/403/409/500 classes it can produce).
- Every operation has a one-line `summary`; descriptions are expected, not rare exceptions. The `operationId` derives from the capability key and is stable.
- The published OpenAPI surface is frozen by executable contract tests (`tests/e2e/test_public_surface_contract.py`); any surface change updates the frozen inventory in the same PR.
- Correlation: every response carries the server-generated `X-Correlation-ID`; declare it as a response header and echo it inside error envelopes as `request_id` so support can trace a failed call end to end.

## 10. Versioning and deprecation

- `/v1` is the only version prefix; evolution within it is additive. Treat as breaking: removing/renaming fields, changing types, tightening validation, adding required request fields. Prefer additive extension (new optional fields, extensible enums) over new versions.
- Clients must tolerate unknown enum values and unknown fields in responses (extensible enums).
- Deprecation is a process, not a docs note: mark the operation `deprecated: true` in OpenAPI, emit `Deprecation` and `Sunset` headers, stop new onboarding onto it, monitor usage, publish a migration guide before shutdown.

## 11. Operational surface

- Every process exposes health/readiness endpoints for probes and client circuit breakers (currently missing everywhere — backlog D7).
- No consumer-visible endpoint returns another tenant's data or leaks existence; tenant-isolation modes (`FILTERED` vs `NOT_FOUND`) are deliberate and documented.

## 12. Known drift — improvement backlog

These are audit findings against the current surface (they document reality, not approval). Fixing one is ordinary product work: follow the connection-surface gate and update the frozen surface inventory in the same change.

The business-onboarding surface (`v3/44-business-onboarding-bootstrap-contract.md`) is the first canonical consumer of §6 and §8: its creation commands require `Idempotency-Key`, register through `add_capability_route`, and return 201 on the public app. Tensions between these standards and newer owner documents are registered below until reconciled; doc 15 does not silently reinterpret an owner contract.

- **D1 (addressing)** QueueEntry has two path roots (nested under queue vs bare `/v1/queue-entries`); service-session start lives under `/queue-entries/{id}/service/start` while its own aggregate lives under `/v1/service-sessions`. Pick one addressing scheme per aggregate.
- **D2 (envelopes)** Most list endpoints return bare arrays; only `staff/history` paginates with a cursor. Standardize the envelope and paginate the unbounded lists (`GET /v1/queues`, live workloads, resource activities, party lookups/revisions).
- **D3 (error-code outliers)** `operational_recovery` uses SCREAMING_SNAKE codes; identity-exchange returns 403 with `resolution: fix_request`; discovery returns 422 with `resolution: refresh_and_retry`; live_capacity maps invalid configuration to 409 instead of 400/422; a second idempotency-conflict code exists. Bring every mapping under §4.
- **D4 (discovery gaps)** Discovery-app routes bypass the capability registry (no `x-request-engine-*` metadata); waitlist slot-offer routes are conditionally mounted while their capability always advertises.
- **D5 (auth metadata, split)** The public app now registers `CapabilityRequired` and `OperationalAuthorityRequired` handlers globally (`add_global_error_handlers` in `entrypoints/http/error_handlers.py`), so capability failures no longer surface as unhandled 500s there. Still open: the operations app registers no `CapabilityRequired` handler (a capability failure there would surface as an unhandled 500), and no app declares security schemes or 401/403 responses in its OpenAPI document.
- **D6 (operator/onboarding API schema)** All `/v1/operations/*` handlers still return untyped responses, and the onboarding bootstrap routers do too (`-> object` in catalog bootstrap/booking-policy/schedule, booking resource bootstrap, queue bootstrap, tenancy bootstrap-authority, communications channel-policy). The only typed exception is `GET /v1/onboarding/readiness` (`OnboardingReadinessView`). Summaries/descriptions remain effectively absent; every `-> object` handler is a schema-less response that cannot generate clients.
- **D7 (operational hygiene)** No health/readiness/version endpoints on any process; `entrypoints/http/README.md` route list is stale versus the real surface.
- **D8 (read model)** No list-my-* endpoints (a party's appointments, waitlist entries, reminder plans); consumers must persist every id they ever see. Also `GET /v1/appointments/slots` accepts tz-naive datetimes unlike every other window parameter.
- **D9 (status discipline)** Public-app onboarding creations now return 201 (resources, offerings, queues, resource capabilities). Remaining outliers: `POST /v1/organization/bootstrap-operational-authority` and the `operational_recovery` workflow creation routes (workflow, reschedule, workflow-communication) return 200 while sibling creations on their own surfaces return 201; update verbs are mixed (PATCH vs PUT vs POST `/update`).
- **D10 (revision-conflict code split)** Stale-revision responses are no longer uniform under the generic `revision_conflict`: newer surfaces emit per-aggregate codes — `offering_booking_policy_revision_conflict` and `location_operational_revision_conflict` (catalog), `resource_availability_revision_conflict` and `resource_location_assignment_revision_conflict` (booking) — with `{id, expected_revision, current_revision}` details and no `aggregate_kind`, while the generic `revision_conflict` remains in communications and booking task errors. Doc `v3/44` §6.2/§6.5 still describe the onboarding conflicts as `revision_conflict`, which does not match the implemented per-aggregate codes; doc 44 must be reconciled (not in this change) and the owner contract must decide one vocabulary: either one generic code with `aggregate_kind`, or a closed per-aggregate family — not both.
- **D11 (timezone binding decision)** `weekly_availability` windows in the onboarding surface are local wall-clock (`local_start`/`local_end`) and inherit the timezone declared on the owning Location instead of carrying a per-request IANA field (doc `v3/44` §6.3). §7 has been worded to accept explicit timezone binding at the owning resource; whether scheduling inputs must additionally carry a per-window IANA field (as reminder plans do) remains an open product decision to settle in the owner contract.

## 13. Anti-patterns (never do these)

1. Silent 200 carrying an error payload; errors always use the envelope and a 4xx/5xx status.
2. Bare top-level JSON arrays from list endpoints.
3. Reused idempotency key with a different fingerprint silently re-executing.
4. Unbounded, unpaginated collection endpoints.
5. Per-module error shapes or codes invented outside the owner contract's vocabulary.
6. Unknown query parameters silently ignored.
7. Wall-clock datetimes without a timezone in scheduling inputs.
8. Leaking stack traces, SQL, provider errors or other tenants' data in responses.
9. A capability registered but its route unmounted (or vice versa) without documentation.
10. Route order that makes one path capture another (`/day-board` before `/{id}`); prefer unambiguous path shapes.

## 14. Sources

- Zalando RESTful API Guidelines — https://opensource.zalando.com/restful-api-guidelines/
- Azure REST API Guidelines — https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md
- Google AIP (AIP-132/136/158/193) — https://google.aip.dev/
- Stripe idempotent requests & API versioning — https://docs.stripe.com/api/idempotent_requests
- OWASP API Security Top 10 (2023) — https://owasp.org/API-Security/
- MDN HTTP status reference — https://developer.mozilla.org/en-US/docs/Web/HTTP/Status
