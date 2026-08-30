# F6 Operational Copilot Contract

Status: normative target contract for `feature/operational-copilot`.

This contract specializes the F6 boundary in `14-operational-intelligence-roadmap.md`. F6 is a bounded semantic adapter over existing F1-F5 operational truth and commands. It is not an autonomous authority and owns no replacement domain mutation.

## 1. Roadmap capability set

F6 must preserve the full roadmap scope:

- inspect operational truth through supported read/query surfaces;
- extend a resource's working day through the existing owner-controlled additional-hours semantics;
- stop/reopen walk-in intake through the existing recovery/intake command semantics;
- publish/unpublish eligible supply for cross-tenant discovery through F2 semantics;
- inspect Reservations/commitments currently at risk through F4/F5 read semantics;
- propose or execute other explicitly supported semantic commands only when an existing typed owner command exists.

A delivery tranche may implement a strict subset, but must record the remaining rows as pending rather than redefine F6 around the subset.

## 2. Ownership

F6 owns:

- bounded semantic parsing;
- typed, framework-free request-semantics IR;
- ambiguity and unsupported-intent refusal;
- explicit F6 admission/policy validation;
- deterministic lowering into supported owner contracts;
- read/query composition needed to expose supported inspection intents;
- a fail-closed registry that maps an already-lowered operation to exactly one explicitly registered owner-contract executor;
- an F6-owned execution receipt for the public execution surface, rather than exposing an owner application object directly.

F6 does not own tenant/principal identity, owner authorization, persistence, transactions, schedule truth, capacity truth, queue truth, discovery publication truth, recovery policy, communications delivery, or arbitrary tool execution.

## 3. Trust and execution boundary

`organization_id` and `principal_id` come from the authenticated application boundary. Natural-language input never chooses tenant, principal or authority, and no HTTP parameter may supply them.

`authority_party_id` is resolved server-side from tenant-owned representation truth through the published `tenancy` operational authority read contract (`OperationalAuthorityPartyReader`): the resolver returns the single party the principal currently holds a valid grant for within the copilot's operational scopes, and refuses when authority is absent or ambiguous. Callers cannot inject, override or escalate authority through the request.

The mutation idempotency identity comes from the trusted request boundary: the authenticated caller supplies the `Idempotency-Key`, which flows unchanged into `CopilotContext` and every lowered owner command. Two different request keys with identical language produce different identities; the same request key replays the same identity. Identity is never derived from language text.

The parser is pure: text in, typed IR or semantic refusal out. It has no repository, database, network, provider, command bus or application-service dependency.

Mutation lowering accepts only policy-validated IR and constructs an existing owner command. Lowering itself never executes it.

The public execution path is separately bounded:

1. authenticate and require `operational_copilot.execute`;
2. run the normal parse -> trusted resolution -> policy -> lowering pipeline;
3. resolve exactly one registered `CopilotMutationExecutor` for the concrete lowered operation type;
4. require the executor-declared owner capability;
5. invoke the adapter, which delegates to the published owner contract;
6. return the F6-owned `CopilotExecutionReceipt` rather than the owner's internal application object.

Zero registered executors or more than one matching executor is a semantic refusal. There is no generic fallback tool, SQL surface, HTTP forwarding, command bus or reflection-based invocation.

The current receipt is intentionally owned by F6 but is still recovery-shaped (`owner_action_id`, `incident_id`, status and idempotency identity). It must be generalized or versioned before the same public response contract is used for a non-recovery owner such as Discovery.

The owner application service remains authoritative for concurrency, idempotency, transaction and domain validation. F6's execution capability never substitutes for the owner's capability or authority rules.

Read intents terminate at explicit supported query/read contracts; they do not read tables or adapters directly.

## 4. Refusal semantics

F6 fails closed.

- empty/unmatched text -> unsupported intent;
- multiple plausible supported actions -> ambiguous intent;
- missing identifiers or required disambiguation -> refusal, never guessed entity resolution;
- policy-invalid parameters -> policy rejection;
- unavailable owner primitive -> unsupported until that primitive is explicitly published;
- lowered mutation without exactly one registered executor -> unsupported execution;
- missing F6 execution capability or missing executor-declared owner capability -> authorization refusal;
- arbitrary SQL, generic HTTP/tool calls and hidden execution plans are forbidden.

## 5. Implemented grammar and execution registration

This tranche delivers the roadmap F6 semantic action classes as a deterministic semantic compiler. The roadmap's natural-language examples as written (for example, "Dr. A will work until 7 PM today" and "publish Dr. B for cardiology discovery") are not yet executable because name-based entity resolution and relative operational-time resolution are deliberately pending; both are refused rather than guessed.

The implemented grammar runs over already-published owner primitives. Phrases are normalized, matched deterministically and currently use explicit UUIDs. Name-based entity resolution such as "Dr. A" is refused under section 4.

Recovery (F5):

```text
propose recovery for queue <queue-uuid>
propose recovery for queue <queue-uuid> over <N> days
execute recovery proposal <proposal-uuid> for reservation <reservation-uuid>
execute recovery proposal <proposal-uuid> for reservation <reservation-uuid> source <source-fingerprint> proposal <proposal-fingerprint>
```

The execute form may append, in order, `allow subject override` and `without notification`. Fingerprints are all-or-nothing: either both are stated in language or both are omitted, in which case F6 resolves them through the published `RecoveryProposalReader` before validation. Resolution is from owner truth, never model output. Owner freshness and concurrency still decide whether a later mutation succeeds.

Recovery workflow (F5):

```text
stop walk-ins for incident <incident-uuid> source revision <N> intake revision <N>
reopen walk-ins for incident <incident-uuid> source revision <N> intake revision <N>
extend day for incident <incident-uuid> assignment <assignment-uuid> from <iso-datetime> to <iso-datetime> source revision <N> location revision <N> availability revision <N> reason <text>
```

These workflow commands are also the first registered public execution tranche:

- `SetRecoveryIntakeCommand` -> recovery intake owner contract;
- `ExtendRecoveryDayCommand` -> recovery extend-day owner contract.

Both require `operational_recovery.execute` in addition to `operational_copilot.execute`. Stop and reopen are represented by the same typed owner command with different `accepting` values.

Discovery publication (F2):

```text
publish offering <offering-uuid> at location <location-uuid> for discovery starting <iso-datetime> [ending <iso-datetime>] [with resource <resource-uuid>] [visibility hidden|public]
revoke discovery publication <publication-uuid> at revision <N>
```

Discovery commands lower to published contracts but are not yet registered for `/execute`; execution therefore fails closed rather than reaching a discovery owner implicitly.

Inspection (F4/F5):

```text
show reservations at risk for queue <queue-uuid>
```

`N` is a non-negative integer; proposal search days are bounded to 1 through 30 with an F5 default of 7 days. Fingerprints are bounded to 512 characters. Datetimes must be timezone-aware and ends must be after starts. `public` visibility requires an explicit resource.

## 6. Typed semantics, replay and dispatcher

The branch contains:

- `CreateRecoveryProposalIntent(service_queue_id, search_days)`;
- `ExecuteRecoveryIntent(proposal_id, reservation_id, expected_source_fingerprint, expected_proposal_fingerprint, allow_subject_override, notify)`;
- `SetRecoveryIntakeIntent(incident_id, accepting, expected_source_revision, expected_intake_revision)`;
- `ExtendRecoveryDayIntent(incident_id, assignment_id, start_at, end_at, expected_source_revision, expected_location_operational_revision, expected_resource_availability_revision, reason)`;
- `PublishDiscoverySupplyIntent(offering_id, location_id, effective_start, effective_end, resource_id, provider_visibility)`;
- `RevokeDiscoveryPublicationIntent(publication_id, expected_revision)`;
- `ShowAtRiskReservationsIntent(service_queue_id)`;
- trusted `CopilotContext(organization_id, principal_id, idempotency_key, authority_party_id)`;
- `ValidatedCopilotIntent` as the explicit admission boundary;
- `CopilotOperation`, which is an existing owner command or `AtRiskReservationsQuery`;
- `CopilotMutationExecutor`, the structural registered-executor contract;
- `CopilotExecutionRegistry`, which requires exactly one executor match;
- `CopilotExecutionReceipt`, an F6-owned API contract that prevents the public surface from returning the owner's `RecoveryAction` object directly.

The same trusted context plus the same validated IR must lower deterministically to the same owner command values and idempotency identity.

`authority_party_id` is never accepted from natural-language text. It arrives only through trusted resolution into `CopilotContext`, and policy refuses authority-dependent intents when it is absent.

Registered owner adapters may translate only between an already-lowered F6 operation and a published owner execution contract. They may not recreate owner business rules or persistence.

## 7. Cross-module and public API boundary

Inside the F6 module, cross-module imports may consume only supported `contracts` surfaces. F6 must not import another module's `application`, `adapters`, persistence mappings or API DTOs. Module-wide architecture tests enforce this boundary and also freeze the router/core as owner-agnostic so adding a new executable command does not grow a central type switch.

The HTTP composition root may wire concrete owner services only through module `api` surfaces, according to the repository-wide connection-surface architecture rules.

Published owner primitives consumed by F6 include:

- `operational_recovery.contracts.commands` — `CreateRecoveryProposalCommand`, `ExecuteRecoveryCommand`;
- `operational_recovery.contracts.workflow_commands` — `SetRecoveryIntakeCommand`, `ExtendRecoveryDayCommand`;
- `operational_recovery.contracts.queries` — `RecoveryProposalReader` for server-side fingerprint resolution;
- `discovery.contracts.commands` — `PublishDiscoverySupplyCommand`, `RevokeDiscoveryPublicationCommand`, `DiscoveryPublicationState`;
- `live_capacity.contracts.recovery` — recovery-capacity assessment/read contracts adapted behind the F6 at-risk reader port;
- `tenancy.contracts.authority` — operational authority read contract for trusted authority resolution.

Future grammar rows must first identify a supported owner command/query contract. Future executable rows must additionally register one bounded executor. If either is missing, F6 refuses.

Public HTTP surfaces:

- `POST /v1/operational-copilot/interpret`, capability `operational_copilot.interpret` — returns the semantic decision or supported at-risk read and never mutates;
- `POST /v1/operational-copilot/execute`, capability `operational_copilot.execute` — executes only an explicitly registered mutation and additionally enforces its owner capability.

Both accept the language in a typed JSON body and the trusted `Idempotency-Key` header.

## 8. Required proof

Before F6 closure, evidence must prove:

1. each accepted phrase lowers to a documented typed intent;
2. ambiguity and unsupported input fail closed;
3. policy-invalid mutation intent cannot lower;
4. mutation replay preserves idempotency identity;
5. parser code has no mutation/application-service dependency;
6. each mutation lowers to an existing owner command contract;
7. each inspection intent reads through an existing supported read/query surface;
8. authority cannot be supplied or escalated through natural language;
9. public execution resolves only explicitly registered operation types and preserves the owner capability gate;
10. registered mutation replay returns the same owner action identity and does not duplicate durable owner effects;
11. the four roadmap examples are implemented or explicitly dispositioned as remaining scope;
12. exact-head CI and repository architecture/typing gates are green.

Current PostgreSQL evidence proves direct F6 execution for intake stop/reopen and extend-day. The extend-day proof verifies owner effects, replay identity and preservation of the recurring schedule rather than using the previous manual bridge from F6 interpretation to the F5 HTTP endpoint.

## 9. Current old -> new disposition

At branch start there was no pre-F6 natural-language execution surface to preserve.

Current status:

```text
semantic parser / typed IR                         implemented
ambiguity + unsupported refusal                    implemented
explicit F6 admission policy                       implemented
recovery proposal/execution lowering               implemented
parser cannot directly mutate                      structural proof implemented
extend working day semantic intent                 implemented (bounded identifier grammar)
stop/reopen walk-ins semantic intent               implemented (bounded identifier grammar)
discovery publish/revoke semantic intent           implemented (bounded identifier grammar)
at-risk Reservation inspection                     implemented through live_capacity read contract
F5 fingerprint resolution via owner read contract  implemented (bounded, fail-closed)
trusted authority resolution (tenancy truth)       implemented (fail-closed, injection-refused)
request-scoped idempotency identity propagation    implemented (header -> context -> owner command)
POST /operational-copilot/interpret                implemented (decision/read surface; no mutation)
POST /operational-copilot/execute                  implemented (registered executors only; fail-closed)
registered intake stop/reopen execution            implemented + PostgreSQL replay/effect proof
registered extend-day execution                    implemented + PostgreSQL replay/effect proof
owner-agnostic execution registry                  implemented + architecture fitness proof
owner capability preservation on F6 execute        implemented
F6 execution receipt                               implemented, recovery-shaped; generalization pending
recovery proposal/execution via F6 execute         remaining scope (lowering exists; executor not registered)
discovery publish/revoke via F6 execute            remaining scope (lowering exists; executor not registered)
roadmap natural-language examples as written       remaining scope (entity + relative-time resolution pending)
natural entity resolution                         remaining scope
relative operational-time resolution              remaining scope
```

The code checkpoint `3c18136e49d622875cc045ced6744909e13b8025` passed the full PR CI pipeline, including Python quality/architecture, PostgreSQL 18 current-product proof, V2 history, repeated bootstrap, frozen V3 compatibility, observability and the V3 candidate/vertical aggregate. Documentation-only commits after that checkpoint must still survive exact-head CI before merge.

Remaining before roadmap F6 is fully delivered: authoritative entity resolution (resource/assignment/queue/offering/current operational targets from Request Engine truth), relative operational-time resolution, registration/evidence for any additional mutation classes we choose to expose through `/execute`, generalization/versioning of the execution receipt before cross-owner reuse, and direct acceptance/disposition of the roadmap examples without UUID/revision boilerplate.

Any future LLM, voice, chat or UI adapter is non-authoritative. It may produce text or a candidate semantic intent, but it must terminate at this bounded validation/lowering/execution-registration contract and cannot acquire identity, authority, revisions, idempotency or owner capabilities from model output.
