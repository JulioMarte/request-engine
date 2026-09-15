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
AND capability is registered and runtime-available
AND ActorContext.allows(operation.capability)
```

For the public Request Engine process, the ActorContext passed to the catalog is produced by `TenantCapabilityActorResolver`, so effective capabilities are already reduced to:

```text
actor granted
INTERSECT
tenant enabled
```

Owner/Party/Representation/resource validation still runs when an operation is invoked. Catalog membership is not proof that every object instance is authorized.

Agent self-discovery additionally uses the fresh allowed/denied/risk policy as
specified in [doc 16's agent self-discovery contract](../16-canonical-operation-and-tool-projection-pattern.md#agent-self-discovery-contract-current).
The explicit catalog exception does not admit arbitrary unmarked routes.

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
openapi_pointer          # JSON Pointer within the canonical OpenAPI document
party_scope              # optional authority requirement, not an authorization result
override_capability      # optional owner-approved alternative requirement
tool_name                # optional
tool_audiences           # optional
```

The path/method are discovery information for HTTP clients, not business identity. `operation_id` remains the stable operation identity.

The envelope includes `openapi_url` (null when schema serving is disabled),
`requires_owner_validation: true`, and `agent_policy_revision` (null for non-agent
callers). Responses use `Cache-Control: no-store`. Resolve `openapi_pointer`
against the document at `openapi_url` for request/response/error schemas. The URL
is application-relative; deployments with a path prefix must resolve it against
their configured API mount. Discovery never reserves authority for a later call.

### Developer/agent consumption sequence

1. Authenticate and select the tenant through the supported transport boundary;
   request the catalog with those same credentials.
2. Select by stable `operation_id`, or match an onboarding blocker's
   `resolution_capabilities` against catalog capabilities. Do not assume one
   capability means exactly one endpoint.
3. Resolve the operation's pointer in canonical OpenAPI. Use its typed path/query/
   body and response/error schemas; follow local schema references in that same
   document rather than guessing arguments from the operation name.
4. Satisfy any Party/representation requirement and obtain required current
   revisions from the owning read. Preserve the idempotency key for a retry of
   the same command intent; never substitute discovery for concurrency checks.
5. Invoke the advertised method/path through the normal API. Handle owner errors
   and refresh relevant state after conflicts or authority changes. Do not replay
   a modified command blindly or inject principal/tenant authority in model input.

An empty catalog is not a general service-health verdict: it can mean the current
grants, tenant policy or agent policy/risk ceiling admit no mounted operations.
An agent without a policy is rejected rather than receiving an empty success.

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

- catalog visibility does not resolve object-specific Party/Representation/resource authority;
- older controller-policy upgrades and identity recovery remain acceptance gaps;
- tool projection metadata has not yet been applied systematically to owner operations;
- no MCP adapter exists;
- no claim is made that every authorized operation is suitable for an LLM.

These limitations are intentional blockers against prematurely declaring the tool surface complete.

For verified native provisioning/staff/agent implementation and remaining
production acceptance work, see [the authentication checkpoint](auth-implementation-status.md).
