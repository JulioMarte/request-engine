# Authorized operation catalog

Status: **current Stage E component contract**, subordinate to `docs/16-canonical-operation-and-tool-projection-pattern.md` and the owning capability/authority contracts.

## 1. Purpose

Request Engine exposes operation discovery separately from capability-policy discovery.

```text
GET /v1/capabilities
    -> capability definitions / tenant availability / actor grants

GET /v1/operation-catalog
    -> concrete mounted canonical HTTP operations visible to the effective ActorContext
```

A capability is authorization policy; an operation is an executable HTTP contract. One capability may authorize multiple operations, so they must not be represented as the same identity.

## 2. Source of truth

The operation catalog is **derived**, not hand-maintained.

It reads the FastAPI/OpenAPI document that is actually mounted in the current process and selects only operations carrying the canonical Request Engine metadata emitted by `add_capability_route`:

```text
x-request-engine-operation-id
x-request-engine-owner
x-request-engine-capability
x-request-engine-kind
x-request-engine-exposure
x-request-engine-idempotency
x-request-engine-expected-revision
```

Routes without complete canonical metadata are not advertised.

The catalog therefore does not create another operation registry and cannot advertise an operation that is absent from the mounted process solely because a document says it should exist.

## 3. Authorization filter

An operation is returned only when:

```text
operation is mounted
AND canonical metadata is complete
AND ActorContext.allows(operation.capability)
```

For the public Request Engine process, the ActorContext passed to the catalog is produced by `TenantCapabilityActorResolver`, so effective capabilities are already reduced to:

```text
actor granted
INTERSECT
tenant enabled
```

Owner/Party/Representation/resource validation still runs when an operation is invoked. Catalog membership is not proof that every object instance is authorized.

### Current operations-process distinction

The existing operations/control-plane process historically receives the request-bound authenticated actor directly rather than the public process's tenant-feature-filtered actor. Stage E preserves that behavior rather than silently redefining operator semantics.

A later security/product decision must determine whether tenant feature policy should also constrain control-plane operations. Until then, documentation and tests must not imply that the two processes have identical tenant-feature semantics.

## 4. Returned contract

Each catalog item contains:

```text
operation_id
owner
capability
kind
exposure
idempotency
expected_revision
method
path_template
tool_name                # optional
tool_audiences           # optional
```

The path/method are discovery information for HTTP clients, not business identity. `operation_id` remains the stable operation identity.

## 5. This is not yet MCP tools/list

`/v1/operation-catalog` lists authorized canonical operations. It does not automatically turn every operation into an AI tool.

An explicit tool projection additionally requires:

```text
x-request-engine-tool-name
x-request-engine-tool-audiences
```

and future tool discovery must intersect that projection metadata with the same authority rules.

Therefore:

```text
authorized operation
    != automatically agent-exposed tool
```

This protects public agents from receiving administrative operations merely because those operations are mounted on the same HTTP process.

## 6. Security properties

The catalog MUST preserve these properties:

1. knowing an operation ID never grants visibility or execution authority;
2. an actor lacking a capability does not receive operations protected by it;
3. tool metadata never grants authority;
4. one capability may map to many operation IDs without collision;
5. routes missing canonical metadata are excluded rather than guessed;
6. trusted tenant/principal identity continues to come from ActorContext;
7. owner validation remains authoritative at execution time;
8. discovery must not bypass Party/Representation/RLS protections by returning business data.

## 7. Relationship to Onboarding

Onboarding blockers currently expose:

```text
code
owner
resolution_capabilities
```

They do not hardcode HTTP operation IDs from other owners.

A client/agent may combine:

```text
onboarding blocker resolution_capabilities
        +
/v1/operation-catalog
```

to discover which concrete operations the current actor can use to address the blocker.

This naturally supports the case where one capability authorizes several possible operations and prevents Onboarding from depending on another module's HTTP API shape.

## 8. Current limitations before tool/MCP projection

- not every operations-app route has canonical metadata yet;
- many administrative response schemas remain untyped (`object`);
- staff Representation/grant lifecycle is not yet a supported admin API;
- fresh tenant business-Party provisioning is not yet proven;
- tool projection metadata has not yet been applied systematically to owner operations;
- no MCP adapter exists;
- no claim is made that every authorized operation is suitable for an LLM.

These limitations are intentional blockers against prematurely declaring the tool surface complete.
