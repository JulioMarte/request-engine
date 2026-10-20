# 0018 — MCP tool gateway on the tenant runtime API

Status: Accepted (2026-10-19), by product-owner request. This records the Stage G
adapter of [doc 16](../16-canonical-operation-and-tool-projection-pattern.md); it is
not a production deployment certification.

## Context

Each business is expected to run a "Chief of Staff" AGENT Principal (operating mode
`assisted`, sponsored by the business owner) that the owner talks to from an MCP
client such as Claude Code or Claude Desktop, by text or voice. Agents and humans
already authenticate against the tenant runtime API (workload tokens, native
sessions), and `GET /v1/operation-catalog` already returns only operations the
caller may invoke now (grants ∩ tenant policy; for agents also allowed − denied
capabilities and the risk ceiling). `add_capability_route` could already emit tool
projection metadata, but no operation used it and no MCP endpoint existed.

The design must not add a second business execution path, copy capability policy,
trust model-supplied identity, or run a language model inside Request Engine.

## Decision

1. **Transport.** The tenant runtime app mounts `POST /mcp/organizations/{organization_id}`
   (MCP Streamable HTTP, stateless, JSON responses, no SSE and no `Mcp-Session-Id`).
   `GET` returns 405 with `Allow: POST`. Supported protocol versions are
   `2025-06-18` and `2025-03-26`; `initialize` echoes a supported client version,
   otherwise answers the latest. Methods: `initialize`, `notifications/initialized`
   (202, empty body), `ping`, `tools/list`, `tools/call`. JSON-RPC parse/invalid
   request/method/params errors use -32700/-32600/-32601/-32602; batches are rejected
   with -32600. The route is excluded from OpenAPI because it is a protocol adapter,
   not an owner operation. The JSON-RPC surface is implemented directly (two small
   entrypoint modules) instead of adding the `mcp` SDK, keeping dependencies and the lockfile
   audit unchanged.
2. **Authentication/authorization.** The route itself grants nothing. A missing
   bearer is HTTP 401 with `WWW-Authenticate: Bearer`; a bearer rejected by the
   runtime is also 401. A present `Origin` header must equal the request host
   (browser cross-origin requests are rejected with 403). Discovery and every tool
   call re-enter the **same ASGI application** in-process (`httpx.ASGITransport`)
   with only the caller's `Authorization`, the path's organization as
   `X-RE-Organization-ID`, and the tool's `Idempotency-Key`. Request budgets,
   authentication, tenant capability policy, agent policy, risk ceiling, mutation
   budgets, idempotency and owner validation therefore run unchanged. Inner calls
   run in a separate task so task-local actor state cannot leak between them.
3. **Discovery.** `tools/list` calls the caller's own operation catalog and keeps
   entries carrying a tool name and the `operator` audience. Each tool is projected
   from the operation's canonical OpenAPI object (`openapi_pointer`): name = tool
   name, title/description from the operation, `inputSchema` = path + query
   parameters + JSON body properties with local `$ref`s inlined and required lists
   kept, plus a required `idempotency_key` string where the operation requires an
   `Idempotency-Key`. Annotations are hints only: `readOnlyHint` for queries,
   `destructiveHint` for cancel/revoke-like commands, `idempotentHint` when a key
   is required, `openWorldHint` false. Operations the gateway cannot map faithfully
   (cookies, other headers, non-JSON or non-object bodies, name collisions) fail
   closed and are not exposed.
4. **Execution.** `tools/call` resolves the name in the caller's **current**
   catalog on every call. Unknown and unauthorized tools are the same -32602
   "Unknown tool" error. Arguments are split into the owner operation's own
   path/query/body inputs; unexpected arguments (for example `organization_id` or
   `principal_id`) and path values that could re-route the inner request are
   -32602. Results carry compact JSON text, `structuredContent` when the body is an
   object, and `isError` for status ≥ 400; owner errors stay tool results with the
   canonical API error envelope so a model can self-correct. A credential refused
   by discovery during `tools/call` (suspended agent, missing policy) is an
   `isError` result; during `tools/list` it is JSON-RPC error -32003 with the
   envelope. The gateway logs nothing and stores nothing.
5. **Projection set.** Fourteen existing OPERATIONAL-plane, risk-classified owner
   operations are marked with `tool_audiences=("operator",)` and an explicit stable
   `operation_id`: Party register/lookup, business info, catalog offering
   search/details, appointment find-slots/book/read/cancel/reschedule, queue
   list/status, and Request submit/read. Staff, agent, identity, delegation and
   platform operations are not projected by this decision. Any later route that
   carries tool metadata (for example an owner-approved staff invitation proposal)
   is picked up automatically, still subject to the same catalog authority.
6. **Voice and conversation** belong to the MCP client. Request Engine receives
   only text tool calls; it hosts no LLM runtime or conversational state.

### Operation design gate (for the projection)

```text
Business owner           unchanged: tenancy, catalog, booking, queue, requests
Resource/custom method   unchanged owner routes
HTTP path/method         unchanged
Stable operationId       now explicit; values equal the previous derived IDs
Capability               unchanged CapabilityDefinition keys
Query or command         unchanged
Idempotency policy       unchanged; exposed as the idempotency_key argument
Revision policy          unchanged; expected_revision stays an owner body field
Party/resource authority unchanged owner validation at execution
Tool projection needed?  yes: assisted agents operate the business through MCP
Tool audiences           operator
Input/output schemas     derived from canonical OpenAPI; no copied registry
Failure semantics        canonical error envelope inside isError tool results
Guarantees affected      INV-MCP-PROJECTION-001 (new); agent policy/risk/budget
                         guarantees apply unchanged through the gateway
```

### Connection gate (for the gateway)

```text
Business owner            none; HTTP composition (entrypoints/http)
Capability                none of its own; each tool's owner capability
Inbound caller/contract   MCP client over Streamable HTTP (JSON-RPC 2.0)
AuthN/AuthZ boundary      caller's bearer forwarded to the unchanged runtime
Application Command/Query the owner operation behind the projected route
Transaction/idempotency   owner transaction; Idempotency-Key from idempotency_key
Domain invariants         owner-enforced only
Database surface          none directly
Cross-module surface      none; composes over HTTP inside one process
Provider/event surface    none
Failure/retry semantics   owner envelope returned; retry with the same key only
                          for the same intended change
```

## Consequences

- One execution path: an MCP call and a direct HTTP call are indistinguishable to
  owners, audit, policy and budgets. Revoking a grant, changing policy or
  suspending an agent takes effect on the next MCP request.
- An inner call holds an additional request-budget slot while the outer MCP request
  is active; under saturation a tool returns the canonical capacity error.
- Tool descriptions and input schemas are only as good as the owner OpenAPI
  metadata; projected routes therefore carry explicit summaries/descriptions.
- No `outputSchema` is advertised yet, because error results would not conform.
- No pagination of `tools/list` and no `listChanged` notifications (stateless).
- OAuth-based MCP authorization discovery is not implemented: clients supply an
  existing bearer header.

## Rejected alternatives

- **Separate MCP execution path** calling application services directly: would
  duplicate authentication, policy, risk, budget and idempotency enforcement.
- **Hand-maintained tool registry**: copies capability policy and drifts.
- **Exposing every authorized operation as a tool**: authorized is not the same as
  suitable for an LLM; projection is an explicit owner decision.
- **Model-supplied organization or principal arguments**: identity comes only from
  the authenticated bearer and the connection path.
- **An LLM/voice runtime inside Request Engine**: conversation is the client's
  concern; Request Engine stays a typed operations API.
- **Adding the `mcp` Python SDK**: larger dependency and audit surface for a small,
  stable JSON-RPC subset.

## Required evidence

- `tests/unit/test_mcp_gateway_protocol.py` — JSON-RPC parsing, version negotiation,
  transport refusals before actor resolution, audience/authority filtering.
- `tests/unit/test_mcp_tool_projection.py` — schema building, `$ref` inlining,
  argument splitting, injection/re-routing rejection, fail-closed projection.
- `tests/architecture/test_api_operation_pattern.py` — every mounted projected tool
  has explicit operationId/owner, OPERATIONAL plane, classified non-authority risk
  and maps to an MCP tool.
- `tests/e2e/test_mcp_gateway_http.py` (PostgreSQL 18) — a provisioned assisted
  agent sees only policy-allowed tools, registers a Party through MCP with durable
  provenance, replays the idempotency key without a duplicate, cannot invoke
  hidden tools or inject identity, loses access when suspended; a human session
  uses the same tools; missing/invalid bearer and cross-origin requests are refused.
