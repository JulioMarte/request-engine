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
- read/query composition needed to expose supported inspection intents.

F6 does not own tenant/principal identity, authorization, persistence, transactions, schedule truth, capacity truth, queue truth, discovery publication truth, recovery policy, communications delivery, or arbitrary tool execution.

## 3. Trust boundary

`organization_id` and `principal_id` come from the authenticated application boundary. Natural-language input never chooses tenant, principal or authority, and no HTTP parameter may supply them.

`authority_party_id` is resolved server-side from tenant-owned representation truth through the published `tenancy` operational authority read contract (`OperationalAuthorityPartyReader`): the resolver returns the single party the principal currently holds a valid grant for within the copilot's operational scopes, and refuses (fails closed) when authority is absent or ambiguous. Callers cannot inject, override or escalate authority through the request.

The mutation idempotency identity comes from the trusted request boundary: the authenticated caller supplies the `Idempotency-Key`, which flows unchanged into `CopilotContext` and into every lowered owner command. Two different request keys with identical language produce different idempotency identities; the same key replays the same identity. The idempotency identity is never derived from the language text itself.

The parser is pure: text in, typed IR or semantic refusal out. It has no repository, database, network, provider, command bus or application-service dependency.

Mutation lowering accepts only policy-validated IR and constructs an existing owner command. It does not execute it. The owner application service retains authorization, concurrency, idempotency, transaction and domain validation.

Read intents similarly terminate at explicit supported query/read contracts; they do not read tables or adapters directly.

## 4. Refusal semantics

F6 fails closed.

- empty/unmatched text -> unsupported intent;
- multiple plausible supported actions -> ambiguous intent;
- missing identifiers or required disambiguation -> refusal, never guessed entity resolution;
- policy-invalid parameters -> policy rejection;
- unavailable owner primitive -> unsupported until that primitive is explicitly published;
- arbitrary SQL, generic HTTP/tool calls and hidden execution plans are forbidden.

## 5. Implemented grammar

Status framing: this tranche delivers the roadmap F6 **semantic action classes** as a deterministic semantic compiler. The roadmap's natural-language *examples as written* ("Dr. A will work until 7 PM today", "publish Dr. B for cardiology discovery") are **not yet executable**, because name-based entity resolution and relative-time resolution are deliberately pending; both are explicitly refused rather than guessed. The examples describe the target capability, not the delivered grammar.

The implemented grammar runs over already-published owner primitives. All phrases are normalized (whitespace-collapsed, case-insensitive) and matched exactly; identifiers are always explicit UUIDs. Name-based entity resolution (for example, "Dr. A") is refused: guessing entity resolution is forbidden by section 4.

Recovery (F5):

```text
propose recovery for queue <queue-uuid>
propose recovery for queue <queue-uuid> over <N> days
execute recovery proposal <proposal-uuid> for reservation <reservation-uuid>
execute recovery proposal <proposal-uuid> for reservation <reservation-uuid> source <source-fingerprint> proposal <proposal-fingerprint>
```

The execute form may append, in order: `allow subject override`, `without notification`. Fingerprints are all-or-nothing: either both are stated in the language (pass-through; the owner still validates them) or both are omitted, in which case F6 resolves them through the published `RecoveryProposalReader` owner read contract before validation. Resolution happens server-side from operational truth, never from model output; a failed or missing proposal fails closed. Owner freshness, concurrency, idempotency and authority gates remain fully in force either way — resolving a fingerprint only records "as of this trusted read" provenance; a stale proposal still loses at the owner.

Recovery workflow (F5):

```text
stop walk-ins for incident <incident-uuid> source revision <N> intake revision <N>
reopen walk-ins for incident <incident-uuid> source revision <N> intake revision <N>
extend day for incident <incident-uuid> assignment <assignment-uuid> from <iso-datetime> to <iso-datetime> source revision <N> location revision <N> availability revision <N> reason <text>
```

Discovery publication (F2):

```text
publish offering <offering-uuid> at location <location-uuid> for discovery starting <iso-datetime> [ending <iso-datetime>] [with resource <resource-uuid>] [visibility hidden|public]
revoke discovery publication <publication-uuid> at revision <N>
```

Inspection (F4/F5):

```text
show reservations at risk for queue <queue-uuid>
```

`N` is admitted only as a non-negative integer; proposal search days are bounded to 1 through 30 with an F5 default of 7 days when omitted. Fingerprints are bounded to 512 characters. Datetimes must be timezone-aware; ends must be after starts. `public` visibility requires an explicit resource. These phrases cover the roadmap's semantic action classes; name-based resolution and relative time parsing remain refused and are recorded as remaining roadmap scope, not delivered capability.

## 6. Typed semantics and replay

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
- `lowering` producing `CopilotOperation`: an existing owner command or an `AtRiskReservationsQuery`.

The same trusted context plus the same validated IR must lower deterministically to the same owner command values and idempotency identity.

`authority_party_id` is never accepted from natural-language text. It arrives only through the trusted `CopilotContext` (authenticated application boundary), and policy refuses extend-day and discovery publication/revocation intents when it is absent.

## 7. Cross-module boundary

F6 may consume only supported `contracts`/facade surfaces of owner modules. It must not import another module's `application`, `adapters`, persistence mappings or API DTOs. A module-wide architecture test enforces that every cross-module import terminates at a `contracts` surface and that only the F6 `api` layer may use the HTTP framework.

Published owner primitives consumed by F6:

- `operational_recovery.contracts.commands` — `CreateRecoveryProposalCommand`, `ExecuteRecoveryCommand`;
- `operational_recovery.contracts.workflow_commands` — `SetRecoveryIntakeCommand`, `ExtendRecoveryDayCommand` (authoritative definitions moved out of `application/workflow_commands.py`, which reexports them);
- `operational_recovery.contracts.queries` — `RecoveryProposalReader` protocol for server-side fingerprint resolution (satisfied structurally by `OperationalRecoveryService`);
- `discovery.contracts.commands` — `PublishDiscoverySupplyCommand`, `RevokeDiscoveryPublicationCommand`, `DiscoveryPublicationState` (new published surface; `application/commands/publication.py` reexports);
- `live_capacity.contracts.recovery` — `RecoveryCapacitySource` / `RecoveryCapacityAssessment` as the at-risk inspection read contract, adapted behind the F6 `AtRiskReservationReader` application port;
- `tenancy.contracts.authority` — `OperationalAuthorityPartyReader` protocol and its PostgreSQL adapter, published for composition roots to wire trusted authority resolution.

Future grammar rows must first identify a supported owner command/query contract. If no such contract exists, F6 must refuse rather than invent a shadow mutation.

The public application/API entrypoint is `application.copilot.OperationalCopilot` (parse -> resolve authority -> resolve fingerprints -> validate -> lower, plus at-risk inspection through the reader port) and `api` route `POST /v1/operational-copilot/interpret` with capability `operational_copilot.interpret`. The interpret endpoint accepts the language in a typed JSON body plus the trusted `Idempotency-Key` header; it returns the typed semantic decision (owner command summary or at-risk view) and never executes mutations. Mutation execution remains at the owner module's own endpoints/commands with their full authority, concurrency, idempotency and audit contracts.

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
9. the four roadmap examples are implemented or explicitly dispositioned as remaining scope;
10. exact-head CI and repository architecture/typing gates are green.

## 9. Current old -> new disposition

At branch start there is no pre-F6 natural-language execution surface to preserve.

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
public F6 application/API entrypoint               implemented (POST interpret, no mutation execution)
authority/capability integration proof             implemented (PostgreSQL e2e through owner surface)
PostgreSQL owner-gate evidence                     implemented (tests/e2e/test_f6_copilot_owner_gates.py, test_f6_copilot_authority.py, test_f6_copilot_fingerprints.py, test_f6_copilot_extend_day.py)
roadmap natural-language examples as written       remaining scope (entity + relative-time resolution pending)
natural-language execution surface                 remaining scope (interpret-only tranche; execution via owner surfaces)
exact-head CI on the branch head                   green (PR #102 head)
```

The PostgreSQL-backed proof in `tests/e2e/` demonstrates that copilot-lowered commands executed through owner surfaces preserve optimistic-concurrency, idempotency and authority gates, that at-risk inspection reads through the live_capacity read contract, that caller-supplied authority is ignored in favour of tenant representation truth, and that refusal fails closed when authority is absent.

Remaining before the roadmap F6 capability is fully delivered: natural entity resolution (resource/assignment/queue/offering from Request Engine truth, never from a model), relative operational-time resolution, and an explicit registered-executor execution surface (`interpret -> validated operation -> owner executor`). A future LLM adapter may draft candidate language but never resolves identities, authority, revisions or idempotency.

Any future LLM, voice, chat or UI adapter is non-authoritative. It may produce text or a candidate semantic intent, but it must terminate at this bounded validation/lowering contract and cannot acquire authority from model output.