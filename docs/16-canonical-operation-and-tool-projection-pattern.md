# 16 — Canonical operation and tool-projection pattern

Status: **normative** for new Request Engine machine-facing API work and for migration of existing HTTP/tool surfaces.

This document defines how Request Engine exposes the same business capabilities coherently to human-facing UX, SDKs, integrations and AI agents without creating duplicate business APIs or a generic command bus.

It complements:

- `10-module-ownership-map.md` — business ownership;
- `13-connection-surfaces.md` — boundary design;
- `15-api-design-and-usability-standards.md` — HTTP/OpenAPI house standards;
- `testing/current-guarantees.toml` — semantic guarantees;
- `platform/security/capabilities.py` — current capability authorization policy.

## 1. Decision

Request Engine uses this pattern:

```text
                     owner capability
                           |
                  semantic operation
                           |
               canonical HTTP/OpenAPI
                           |
          +----------------+----------------+
          |                                 |
        UX / SDK                     authorized tool projection
                                            |
                                      MCP / agent clients
```

The canonical product API is **resource-oriented HTTP with semantic custom methods when standard resource methods do not express user intent cleanly**.

Agent tools are projections of existing owner operations. They are not an independent execution architecture.

MCP is a supported future transport/projection for agents, not Request Engine's internal domain protocol and not the source of business truth.

## 2. Why this pattern

Request Engine has two kinds of operations:

1. ordinary resource lifecycle operations where standard HTTP/resource semantics are natural;
2. correctness-sensitive domain commands where a generic CRUD update would hide the business intent.

Examples of the first category:

```text
create Location
get Offering
list ServiceQueues
update mutable configuration
```

Examples of the second:

```text
book Reservation
reschedule Reservation
check in QueueEntry
call next QueueEntry
stop/reopen intake
extend operational day
execute Recovery action
publish/revoke Discovery supply
```

The second category must remain semantic. A generic `PATCH status=...` or generic `POST /commands` would weaken authorization, idempotency, concurrency, auditability and domain ownership.

External guidance supports this choice:

- Google AIP-121: resource-oriented design uses named resources, standard methods where appropriate and custom methods when standard methods do not fit; API shape should not mirror the database schema.
- Google AIP-136: custom methods are appropriate when arbitrary actions cannot be expressed cleanly through standard methods and should reflect user intent.
- OpenAPI 3.1: every operation may have a unique stable `operationId`, per-operation security requirements and specification extensions.
- NIST SP 800-162: authorization decisions may depend on subject, object, operation and environment attributes rather than role alone.
- RFC 9396: OAuth Rich Authorization Requests exist because coarse scopes do not express all fine-grained authorization needs.
- MCP tool specification: tools have unique names plus typed input/output schemas and are discoverable/callable independently of their underlying HTTP representation.

Request Engine adopts the useful principles, not every convention from those standards. In particular, tenant identity continues to come from trusted `ActorContext`; we do not re-encode tenant authority into URL hierarchies merely to imitate another API style.

## 3. Four concepts that MUST remain separate

Do not collapse these concepts into one key or one registry.

### 3.1 Business owner

The owner is the module that owns the operation's business semantics and final validation.

Examples:

```text
catalog
booking
queue
onboarding
operational_recovery
```

Tool gateways and entrypoints do not become owners because they expose or route an operation.

### 3.2 Capability key

The capability key is authorization policy.

Examples:

```text
appointments.book
queue.manage_intake
onboarding.read
operational_recovery.execute
```

One capability may authorize more than one HTTP operation. Therefore capability key is not a safe unique operation identity.

`CapabilityDefinition` remains the current authority for:

```text
exposure
query vs command kind
idempotency policy
revision policy
party-scope / override policy
runtime availability
```

Do not create a second registry containing copies of those fields.

### 3.3 OpenAPI `operationId`

`operationId` uniquely identifies one HTTP operation for OpenAPI tooling, generated clients and operation-level metadata.

It MUST be stable once an independently deployed consumer relies on it.

It MUST NOT be inferred solely from the capability key when multiple operations share one capability.

Changing a URL does not automatically require changing `operationId` if the semantic operation remains the same.

### 3.4 Tool name

A tool name identifies an agent-facing projection of an operation.

It is optional: not every HTTP operation is useful or safe as an agent tool.

The default tool name may equal the explicit `operationId`; a migration or protocol adapter may use another stable MCP-safe name when justified.

Tool naming never grants authority.

## 4. HTTP modeling rule

Choose the HTTP shape in this order:

1. standard resource method when the semantics really are Create/Get/List/Update/Delete;
2. batch/aggregate resource operation when that is the real product concept;
3. semantic custom method when the action cannot be represented honestly as a standard resource mutation.

Examples:

```text
POST  /v1/locations
GET   /v1/locations/{location_id}
PATCH /v1/locations/{location_id}

POST /v1/reservations/{reservation_id}:reschedule
POST /v1/service-queues/{queue_id}:stop-intake
POST /v1/service-queues/{queue_id}:call-next
POST /v1/recovery-incidents/{incident_id}:execute
```

Exact existing URLs may migrate under `15-api-design-and-usability-standards.md`; this document does not freeze route spelling.

### Never model business commands as

```text
PATCH {"status": "called"}
POST /v1/commands {"operation": "...", "payload": {...}}
POST /v1/tools/{arbitrary_name} as the canonical HTTP business API
```

A generic transport invocation may exist inside MCP because MCP itself uses generic `tools/call`; it must immediately resolve to a typed registered owner operation.

## 5. Canonical operation metadata

Capability-guarded HTTP operations registered through `add_capability_route` expose machine-readable metadata in OpenAPI.

Current canonical extensions are:

```text
x-request-engine-operation-id
x-request-engine-owner
x-request-engine-capability
x-request-engine-kind
x-request-engine-schema-version
x-request-engine-idempotency
x-request-engine-expected-revision
x-request-engine-exposure
x-request-engine-party-scope              # when applicable
x-request-engine-override-capability      # when applicable
x-request-engine-tool-name                # only when tool-projected
x-request-engine-tool-audiences           # only when tool-projected
```

The metadata intentionally distinguishes operation identity from authorization policy.

For module-owned routes, owner may be inferred from the endpoint's module path. A route outside a normal module path must declare owner explicitly before it may be exposed as a tool.

Tool-exposed operations require an explicit stable `operationId`; relying on the legacy capability-derived fallback is not sufficient.

## 6. Authorization model

Tool visibility and operation authorization are different controls.

```text
discovery filtering
      !=
execution authorization
```

A caller should normally discover only operations useful to its audience/authority context, but hiding an operation is never security.

Every invocation still passes through the normal trusted authority boundary:

```text
authenticated Principal
        +
Organization / Representation / Party relationships
        +
required capability
        +
resource/object constraints
        +
owner validation
        +
revision/idempotency/concurrency rules
```

This is intentionally compatible with capability-based policy plus ABAC/ReBAC-style contextual checks.

### Tool audiences

Current tool-discovery vocabulary is:

```text
public
operator
admin
system
```

These are **discovery/UX profiles**, not authority grants and not necessarily equal to one stored role.

A receptionist and an administrator can both be authenticated employees while receiving different capabilities and therefore different effective operations.

## 7. Public, operator and admin clients

Do not create three independently implemented business APIs.

Preferred:

```text
one owner operation
    |
    +-> public consumer when authority permits
    +-> staff/operator UX when authority permits
    +-> administrator UX when authority permits
    +-> agent tool projection when explicitly enabled
```

Separate process surfaces may still exist when trust/deployment boundaries justify them, but they must delegate to the same owner operation rather than duplicate semantics.

## 8. OpenAPI is the canonical UX/SDK description

OpenAPI remains the canonical machine-readable description for HTTP clients.

Each consumer-facing operation should converge on:

- unique stable `operationId`;
- typed request and response schemas;
- explicit owner/capability/kind/idempotency/revision metadata;
- explicit security/error contract;
- stable resource/action semantics;
- no database-shape leakage.

OpenAPI specification extensions are appropriate for Request Engine's policy metadata because OpenAPI explicitly permits extensions.

Do not build a separate hand-maintained SDK/tool registry that repeats OpenAPI + capability metadata.

## 9. Tool projection and future MCP adapter

A tool gateway may expose a subset of HTTP/owner operations to an agent.

Conceptually:

```text
OpenAPI operation + capability policy + tool projection metadata
                         |
                         v
                  authorized tool catalog
                         |
               +---------+---------+
               |                   |
          native tool API        MCP tools/list
                                      |
                                  MCP tools/call
                                      |
                                      v
                              same owner operation
```

MCP-specific schemas/names may be generated/adapted from the canonical typed operation contract.

MCP must not introduce:

- a second business implementation;
- direct table access;
- a universal untyped command payload;
- trusted identity fields supplied by the model;
- weaker capability checks than HTTP/UX paths.

MCP tool annotations are descriptive hints, not trusted authorization policy.

## 10. Onboarding, Operational Recovery and the tool gateway

These remain separate responsibilities even when exposed together.

### Onboarding

Owns readiness/setup-journey composition:

```text
what is missing before journey X is operational?
```

It reads owner facts and reports blockers. It does not own Catalog/Booking/Queue/etc. configuration facts.

### Operational Recovery

Owns durable exception/recovery workflows after normal operational truth has degraded.

It may coordinate owner commands but does not become owner of Booking/Catalog/Queue/Communications truth.

### Operational tools gateway

The current `operational_copilot` package is historical naming for an agent-facing tool surface. The target architecture is a generic authorized **operational/tool gateway**.

It owns only gateway concerns such as:

```text
tool discovery/projection
input/output schema exposure
reference-resolution helpers specific to tool use
admission/refusal
trusted authority injection
owner delegation
normalized tool execution receipts
```

It MUST NOT own business truth or copy owner policy.

Renaming/restructuring the package is a controlled migration, not required in this foundational change.

## 11. Onboarding-driven administration pattern

An administrative agent or UX should be able to compose owner operations without a god-module.

Example:

```text
1. onboarding readiness -> missing_location
2. catalog Location create operation
3. onboarding readiness -> missing_offering + missing_resource_supply
4. catalog Offering create operation
5. booking Resource/Assignment/Schedule operations
6. onboarding readiness -> READY
```

Future readiness blockers may expose machine-readable owner and suggested-operation references, but Onboarding does not execute those operations itself.

## 12. Migration plan for the current repository

The migration is incremental. Do not rewrite every endpoint in one PR.

### Stage A — metadata foundation (this change)

- keep `CapabilityDefinition` as authorization-policy authority;
- add canonical operation/kind/owner/tool-projection OpenAPI metadata through `add_capability_route`;
- require explicit stable `operationId` before a route can opt into tool projection;
- add architecture tests for the metadata relationship;
- update current normative docs.

### Stage B — current HTTP operation audit

Inventory each currently supported operation and classify:

```text
owner
resource vs custom method
operationId
capability
query/command
idempotency
revision policy
public/operator/admin/system relevance
agent-tool suitability
```

Resolve duplicate capability-derived `operationId`s with explicit stable IDs instead of inventing new capability keys.

Do not rename URLs merely to satisfy aesthetics; change route shapes only where the current API has genuine ambiguity or inconsistent resource addressing.

### Stage C — administrative setup completeness

For the supported business onboarding journeys, verify that owner APIs exist for all required setup actions:

- Tenancy identity/organization/staff authority;
- Catalog Locations/Offerings/configuration;
- Booking Resources/Assignments/availability/supply policy;
- Queue configuration;
- Communications configuration;
- Discovery publication where applicable.

Missing operations must be implemented by the owner module first. The tool gateway only projects them.

### Stage D — readiness/action linkage

Evolve Onboarding readiness to report stable blocker codes and, where useful, suggested owner `operationId`s.

This is guidance to clients, not automatic authority or execution.

### Stage E — authorized operation catalog

Build one runtime catalog from canonical OpenAPI operation metadata plus current capability/ActorContext policy.

The catalog must distinguish:

```text
known operation
visible/discoverable operation
currently authorized operation
runtime-mounted operation
```

Do not treat `visible` as `authorized`.

### Stage F — migrate `operational_copilot`

Audit the existing structured tools against owner operations.

For each tool classify:

```text
DIRECT_PROJECTION
AGENT_SPECIFIC_ADAPTER
DUPLICATE_OWNER_LOGIC
HISTORICAL_TEXT_COMPATIBILITY
```

Move toward `operational_tools`/`agent_tools` semantics. Remove duplicate owner logic rather than merely renaming files.

The deterministic text parser remains optional compatibility unless a real consumer requires it.

### Stage G — MCP adapter

Only after the canonical catalog is reliable:

- expose authorized tools through MCP `tools/list`;
- map MCP `tools/call` to the same typed owner execution path;
- generate input/output JSON Schema from canonical typed contracts where practical;
- map business failures into actionable tool execution errors without hiding canonical Request Engine error identity;
- preserve idempotency/revision/authority semantics.

### Stage H — protocol consistency hardening

Continue the existing API backlog:

- response/error schema consistency;
- RFC 9457 evaluation/migration if adopted;
- pagination consistency;
- security metadata;
- revision/ETag mapping where useful;
- deprecation/versioning policy;
- current-route addressing cleanup.

These are protocol improvements, not prerequisites for preserving business ownership.

## 13. Required tests / fitness functions

The test strategy intentionally avoids one mega-snapshot.

### Architecture/unit level

Protect:

- tool projection requires explicit stable `operationId`;
- tool projection requires owner identity;
- tool audiences use the closed vocabulary;
- MCP-facing tool names use an MCP-safe vocabulary;
- OpenAPI operation metadata keeps capability policy visible;
- tool metadata does not replace capability metadata.

### Current HTTP E2E surface

Continue using the existing HTTP-surface classification to protect:

- route inventory changes are deliberate;
- idempotency headers match capability policy;
- OpenAPI capability metadata matches `CapabilityDefinition`;
- operation IDs remain deterministic/current.

Extend that proof to assert canonical operation/kind metadata emitted by `add_capability_route`.

### Future tool/MCP proof

When the runtime catalog/MCP adapter exists, prove:

- unauthorized tools are not advertised;
- manually invoking an undiscoverable admin tool without authority still fails;
- public/operator/admin principals receive appropriately different catalogs;
- tool input/output schemas match owner operation contracts;
- same idempotency key behavior is preserved through HTTP and tool adapters;
- stale revision and tenant/Party authority failures remain owner-equivalent;
- no tool directly mutates owner persistence.

## 14. Future-operation checklist

Before adding a new machine-facing operation answer:

```text
Owner:
Resource or semantic custom method:
HTTP path/method:
Stable operationId:
Capability:
Query or command:
Idempotency:
Revision/concurrency policy:
Party/resource authority rule:
Tool projection needed? why?
Tool audiences:
Tool name (if overridden):
Input/output schemas:
Failure semantics:
Current guarantee IDs affected:
```

If these questions do not have coherent answers, implementation is premature.

## 15. Anti-patterns

Never introduce:

1. one generic `operation + payload` HTTP command bus;
2. a hand-maintained tool registry that copies capability policy;
3. MCP business handlers that bypass owner operations;
4. tool discovery used as the only authorization check;
5. model-supplied tenant/principal/authority identity treated as trusted;
6. capability key assumed to uniquely identify an HTTP operation;
7. tool name assumed to be a business owner;
8. database tables mechanically exposed as API resources;
9. a new `admin` bounded context merely because admin UX crosses many existing owners;
10. Onboarding becoming a provisioning god-module;
11. Recovery becoming owner of the facts it coordinates;
12. route/path snapshots used as permanent architecture constraints when semantic operation identity can remain stable.

## 16. External references

Research basis for this pattern:

- Google AIP-121 — Resource-oriented design: https://google.aip.dev/121
- Google AIP-130 — Method-category selection: https://google.aip.dev/130
- Google AIP-136 — Custom methods: https://google.aip.dev/136
- OpenAPI Specification 3.1.1 — Operation Object, Security Requirements and extensions: https://spec.openapis.org/oas/v3.1.1.html
- NIST SP 800-162 — Attribute Based Access Control: https://csrc.nist.gov/pubs/sp/800/162/upd2/final
- RFC 9396 — OAuth 2.0 Rich Authorization Requests: https://www.rfc-editor.org/rfc/rfc9396.html
- Model Context Protocol 2025-11-25 — Tools: https://modelcontextprotocol.io/specification/2025-11-25/server/tools

These references inform the house pattern. Request Engine remains authoritative for its own tenant, capability, idempotency, concurrency and ownership semantics.
