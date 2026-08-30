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

`organization_id`, `principal_id`, capability/authority context and mutation idempotency identity come from the authenticated application boundary. Natural-language input never chooses tenant, principal or authority.

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

## 5. First implementation slice

The branch currently starts with a deliberately narrow proof over already-integrated F5 recovery commands:

```text
propose recovery for queue <queue-uuid>
propose recovery for queue <queue-uuid> over <N> days
execute recovery proposal <proposal-uuid> for reservation <reservation-uuid> source <source-fingerprint> proposal <proposal-fingerprint>
```

The execute form may append, in order:

```text
allow subject override
without notification
```

`N` is admitted only from 1 through 30. Omission preserves the existing F5 default of 7 days. Fingerprints are required and bounded to 512 characters.

This slice proves the F6 architecture; it does **not** close the roadmap capability set in section 1.

## 6. Typed semantics and replay

The first slice contains:

- `CreateRecoveryProposalIntent(service_queue_id, search_days)`;
- `ExecuteRecoveryIntent(proposal_id, reservation_id, expected_source_fingerprint, expected_proposal_fingerprint, allow_subject_override, notify)`;
- trusted `CopilotContext(organization_id, principal_id, idempotency_key)`;
- `ValidatedCopilotIntent` as the explicit admission boundary.

The same trusted context plus the same validated IR must lower deterministically to the same owner command values and idempotency identity.

## 7. Cross-module boundary

F6 may consume only supported `contracts`/facade surfaces of owner modules. It must not import another module's `application`, `adapters`, persistence mappings or API DTOs.

For the first slice, recovery command DTOs are published from `operational_recovery.contracts.commands`; the historical `operational_recovery.application.commands` path reexports those same classes for internal compatibility.

Future grammar rows must first identify a supported owner command/query contract. If no such contract exists, F6 must refuse rather than invent a shadow mutation.

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

Current first-slice status:

```text
semantic parser / typed IR                         started
ambiguity + unsupported refusal                   started
explicit F6 admission policy                      started
recovery proposal lowering                        started
recovery execution lowering                       started
parser cannot directly mutate                     structural proof pending
extend working day semantic intent                pending primitive mapping
stop/reopen walk-ins semantic intent               pending primitive mapping
discovery publish/unpublish semantic intent        pending primitive mapping
at-risk Reservation inspection                    pending read-contract mapping
public F6 application/API entrypoint               pending
authority/capability integration proof             pending
exact-head CI                                      pending
```

Any future LLM, voice, chat or UI adapter is non-authoritative. It may produce text or a candidate semantic intent, but it must terminate at this bounded validation/lowering contract and cannot acquire authority from model output.