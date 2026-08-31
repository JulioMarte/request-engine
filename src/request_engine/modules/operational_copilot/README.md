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

## Canonical public tools

The canonical machine-facing boundary is `/v1/operational-copilot/tools`.

Authoritative reads use `operational_copilot.read` and currently expose:

- Resource lookup by bounded reference;
- Offering lookup by bounded reference;
- ServiceQueue listing with owner-backed display/location/offering metadata;
- Location clock / operational-day state;
- assignment day-end state;
- Queue intake state and revision;
- open RecoveryIncident state and source revision/fingerprint;
- at-risk Reservation assessment;
- Discovery publication state and revision.

Guarded mutations use `operational_copilot.execute`, then require the executor-declared owner capability before owner invocation.

Recovery-scoped operations require an open `RecoveryIncident`:

- create Recovery proposal;
- execute Recovery proposal;
- stop/reopen Recovery intake;
- extend a Recovery day.

Proactive owner operations do not require a `RecoveryIncident`; each is delegated to its owner's native authority:

- stop/reopen Queue walk-in intake (`queue.manage_intake`);
- extend an assignment's working day (`booking.manage_supply`).

Discovery operations:

- publish Discovery supply;
- revoke Discovery publication.

Every mutation accepts a closed typed schema (`extra="forbid"`): unknown or injected fields such as `organization_id`, `principal_id`, `authority_party_id` or an unrecognized revision name are rejected with `422`, never silently ignored. There is deliberately no arbitrary `operation`/payload command bus.

## Text adapter

The historical surfaces remain available:

- `POST /v1/operational-copilot/interpret`;
- `POST /v1/operational-copilot/execute`.

They are deterministic bounded text adapters over the same admission/lowering/execution path. They are useful for compatibility, refusal proofs and roadmap-language acceptance, but they are **not** the canonical F6 product boundary.

`OperationalCopilot.admit(...)` is the canonical admission boundary for an already-structured `CopilotIntent`. The text adapter parses/resolves references and then enters that same boundary; it does not get a privileged execution path.

## Recovery-scoped vs proactive operations

Recovery-owned intake control and additional-hours/day-extension commands require an existing authoritative `RecoveryIncident`. F6 does not manufacture an incident or reinterpret a normal operational request as a crisis merely to make a phrase executable. An external agent can obtain the current incident and revisions through the structured read tools and then invoke the corresponding typed Recovery mutation. If no open incident exists, the Recovery-scoped operation fails closed.

Ordinary operator control is proactive and owner-native: `POST /tools/queues/intake-control` exercises Queue intake authority, and `POST /tools/assignments/day-extensions` exercises Booking supply authority. Both still pass through F6 admission, owner capability gates, optimistic revisions and owner idempotency. F6 gains no shadow authority: proactive execution is always a delegated owner command, never a direct write to owner tables.

## Lookup and ambiguity

Lookup is authoritative search, not model inference:

- zero matches -> explicit no-match/empty candidates;
- one match -> explicit candidate;
- multiple plausible matches -> all authoritative candidates are returned or semantic resolution refuses as ambiguous;
- F6 never silently chooses one because a model or fuzzy matcher prefers it.

Resource candidates include the owner-provided display name together with `resource_id`, `location_id`, `assignment_id` and current availability revision. Queue candidates include owner-backed `service_queue_id`, `display_name`, `location_id` and `offering_id`. Offering lookup exposes owner-backed IDs/display names. Duplicate names or a Resource with multiple current assignments remain explicit ambiguity rather than becoming an arbitrary winner.

## Trust boundary

`organization_id` and `principal_id` come only from authenticated `ActorContext`. `authority_party_id` is resolved server-side from tenancy representation truth. Tool bodies cannot inject those identities.

Mutation identity comes from the trusted `Idempotency-Key` transport header. F6 preserves that identity into the owner command. Owner idempotency, optimistic concurrency, transactionality, domain validation and durable effects remain authoritative.

The structured write path performs both gates:

1. `operational_copilot.execute`;
2. the registered executor's owner capability, such as `operational_recovery.execute` or the Discovery owner capability.

## Module boundary

Cross-module imports inside F6 terminate at published owner `contracts` surfaces. The HTTP composition root obtains concrete owner readers/runtimes through each module's `api` composition surface.

F6 owns no durable business table and performs no direct owner-table mutation.

Architecture fitness tests enforce this boundary.

## Execution receipt

`CopilotExecutionReceipt` is owner-agnostic:

```text
owner
action
result_id
status
idempotency_key
```

It intentionally does not leak Recovery- or Discovery-specific application objects. `result_id` always preserves the identity returned by the authoritative owner; for Recovery execution that is `RecoveryExecution.id`.

## Closure criterion

F6 is complete when an external agent with no database access and no Request Engine internal imports can:

1. discover authoritative targets/state through structured read tools;
2. disambiguate or fail closed rather than guess;
3. construct a supported typed mutation;
4. execute it through F6 while preserving tenant/principal/authority/capability boundaries;
5. replay safely under owner idempotency/concurrency semantics;
6. complete the supported roadmap scenarios without relying on the text parser as the only API.

PostgreSQL acceptance covers Recovery proposal/execution, proactive Queue intake control, proactive Booking day extension, Recovery intake stop/reopen, Recovery day extension, Discovery publish/revoke, closed-schema injection refusal, same-key conflicting replay and concurrent same-key execution for Recovery, Queue and Booking paths. Adversarial lookup acceptance covers multi-Queue, duplicate Offering and multi-location Resource ambiguity. The four roadmap scenarios (extend day, stop walk-ins, publish Discovery, inspect at-risk Reservations) are satisfied end-to-end through structured tools alone.

Normative contract: `docs/v3/35-operational-copilot-contract.md`.
