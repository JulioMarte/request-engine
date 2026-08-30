# F6 Agent Operational Tooling Contract

Status: normative target contract for `feature/operational-copilot`.

> Naming note: the historical branch/module name is `operational_copilot`. The product boundary defined here is **not an embedded copilot inside Request Engine**. F6 exposes bounded operational tools that an external copilot, agent, application or UI can consume.

This contract specializes the F6 boundary in `14-operational-intelligence-roadmap.md`. Request Engine remains the authoritative operational system; the external agent decides what operation to attempt, while Request Engine decides whether the requested operation is valid and executes it only through the owning domain contract.

## 1. Product boundary

F6 exists to make F1-F5 operational capabilities safely usable as tools.

The target architecture is:

```text
LLM / voice agent / chatbot / UI / application
              |
              | reasoning, conversation, natural-language interpretation
              v
      tool / API / MCP adapter
              |
              | structured arguments
              v
        Request Engine F6
              |
              | bounded reads + guarded owner commands
              v
       F1-F5 owner modules
```

The critical rule is:

> **The agent decides what operation to attempt. Request Engine validates authority and operational truth and performs the operation through the authoritative owner.**

Request Engine does **not** need to host an LLM, conversation runtime or general natural-language interpreter for F6 to be complete.

## 2. Roadmap capability set

F6 must expose enough supported tooling for an external agent/application to:

- inspect operational truth through supported read/query surfaces;
- locate and disambiguate operational entities through authoritative, tenant-scoped lookup/read surfaces where the caller cannot safely know their identifiers in advance;
- obtain the current owner state/revisions required to construct guarded mutations without direct database access;
- extend a Resource/assignment working day through the existing owner-controlled additional-hours semantics;
- stop/reopen walk-in intake through the existing recovery/intake command semantics;
- publish/unpublish eligible supply for cross-tenant discovery through F2 semantics;
- inspect Reservations/commitments currently at risk through F4/F5 read semantics;
- propose or execute other explicitly supported operations only when an existing typed owner command/query exists.

A delivery tranche may implement a strict subset, but must record remaining tool rows as pending rather than redefine F6 around the subset.

## 3. What F6 owns

F6 owns:

- stable, typed tool contracts over supported F1-F5 operations;
- machine-readable argument/result/error contracts suitable for external agents and applications;
- bounded operational lookup/read composition needed for a caller to obtain identifiers, current state and required revisions without reading owner tables;
- explicit admission/policy validation before owner execution;
- deterministic lowering from validated structured tool requests into supported owner contracts;
- a fail-closed registry that maps an already-lowered operation to exactly one explicitly registered owner-contract executor;
- F6-owned public execution receipts rather than leaking owner application objects directly;
- optional bounded adapters, including the current deterministic text grammar, when they terminate at the same typed tool/admission boundary.

F6 does **not** own:

- an LLM or model runtime;
- conversation memory or dialogue state;
- arbitrary natural-language understanding;
- fuzzy intent inference or guessing what a user "probably meant";
- tenant/principal identity;
- owner authorization;
- persistence or transactions belonging to owner modules;
- schedule, capacity, queue, discovery publication, recovery or communications truth;
- arbitrary SQL, HTTP/tool execution or a universal command bus.

## 4. External-agent responsibility vs Request Engine responsibility

An external agent may interpret a request such as:

```text
"Dr. A will work until 7 PM today"
```

The agent is responsible for conversational interpretation such as:

- understanding that the user intends to extend working availability;
- interpreting phrases such as `today` in its conversational context;
- deciding which F6 lookup/read tools are needed before attempting the mutation;
- asking the user for clarification when business meaning remains ambiguous.

Request Engine is responsible for operational truth such as:

- which Resource(s) actually match supplied lookup criteria inside the authorized tenant;
- which ResourceLocationAssignment is current/applicable;
- the Location timezone and authoritative operational schedule state;
- current revisions/freshness tokens required by the owning command;
- whether the caller has the required tenant, party and capability authority;
- whether the requested time interval and resulting mutation are legal;
- executing only through the owner contract and preserving idempotency/concurrency semantics.

An external model must never invent an ID, revision, authority party, fingerprint or hidden owner state and have Request Engine trust it merely because it appeared in model output.

## 5. Tool composition examples

The roadmap phrases are **client-level acceptance scenarios**, not a requirement that Request Engine itself parse those exact strings.

### 5.1 Extend a working day

Human request:

```text
"Dr. A will work until 7 PM today"
```

A compliant external agent may satisfy it through a sequence conceptually like:

```text
search_resources(query="Dr. A")
get_resource_operational_context(resource_id=...)
get_current_assignment_state(assignment_id=...)
extend_day(... absolute time + current guarded state ...)
```

Concrete tool names may differ, but the caller must be able to obtain every authoritative identifier/state value through supported Request Engine surfaces rather than database/internal-module access.

### 5.2 Stop walk-ins

Human request:

```text
"stop accepting walk-ins for the rest of the day"
```

The external agent determines conversational intent and target scope. Request Engine tools must expose enough current queue/recovery state for the agent to identify the authoritative target and invoke the guarded stop-intake operation.

### 5.3 Publish discovery supply

Human request:

```text
"publish Dr. B for cardiology discovery"
```

The external agent may search/resolve Resource, Offering/classification and Location through Request Engine reads, then invoke the supported Discovery publication tool. Discovery remains publication authority and all F2 validation remains authoritative.

### 5.4 Inspect at-risk commitments

Human request:

```text
"show me which Reservations are at risk"
```

The external agent may identify the relevant current ServiceQueue through supported reads, then call the at-risk inspection tool. F4/F5 remain authoritative for the resulting projection/recovery facts.

The acceptance requirement is:

> An external agent with no database access and no imports from Request Engine internals can satisfy the supported roadmap scenarios using only public F6/owner-approved tool surfaces.

It is **not** an acceptance requirement that Request Engine understand arbitrary human wording itself.

## 6. Trust and execution boundary

`organization_id` and `principal_id` come from the authenticated application boundary. Tool arguments, text adapters and model output never choose tenant or principal authority.

`authority_party_id` is resolved server-side from tenant-owned representation truth through the published `tenancy` operational authority read contract (`OperationalAuthorityPartyReader`) when the operation requires party authority. Callers cannot inject, override or escalate it.

Mutation idempotency identity comes from the trusted request boundary. An `Idempotency-Key` (or an equivalent trusted transport identity in a future adapter) flows unchanged into the lowered owner command. Identity is never derived from conversational text.

Owner application services remain authoritative for:

- capability and representation authority;
- optimistic concurrency/freshness;
- idempotency and conflicting replay;
- transactionality;
- domain validation;
- final mutation effects.

F6 may execute a mutation **through** an explicitly registered owner adapter, but F6 never becomes the owner of that mutation.

## 7. Structured tools are the canonical boundary

The canonical F6 product boundary is typed operations, not prose.

A tool-facing request should converge on explicit structured semantics such as:

```text
operation: extend_day
assignment_id: ...
start_at: ...
end_at: ...
expected_source_revision: ...
expected_location_revision: ...
expected_availability_revision: ...
idempotency identity: trusted boundary
```

How an external caller derived those values is outside Request Engine, except that operational identifiers/current state must be obtainable through supported authoritative reads.

HTTP, MCP, SDKs, voice-agent adapters or chat-agent adapters may expose the tools. No transport may weaken the owner contracts.

## 8. Current deterministic text adapter

The branch currently contains a strict deterministic parser and the public surfaces:

- `POST /v1/operational-copilot/interpret`;
- `POST /v1/operational-copilot/execute`.

The parser accepts a bounded textual DSL using explicit UUIDs/revisions/timestamps and lowers it into typed operations. It is useful as:

- a compatibility adapter;
- an admission/refusal proof surface;
- a deterministic integration/test harness;
- an optional caller convenience layer.

It is **not the product definition of F6** and F6 closure does not require turning it into a general NLU system.

In particular, Request Engine does not need to implement fuzzy name interpretation or phrases such as `today`, `until 7 PM` or `rest of day` inside this parser. External agents may reason about such language and then use authoritative lookup/state tools plus structured mutations.

## 9. Current implemented operations

Current typed semantic/compiler coverage includes:

Recovery (F5):

```text
CreateRecoveryProposalIntent
ExecuteRecoveryIntent
SetRecoveryIntakeIntent
ExtendRecoveryDayIntent
```

Discovery (F2):

```text
PublishDiscoverySupplyIntent
RevokeDiscoveryPublicationIntent
```

Inspection (F4/F5):

```text
ShowAtRiskReservationsIntent
AtRiskReservationsQuery
```

Currently registered public execution operations are:

- `SetRecoveryIntakeCommand` -> recovery intake owner contract;
- `ExtendRecoveryDayCommand` -> recovery extend-day owner contract.

Both require `operational_recovery.execute` in addition to `operational_copilot.execute`.

Discovery publish/revoke and recovery proposal/execution already lower to published owner contracts but are not yet registered for `/execute`; execution fails closed.

## 10. Execution registry and receipts

The public execution path is bounded:

1. authenticate and require the F6 execution capability;
2. accept/validate a supported structured operation or a bounded adapter output;
3. resolve trusted authority/state inputs that F6 is explicitly responsible for resolving;
4. lower to an existing owner command;
5. resolve exactly one registered `CopilotMutationExecutor` for the concrete operation type;
6. require the executor-declared owner capability;
7. invoke the owner adapter;
8. return an F6-owned machine-readable receipt.

Zero registered executors or more than one matching executor is refusal. There is no generic fallback tool, arbitrary SQL, HTTP forwarding, reflection-based invocation or hidden execution plan.

The current `CopilotExecutionReceipt` is F6-owned but recovery-shaped (`owner_action_id`, `incident_id`, status, idempotency identity). It must be generalized or versioned before cross-owner tool reuse such as Discovery.

## 11. Lookup and resolution safety

F6 needs **authoritative lookup**, not model inference.

Supported lookup/read tools may accept bounded search keys such as names, service identifiers or scoped filters, but must:

- remain tenant/capability scoped;
- return explicit candidate identities and enough disambiguating operational metadata;
- return zero/one/multiple candidates honestly;
- never silently choose one of multiple operationally plausible entities;
- avoid exposing private cross-tenant identities;
- preserve owner/public projection boundaries;
- expose current state/revisions only through published owner read contracts.

If multiple candidates remain, the external agent/user must disambiguate before mutation.

## 12. Cross-module boundary

Inside F6, cross-module imports may consume only supported `contracts` surfaces. F6 must not import another module's application internals, adapters, persistence mappings or HTTP DTOs.

Published owner primitives currently consumed include:

- `operational_recovery.contracts.commands`;
- `operational_recovery.contracts.workflow_commands`;
- `operational_recovery.contracts.queries`;
- `discovery.contracts.commands`;
- `live_capacity.contracts.recovery`;
- `tenancy.contracts.authority`.

Future tools must first identify a supported owner command/query contract. A future executable tool must additionally register one bounded executor. If either is missing, F6 refuses.

## 13. Required proof before F6 closure

Evidence must prove:

1. every exposed mutation tool lowers to an existing published owner command;
2. every inspection/lookup tool reads through published owner query/read contracts rather than tables/internals;
3. malformed, unsupported or ambiguous structured requests fail closed;
4. an external caller cannot supply/escalate tenant, principal or authority identity through tool arguments;
5. mutation replay preserves trusted idempotency identity;
6. F6 execution preserves the executor-declared owner capability gate;
7. registered mutation replay does not duplicate durable owner effects;
8. lookup returns ambiguity rather than guessing when multiple authoritative entities match;
9. callers can obtain identifiers/current state required by supported mutations without direct database access;
10. the four roadmap scenarios can be completed by an external agent using only supported public tools, with natural-language reasoning outside Request Engine;
11. no F6 component becomes a shadow owner of schedule, capacity, queue, discovery, recovery or communications truth;
12. exact-head CI and repository architecture/typing gates are green.

No proof is required that Request Engine can understand arbitrary conversational wording.

## 14. Current old -> new disposition

At branch start there was no dedicated F6 agent-tooling surface.

Current status:

```text
typed intent / operation IR                         implemented
bounded deterministic text adapter                  implemented; optional adapter, not F6 product boundary
ambiguity + unsupported refusal                     implemented for current text adapter
explicit F6 admission policy                        implemented
recovery proposal/execution lowering                implemented
stop/reopen intake lowering                         implemented
extend-day lowering                                 implemented
discovery publish/revoke lowering                   implemented
at-risk Reservation inspection                      implemented through live_capacity read contract
F5 fingerprint resolution via owner read contract   implemented
trusted authority resolution from tenancy truth     implemented
request-scoped idempotency propagation              implemented
POST /operational-copilot/interpret                 implemented compatibility/inspection surface
POST /operational-copilot/execute                   implemented registered-executor surface
registered intake stop/reopen execution             implemented + PostgreSQL replay/effect proof
registered extend-day execution                     implemented + PostgreSQL replay/effect proof
owner-agnostic execution registry                   implemented + architecture proof
owner capability preservation in code               implemented; explicit negative proof remains a closure requirement
F6 execution receipt                                implemented, recovery-shaped; generalization pending
recovery proposal/execution via F6 execute          remaining scope if retained as public F6 tools
discovery publish/revoke via F6 execute             remaining scope
authoritative agent-facing entity lookup tools      remaining scope
authoritative current-state/revision read tools     remaining scope where existing owner reads are insufficient
structured agent-tool surface independent of text   remaining scope / needs explicit closure disposition
roadmap scenarios via external-agent tool usage     remaining acceptance proof
```

Existing exact-head CI proves the current implementation tranche; it does not by itself prove the complete agent-tooling product boundary above.

## 15. Explicit non-goals

F6 closure must not add these merely to make demos conversational:

```text
embedded LLM
conversation history/memory
prompt orchestration
RAG over business conversation
fuzzy autonomous entity choice
general natural-language date parser
arbitrary tool/plugin execution
SQL generation
model-selected tenant/principal/authority/revision
```

Those capabilities belong in external agent/application layers when needed.

Any LLM, voice, chat or UI integration is non-authoritative. It consumes F6 tools; it is not part of Request Engine's domain authority.
