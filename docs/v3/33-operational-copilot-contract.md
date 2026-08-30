# F6 Operational Copilot Contract

Status: normative for `feature/operational-copilot`.

This contract specializes the F6 boundary in `14-operational-intelligence-roadmap.md`. F6 is a bounded semantic adapter over existing F1-F5 application semantics. It is not an autonomous agent and it owns no new operational mutation.

## Ownership

F6 owns:

- deterministic semantic parsing of the documented grammar;
- a typed, framework-free request-semantics IR;
- ambiguity and unsupported-intent refusal;
- an explicit F6 policy-validation gate;
- lowering validated IR into existing typed application commands.

F6 does not own tenant identity, principal identity, authorization, persistence, transactions, recovery policy, capacity truth, communication delivery, or arbitrary tool execution. Those remain with their existing owners.

## Trust boundary

`organization_id`, `principal_id`, and `idempotency_key` come from authenticated application context. They are never accepted from natural-language input.

The parser is pure. It receives text and returns IR or a semantic refusal. It has no repository, database, network, provider, command-bus, or application-service dependency.

The lowering boundary accepts only policy-validated IR. Lowering constructs an existing application command; it does not execute or mutate anything.

Execution remains the responsibility of the existing owning application service, which retains authorization, concurrency, idempotency, transaction, and domain validation.

## Bounded grammar v1

F6 initially exposes only recovery semantics that already exist in F5.

Create proposal:

```text
propose recovery for queue <queue-uuid>
propose recovery for queue <queue-uuid> over <N> days
```

`N` is an integer from 1 through 30. Omitting it preserves the F5 command default of 7 days.

Execute proposal:

```text
execute recovery proposal <proposal-uuid> for reservation <reservation-uuid> source <source-fingerprint> proposal <proposal-fingerprint>
```

The execution phrase may end with either or both of these exact modifiers, in this order:

```text
allow subject override
without notification
```

No synonym expansion, inferred identifier, fuzzy entity resolution, hidden default other than the documented F5 `search_days=7`, or trailing free text is accepted in v1.

## Typed semantics

The IR represents only the two supported intents:

- `CreateRecoveryProposalIntent(service_queue_id, search_days)`;
- `ExecuteRecoveryIntent(proposal_id, reservation_id, expected_source_fingerprint, expected_proposal_fingerprint, allow_subject_override, notify)`.

A `CopilotContext` supplies authenticated organization/principal identity and an idempotency key. The same context plus the same validated IR must lower to the same command values on replay.

## Refusal semantics

F6 fails closed.

- Empty or unmatched text -> `UnsupportedCopilotIntent`.
- Text containing markers for more than one supported action -> `AmbiguousCopilotIntent`.
- A recognized action with values outside the F6 grammar/policy -> `CopilotPolicyRejected`.
- The parser never guesses missing UUIDs, fingerprints, flags, tenant, principal, or idempotency identity.

Refusal is not an operational side effect and must not enqueue work.

## Policy validation

Policy validation is explicit and separate from parsing. V1 requires:

- proposal search horizon between 1 and 30 days;
- non-empty idempotency key in trusted context;
- execution fingerprints must be non-empty and bounded to 512 characters each.

These are F6 admission constraints, not substitutes for downstream F5 policy. F5 still validates proposal freshness, affected reservation membership, target actionability, authorization, and execution semantics.

## Lowering

Validated create-proposal IR lowers to `operational_recovery.application.commands.CreateRecoveryProposalCommand`.

Validated execute IR lowers to `operational_recovery.application.commands.ExecuteRecoveryCommand`.

F6 must import this public application command surface only for construction. It must not import F5 adapters, repositories, persistence mappings, or execution internals.

## Required proof

The branch is not complete until tests prove:

1. documented natural-language scenarios parse into typed IR;
2. ambiguous and unsupported input is rejected;
3. policy-invalid input cannot lower;
4. replay with the same trusted context lowers deterministically with the same idempotency key;
5. parser modules contain no direct mutation/application-service dependency;
6. lowered commands are the existing F5 command types, not F6-owned mutation commands.

## Old -> new disposition

There is no pre-F6 natural-language execution path to preserve. F6 adds a new adapter surface and must not reinterpret existing HTTP, worker, recovery, queue, booking, or delivery semantics.

Any future LLM, voice, chat, or UI adapter may propose text or typed semantic candidates, but it remains outside the authoritative boundary and must terminate at this same bounded parse/validation/lowering contract. Expanding grammar requires an explicit contract change plus tests before implementation.