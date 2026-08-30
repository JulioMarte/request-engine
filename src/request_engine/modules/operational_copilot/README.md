# operational_copilot

`operational_copilot` is the historical module name for F6's **agent-facing operational tooling surface**. Request Engine does not embed a copilot, LLM, conversation runtime or general natural-language interpreter here.

F6 exposes bounded, typed operational reads and mutations that an external copilot, agent, application or UI can consume over F1-F5 authoritative truth.

## Product boundary

```text
external agent / application
  conversation + reasoning + tool selection
            |
            v
Request Engine F6 tool surface
  typed requests/results
  authoritative lookup/state reads
  guarded owner-command execution
            |
            v
F1-F5 owner modules
```

The agent decides what operation to attempt. Request Engine validates whether the operation is legal and executes it only through the authoritative owner.

F6 does not own schedule, capacity, queue, publication, recovery or communication truth merely because it exposes a tool that reaches those domains.

## Owned here

- typed intent/operation contracts and trusted request context (`contracts.py`);
- admission/refusal policy (`policy.py`);
- deterministic lowering into published owner commands/queries (`lowering/`);
- supported operational read composition needed by the tool surface;
- fail-closed registered mutation execution (`application/execution.py`);
- F6-owned machine-readable execution receipts;
- HTTP/tool adapters (`api/`);
- optional bounded text parsing (`parser.py`, `parsing/`) as a compatibility/test adapter.

## Explicit non-goals

F6 does not own or require:

```text
embedded LLM
conversation memory
prompt orchestration
arbitrary natural-language understanding
fuzzy autonomous entity selection
general natural-language date parsing
arbitrary SQL/tool execution
model-selected tenant/principal/authority/revision
```

An external agent may understand a sentence such as `Dr. A will work until 7 PM today`. It should then use authoritative Request Engine lookup/state tools to identify the Resource/assignment and current guarded state before invoking a structured mutation.

Request Engine must never trust a Resource ID, revision, fingerprint or authority identity merely because a model produced it.

## Current implementation

The current branch contains a strict deterministic text adapter and two HTTP surfaces:

- `POST /v1/operational-copilot/interpret`, capability `operational_copilot.interpret`;
- `POST /v1/operational-copilot/execute`, capability `operational_copilot.execute`.

The text adapter accepts a bounded DSL with explicit UUIDs/revisions/timestamps. It is useful as an admission/refusal proof and integration harness, but **it is not the F6 product boundary** and should not be expanded into a general NLU system merely to make F6 conversational.

Currently registered execution operations:

- stop/reopen recovery intake (`SetRecoveryIntakeCommand`);
- extend a recovery day (`ExtendRecoveryDayCommand`).

All other lowered mutations remain non-executable through the F6 execution surface until an owner-contract executor is explicitly registered. They fail closed rather than falling back to arbitrary tools or shadow mutation logic.

## Agent-facing reads and resolution

A complete F6 tooling surface must let an external agent obtain the authoritative identifiers/current state required by supported mutations without database access or imports from owner internals.

Where needed, lookup/read tools must support bounded tenant-scoped discovery of operational entities such as Resource, ResourceLocationAssignment, ServiceQueue, Offering and Location, plus the current revisions/freshness required by guarded commands.

Lookup is authoritative search, not model inference:

- zero matches -> explicit no-match;
- one match -> explicit candidate;
- multiple plausible matches -> explicit ambiguity;
- never silently choose one because a model or fuzzy matcher prefers it.

## Boundary

Cross-module imports inside F6 terminate at owner `contracts` surfaces only:

```text
operational_recovery.contracts.commands / contracts.workflow_commands
discovery.contracts.commands
live_capacity.contracts.recovery
tenancy.contracts.authority
```

The architecture test `tests/architecture/test_operational_copilot_module_boundary.py` enforces this module-wide. The HTTP composition root wires owner application objects only through module `api` surfaces; F6 adapters consume their published structural contracts.

Trust rules: `organization_id` and `principal_id` come only from the authenticated actor. `authority_party_id` is resolved server-side from tenant representation truth through the published `tenancy` operational authority reader. The trusted `Idempotency-Key` request identity flows into owner commands and is never derived from conversational text.

`/interpret` never executes mutations. `/execute` resolves exactly one registered executor and requires both the F6 capability and the executor-declared owner capability before invoking the owner contract. Owner concurrency, idempotency, authority, transaction and domain validation remain authoritative.

The current execution receipt is owned by F6 rather than exposing the owner's `RecoveryAction` object directly, but its fields are still recovery-shaped. It must be generalized or versioned before the same response contract is reused for non-recovery owners such as Discovery.

## F6 closure criterion

F6 is complete when an external copilot/agent with no database access and no Request Engine internal imports can satisfy the supported roadmap scenarios using only public authoritative lookup/read tools and guarded mutation tools.

It is not necessary for Request Engine itself to understand the user's arbitrary natural-language sentence.

Normative contract: `docs/v3/35-operational-copilot-contract.md`.
