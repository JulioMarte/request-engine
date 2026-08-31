# F6 Agent Operational Tooling Contract

Status: normative contract for `feature/operational-copilot`.

> Naming note: the historical branch/module name is `operational_copilot`. The product boundary defined here is **not an embedded copilot inside Request Engine**. F6 exposes bounded operational tools that an external copilot, agent, application or UI can consume.

This contract specializes the F6 boundary in `14-operational-intelligence-roadmap.md`. Request Engine remains the authoritative operational system; the external agent decides what operation to attempt, while Request Engine decides whether the requested operation is valid and executes it only through the owning domain contract.

## 1. Product boundary

F6 exists to make F1-F5 operational capabilities safely usable as tools.

```text
LLM / voice agent / chatbot / UI / application
              |
              | reasoning, conversation, tool selection
              v
      Request Engine F6 tools
              |
              | typed reads + guarded owner commands
              v
       F1-F5 owner modules
```

The critical rule is:

> **The agent decides what operation to attempt. Request Engine validates identity, authority, freshness and operational truth and performs the operation through the authoritative owner.**

Request Engine does **not** need to host an LLM, conversation runtime or general natural-language interpreter for F6 to be complete.

## 2. Roadmap capability set

F6 exposes enough supported tooling for an external agent/application to:

- inspect operational truth through owner-backed read/query surfaces;
- locate and disambiguate operational entities through authoritative tenant-scoped lookup;
- obtain current owner state/revisions needed for guarded mutations without database access;
- extend a Resource/assignment working day through Recovery-owned additional-hours semantics;
- stop/reopen walk-in intake through Recovery/Queue owner semantics;
- publish/unpublish eligible supply through Discovery owner semantics;
- inspect Reservations/commitments currently at risk through F4/F5 truth;
- create and execute supported Recovery proposals through F5 contracts.

F6 is a closed semantic set. Adding another operation requires a published owner contract, an explicit typed F6 request/intent, admission/lowering, a registered owner adapter where mutation is required, capability disposition and acceptance evidence.

## 3. What F6 owns

F6 owns:

- stable typed tool request/result/error contracts;
- bounded owner-backed operational lookup/read composition;
- explicit admission/refusal policy;
- deterministic lowering into supported owner contracts;
- a fail-closed executor registry;
- F6-owned owner-agnostic execution receipts;
- HTTP/tool adapters;
- optional bounded text adapters that terminate at the same typed admission boundary.

F6 does **not** own:

- an LLM/model runtime;
- conversation memory or prompt orchestration;
- fuzzy autonomous entity choice;
- tenant/principal identity;
- representation/authority identity;
- owner authorization;
- owner persistence or transactions;
- schedule, capacity, queue, Discovery publication, Recovery or communications truth;
- arbitrary SQL, HTTP forwarding, plugin invocation or a universal command bus.

## 4. Canonical structured boundary

The canonical F6 product boundary is typed operations, not prose.

The HTTP tool surface is rooted at:

```text
/v1/operational-copilot/tools
```

Authoritative read tools are capability-gated by `operational_copilot.read`. Current reads expose:

```text
GET /resources?reference=...
GET /offerings?reference=...
GET /queues
GET /locations/{location_id}/clock
GET /assignments/{assignment_id}/day-end?weekday=...
GET /queues/{service_queue_id}/intake
GET /queues/{service_queue_id}/recovery-incident
GET /queues/{service_queue_id}/at-risk-reservations
GET /discovery/publications/{publication_id}
```

Guarded mutation tools are capability-gated first by `operational_copilot.execute` and then by the registered executor's owner capability:

```text
POST /recovery/proposals
POST /recovery/executions
POST /recovery/intake
POST /recovery/day-extensions
POST /discovery/publications
POST /discovery/revocations
```

Every mutation uses an explicit Pydantic/typed schema. F6 intentionally does not expose a generic `{operation, payload}` command bus.

`OperationalCopilot.admit(context, intent)` is the canonical application admission boundary for already-structured intents. It performs trusted authority resolution, owner-state/fingerprint resolution where applicable, policy validation and deterministic lowering.

## 5. Text adapter disposition

The historical compatibility surfaces remain:

```text
POST /v1/operational-copilot/interpret
POST /v1/operational-copilot/execute
```

They use a bounded deterministic parser/reference resolver and then enter the same typed admission/lowering/executor path. They are useful for refusal proofs, compatibility and roadmap-language acceptance.

They are **not** the canonical F6 product boundary and must not evolve into a general NLU subsystem merely because an external agent is conversational.

The branch may support selected phrases such as `today` or `rest of day` deterministically when they are anchored to authoritative Location clock/timezone state. That convenience does not move conversational reasoning authority into Request Engine.

## 6. External-agent vs Request Engine responsibility

For a request such as:

```text
"Dr. A will work until 7 PM today"
```

an external agent may decide the user means `extend_day`, then use F6 reads to identify candidate Resources/assignments and current state.

Request Engine is responsible for:

- tenant-scoped authoritative matching;
- explicit ambiguity/no-match behavior;
- current assignment/Location/Queue/Recovery state;
- current revisions/fingerprints required by guarded owner commands;
- trusted identity and representation authority;
- owner capability enforcement;
- legal interval/state validation;
- owner execution, concurrency and idempotency.

A model-provided ID, revision, fingerprint or authority identity is never trusted merely because the model supplied it. Such values are either owner-backed observable state or are validated by the owner contract.

## 7. Lookup and ambiguity safety

Lookup is authoritative search, not model inference.

Required behavior:

- zero matches -> explicit empty/no-match;
- one match -> explicit candidate;
- multiple plausible matches -> explicit candidate set or semantic ambiguity refusal;
- never silently choose one because a fuzzy matcher/model ranks it higher;
- remain tenant/capability scoped;
- expose only owner-approved metadata;
- preserve cross-tenant/public projection boundaries.

Resource lookup returns the owner-provided display name together with Resource, Location, assignment and availability-revision identity. One Resource with multiple current assignments therefore produces multiple explicit candidates rather than an arbitrary winner.

ServiceQueue currently has no guaranteed human display label in its owner contract. F6 returns the Queue and Location identities the owner actually possesses; it does not invent presentation metadata absent from the domain model.

## 8. RecoveryIncident semantics

`SetRecoveryIntakeIntent` and `ExtendRecoveryDayIntent` lower into Recovery-owned commands. Their structured forms therefore require an authoritative `incident_id` and the relevant current owner revisions.

The read surface exposes the current open RecoveryIncident for a ServiceQueue so an external agent can compose these mutations without database access.

If no applicable RecoveryIncident exists, the Recovery-scoped operation fails closed.

This is intentional. F6 must not:

- manufacture a RecoveryIncident merely to satisfy a phrase;
- direct-write Queue intake state;
- direct-write Booking schedules;
- reinterpret a normal proactive operator request as Recovery authority.

If the product requires proactive stop-intake or schedule extension outside Recovery, a corresponding owner capability/contract must first be added to Queue/Booking/another authoritative owner. F6 may then expose that owner operation explicitly. It must not create shadow authority.

Therefore the current text behavior of phrases such as `stop accepting walk-ins for the rest of the day` or `Dr. A will work until 7 PM today` is correctly narrower than unconstrained prose: execution requires current Recovery truth.

## 9. Current typed operation set

Recovery/F5:

```text
CreateRecoveryProposalIntent
ExecuteRecoveryIntent
SetRecoveryIntakeIntent
ExtendRecoveryDayIntent
```

Discovery/F2:

```text
PublishDiscoverySupplyIntent
RevokeDiscoveryPublicationIntent
```

Inspection/F4-F5:

```text
ShowAtRiskReservationsIntent
AtRiskReservationsQuery
```

Registered mutation execution includes:

- create Recovery proposal;
- execute Recovery proposal;
- stop/reopen Recovery intake;
- extend Recovery day;
- publish Discovery supply;
- revoke Discovery publication.

There is no fallback executor. Zero or multiple registered executors for a lowered mutation is refusal.

## 10. Trust, authority and capabilities

`organization_id` and `principal_id` originate only from authenticated `ActorContext`.

`authority_party_id` is resolved server-side from tenancy representation truth through the published operational authority reader. Public tool bodies do not contain a trusted authority-party selector.

Mutation identity comes from the trusted `Idempotency-Key` transport header and is propagated into owner commands.

The structured write path performs two capability gates:

1. `operational_copilot.execute`;
2. the concrete executor's owner capability.

Owner services remain authoritative for optimistic concurrency/freshness, idempotency/conflicting replay, representation authority, transactions, domain validation and durable effects.

Read tools use `operational_copilot.read`, a query capability with no false command/idempotency semantics.

## 11. Execution receipts

`CopilotExecutionReceipt` is F6-owned and owner-agnostic:

```text
owner
action
result_id
status
idempotency_key
```

F6 does not expose RecoveryAction or DiscoveryPublication application objects as the common mutation response.

## 12. Cross-module boundary

F6 consumes published owner contracts only. It must not import another module's application internals, adapters, persistence mappings or HTTP DTOs.

Published owner primitives include contracts from:

- Booking;
- Catalog;
- Queue;
- Operational Recovery;
- Discovery;
- Live Capacity;
- Tenancy.

Concrete implementations are obtained through module `api` composition surfaces at the HTTP composition root.

F6 owns no durable owner-state table and performs no direct owner-table mutation.

Architecture fitness tests enforce the boundary, including preventing accidental cross-owner table access.

## 13. Tool composition examples

### Extend a working day

```text
lookup Resource -> explicit assignment/location candidate
read Location clock
read assignment day-end
read current RecoveryIncident
POST structured Recovery day-extension
```

The mutation remains Recovery-owned and requires the incident/current revisions.

### Stop/reopen walk-ins

```text
list/identify ServiceQueue
read intake state + revision
read current RecoveryIncident + source revision
POST structured Recovery intake mutation
```

### Publish/revoke Discovery supply

```text
lookup Resource
lookup Offering
read authoritative Location context as needed
POST structured Discovery publication
GET publication state/revision
POST structured Discovery revocation
```

### Inspect at-risk Reservations

```text
list/identify ServiceQueue
GET structured at-risk assessment
```

F4/F5 projection/recovery truth remains authoritative for the result.

## 14. Idempotency and concurrency requirements

Every public F6 mutation must preserve owner idempotency semantics:

- same trusted key + same semantic command -> same durable effect/receipt identity;
- same key + different semantic command -> conflict, never reinterpretation;
- concurrent same-key requests -> at most one durable owner effect;
- owner state/revision changes after read/resolution -> owner freshness/concurrency rules remain authoritative;
- text-adapter replay must not fabricate a new semantic payload merely because the first execution changed current state.

F6-specific concurrency evidence is required because semantic resolution occurs before the owner transaction. Owner-only concurrency tests are necessary but not sufficient.

## 15. Required proof before closure

Evidence must prove:

1. every exposed mutation lowers to an existing published owner command;
2. every read/lookup uses published owner read contracts, not F6 table access;
3. unsupported/malformed/ambiguous requests fail closed;
4. callers cannot inject/escalate tenant, principal or authority identity;
5. the F6 capability and concrete owner capability are both enforced;
6. each public mutation preserves same-key replay and conflicting replay semantics;
7. concurrent F6 semantic resolution/execution cannot duplicate durable owner effects;
8. lookup exposes ambiguity/candidates rather than guessing;
9. callers can obtain IDs/current revisions needed by supported mutations without database access;
10. Recovery proposal/execution, intake stop/reopen, extend-day and Discovery publish/revoke execute through F6 into real PostgreSQL effects;
11. the four roadmap scenarios are satisfiable using structured public tools, with natural-language reasoning allowed outside Request Engine;
12. F6 has no shadow persistence/authority;
13. docs, guarantee/proof inventory and exact-head CI describe the same implementation.

## 16. Current old -> new disposition

```text
typed intent / operation IR                         implemented
canonical structured read tool surface              implemented
canonical structured mutation tool surface          implemented
bounded deterministic text adapter                  implemented; optional adapter
ambiguity + unsupported refusal                     implemented
explicit F6 admission policy                        implemented
owner-backed Resource/Offering/Queue lookup          implemented
Location clock + assignment state reads             implemented
Queue intake + RecoveryIncident state reads         implemented
Discovery publication state/revision read           implemented
at-risk Reservation inspection                      implemented
Recovery proposal/execution                         registered through F6
stop/reopen intake execution                         registered through F6
extend-day execution                                 registered through F6
Discovery publish/revoke execution                   registered through F6
trusted authority resolution                         implemented
owner-agnostic execution registry/receipt            implemented
second owner capability gate                         implemented + negative proof
request-scoped idempotency propagation              implemented
roadmap text compatibility scenarios                implemented as bounded adapter proof
structured PostgreSQL acceptance                    implemented for proposal/execution,
                                                     intake stop/reopen and Discovery publish/revoke
concurrent natural-command replay proof              implemented
final exact-head evidence/docs convergence           closure gate
```

The feature is not declared complete merely because an older CI run is green. Closure is based on the exact current HEAD and the proof inventory required above.

## 17. Explicit non-goals

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

Any LLM, voice, chat or UI integration is non-authoritative. It consumes F6 tools; it is not part of Request Engine's domain authority.
