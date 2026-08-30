# operational_copilot

F6 Operational Copilot is a bounded semantic adapter over F1-F5 operational truth. It parses strict natural-language phrases into typed intents, validates them against an explicit admission policy, lowers them into already-published owner commands, and may execute only operations that are explicitly registered at composition time. It owns no replacement domain mutation and reads no owner tables.

## Scope

Owned here:

- deterministic parser (`parser.py`, `parsing/`), pure: text in, typed IR or semantic refusal out;
- typed intent IR, trusted context, and owner-neutral execution receipt (`contracts.py`);
- admission policy (`policy.py`), including trusted-authority requirements;
- deterministic lowering (`lowering.py`) into owner commands / at-risk query;
- application facade (`application/`): interpretation, supported reads, and a fail-closed registered mutation-executor registry;
- HTTP surfaces (`api/`):
  - `POST /v1/operational-copilot/interpret`, capability `operational_copilot.interpret`;
  - `POST /v1/operational-copilot/execute`, capability `operational_copilot.execute`;
- owner-contract adapters for explicitly registered mutations;
- composition adapter (`adapters/live_capacity_reader.py`) wrapping `live_capacity.contracts.recovery.RecoveryCapacitySource`.

Currently registered execution operations:

- stop/reopen recovery intake (`SetRecoveryIntakeCommand`);
- extend a recovery day (`ExtendRecoveryDayCommand`).

All other lowered mutations remain non-executable through the F6 execution surface until an owner-contract executor is explicitly registered. They fail closed rather than falling back to arbitrary tools or shadow mutation logic.

Not owned: tenant/principal/authority identity, persistence, transactions, schedule/capacity/queue/publication truth, recovery policy, communications delivery, arbitrary tool execution.

## Boundary

Cross-module imports inside F6 terminate at owner `contracts` surfaces only:

```text
operational_recovery.contracts.commands / contracts.workflow_commands
discovery.contracts.commands
live_capacity.contracts.recovery
tenancy.contracts.authority
```

The architecture test `tests/architecture/test_operational_copilot_module_boundary.py` enforces this module-wide. The HTTP composition root wires owner application objects only through module `api` surfaces; F6 adapters consume their published structural contracts.

Trust rules: `organization_id` and `principal_id` come only from the authenticated actor. `authority_party_id` is resolved server-side from tenant representation truth through the published `tenancy` operational authority reader — never from language or HTTP parameters — and fails closed when absent or ambiguous. The `Idempotency-Key` request header is the trusted idempotency identity and flows unchanged into every lowered owner command; it is never derived from the language text. Ambiguous, unsupported or name-based-resolution input fails closed (`errors.py`).

`/interpret` never executes mutations. `/execute` first performs the same parse → trusted resolution → policy → lowering pipeline, then resolves exactly one registered executor for the lowered operation. The F6 execution capability does not replace the owner gate: the router also requires the executor-declared owner capability before invoking the owner contract. Owner concurrency, idempotency, authority, transaction and domain validation remain authoritative.

The current execution tranche is PostgreSQL-backed and exact-head CI-proven for intake stop/reopen and extend-day replay/effects. Natural entity resolution and relative operational-time resolution are still roadmap scope, not delivered capability.

Normative contract: `docs/v3/35-operational-copilot-contract.md`.
