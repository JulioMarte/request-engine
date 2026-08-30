# operational_copilot

F6 Operational Copilot: a bounded semantic adapter over F1-F5 operational truth. It parses strict natural-language phrases into typed intents, validates them against an explicit admission policy, and lowers them into already-published owner commands. It executes no mutations and reads no tables.

## Scope

Owned here:

- deterministic parser (`parser.py`, `parsing/`), pure: text in, typed IR or semantic refusal out;
- typed intent IR and trusted context (`contracts.py`);
- admission policy (`policy.py`), including trusted-authority requirements;
- deterministic lowering (`lowering.py`) into owner commands / at-risk query;
- application facade (`application/`): `OperationalCopilot.interpret` + at-risk inspection through the `AtRiskReservationReader` port;
- HTTP interpret surface (`api/`): `POST /v1/operational-copilot/interpret`, capability `operational_copilot.interpret`;
- composition adapter (`adapters/live_capacity_reader.py`) wrapping `live_capacity.contracts.recovery.RecoveryCapacitySource`.

Not owned: tenant/principal/authority identity, persistence, transactions, schedule/capacity/queue/publication truth, recovery policy, communications delivery, arbitrary tool execution.

## Boundary

Cross-module imports terminate at owner `contracts` surfaces only:

```text
operational_recovery.contracts.commands / contracts.workflow_commands
discovery.contracts.commands
live_capacity.contracts.recovery
```

The architecture test `tests/architecture/test_operational_copilot_module_boundary.py` enforces this module-wide.

Trust rules: `organization_id`, `principal_id`, `idempotency_key` and `authority_party_id` come only from the trusted `CopilotContext`. Natural language never supplies identity, authority or idempotency. Ambiguous, unsupported or name-based-resolution input fails closed (`errors.py`).

Normative contract: `docs/v3/35-operational-copilot-contract.md`.
