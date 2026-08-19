# V3 Product and API Contract

This document freezes the Phase 5 product-facing execution contract.

## 1. Execution authorization

Capability discovery and capability execution are related but different operations.

For an HTTP operation to pass the technical authorization boundary, all of these facts must hold:

1. The product defines the canonical capability.
2. The tenant capability policy enables that capability.
3. The authenticated Principal has a grant that satisfies that capability.

The runtime derives an effective actor from the intersection of tenant-enabled and actor-granted capabilities. A tenant-disabled capability cannot execute even if a stale credential still carries its grant.

Party authority remains separate. Commands and reads that operate for a Party must additionally resolve the required tenant-owned Representation or an explicit operator override permission. Domain state, capacity, revisions, and other business invariants are evaluated at execution time.

Discovery never claims that a concrete domain operation will succeed.

## 2. Capability discovery

`GET /v1/capabilities` reports stable facts independently:

- `product_supported`
- `runtime_available`
- `tenant_enabled`
- `actor_granted`

It also reports the canonical capability metadata, including operation kind, exposure, idempotency policy, revision policy, Party scope, override permission, schema version, and OpenAPI operation ID when applicable.

The API does not publish a synthetic `context_executable` value. Contextual executability depends on authoritative domain state and Party authority and therefore belongs to command/query execution.

Internal capabilities never appear in discovery.

## 3. OpenAPI contract

Every runtime-invocable capability has one stable OpenAPI operation ID derived from its canonical key.

Capability routes publish machine-readable extensions:

- `x-request-engine-capability`
- `x-request-engine-schema-version`
- `x-request-engine-idempotency`
- `x-request-engine-expected-revision`
- `x-request-engine-exposure`
- `x-request-engine-party-scope`, when applicable
- `x-request-engine-override-capability`, when applicable

OpenAPI metadata is descriptive. It is not an authorization decision.

Internal Request processing commands such as result recording, completion, and failure are not mounted in the public HTTP composition. Hiding an operation from OpenAPI is not treated as a security boundary.

## 4. Request correlation and trusted provenance

The server creates a new correlation UUID for every inbound HTTP request. Caller-provided `X-Correlation-ID` values do not select trusted correlation identity.

The server returns its correlation UUID in `X-Correlation-ID`.

The authenticated ActorContext is rebound to that request correlation and stored in task-local execution context. The context is cleared when the request finishes.

Tenant transactions inherit the trusted actor only when the actor tenant equals the requested transaction tenant. PostgreSQL receives trusted execution GUCs for tenant, Principal, Principal kind, authentication method, correlation ID, and credential identity.

Audit records derive provenance from this trusted execution context.

## 5. Durable asynchronous correlation

Correlation must survive the transaction boundary without becoming business payload.

`OutboxMessage` and `ScheduledAction` persist `correlation_data` separately from semantic payloads and dedupe fingerprints. This preserves tracing without changing command semantics or idempotency identity.

A ProviderEvent is an inbound event root. It is correlated by its provider identity tuple and provider event ID. Request Engine does not fabricate an HTTP correlation ancestry for an independently received provider event.

## 6. ReminderPlan public contract

Phase 5 exposes only ReminderPlan operations with mature transactional semantics:

- `reminders.create_plan`
- `reminders.read`
- `reminders.cancel_plan`

All use Party scope `reminders.manage`. Operators may use the separate `reminders.subject_override` permission.

Create checks exact current Party authority inside the same transaction that creates the plan.

Read does not disclose a plan when Party authority is absent.

Cancel locks the ReminderPlan, verifies Party authority, then evaluates `expected_revision`. Authority is checked before revision conflict details so aggregate revision cannot become an authorization oracle.

`reminders.cancel_plan` requires idempotency and optimistic concurrency.

Phase 5 does not publish `update_plan` or `acknowledge` because their lifecycle semantics are not yet frozen. Unsupported conceptual operations must not be advertised as runtime capabilities.

## 7. Internal processing boundary

`requests.record_result`, `requests.complete`, and `requests.fail` are integration/internal capabilities.

The public app does not register their routes. Internal application handlers remain available to trusted integration composition and workers.

Tests must exercise internal commands through the application contract or an explicitly internal composition, never by weakening the public API.

## 8. Agent-facing acceptance rule

A machine client with only authentication, `GET /v1/capabilities`, and the published OpenAPI contract must be able to map each runtime operation to one canonical capability and schema.

Opaque appointment options remain advisory transport tokens. Booking always revalidates authoritative state.

No agent is allowed to infer authority, resource ownership, or executable domain state solely from discovery metadata.

## 9. Phase 5 security gates

The Phase 5 suite must prove at minimum:

- tenant disabled plus actor granted is rejected;
- tenant enabled plus actor missing grant is rejected;
- internal operations are absent from the public HTTP router;
- caller tenant and Principal headers cannot override trusted identity;
- caller correlation headers cannot override server correlation;
- separate requests receive separate correlation IDs;
- durable outbox and scheduled work preserve trusted correlation;
- ReminderPlan create requires current Party authority;
- ReminderPlan cancellation checks authority before revision conflict;
- authorized stale ReminderPlan cancellation returns a revision conflict;
- capability discovery maps to stable OpenAPI operations;
- operator permission-only capabilities do not pretend to be runtime operations.

These are release contracts, not documentation-only expectations.
