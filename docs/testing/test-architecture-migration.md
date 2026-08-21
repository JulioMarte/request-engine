# Request Engine test-architecture migration ledger

Status: active migration evidence for the pre-production test-architecture restructuring.

Baseline branch: `feature/operational-profile-contextual-supply`

Baseline evidence HEAD before this migration:

```text
66038f4110863f1df47b9e05024c128fe84928f1
```

This ledger is intentionally a migration artifact. The durable policy is `docs/architecture/pre-production-evolution-policy.md`; the durable current guarantee inventory is `docs/testing/current-guarantees.toml`.

## 1. Migration rules

```text
physical test location = ownership / execution boundary
logical test metadata  = evidence class / risk
historical/             = pinned release provenance only
```

The migration must not reduce safety simply to reduce test count or runtime. A test may move or disappear only after its protected intent receives KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition.

## 2. Phase 0 evidence freeze

The pre-migration HEAD above is the comparison point for this restructuring. V3 frozen release artifacts remain immutable provenance. Current F1/product behavior is not frozen by this checkpoint.

## 3. First architecture disposition

The following files were previously collected by `tests/architecture/` but primarily validate exact V3 release/freeze artifacts rather than current architecture. Their disposition is `HISTORICAL`; their contents are preserved and moved to `tests/historical/`:

```text
test_v3_adversarial_failure_artifact_semantics.py
test_v3_adversarial_failure_proof.py
test_v3_candidate_freeze.py
test_v3_candidate_freeze_artifact_semantics.py
test_v3_database_candidate.py
test_v3_evidence_manifest_semantics.py
test_v3_final_initial_equivalence_artifact_semantics.py
test_v3_final_initial_equivalence_wiring.py
test_v3_final_initial_provenance.py
test_v3_final_release_artifact_semantics.py
test_v3_final_release_wiring.py
test_v3_invariant_proof_registry.py
test_v3_production_like_bootstrap_artifact_semantics.py
test_v3_public_contract_freeze.py
test_v3_release_harness.py
test_v3_release_inventory.py
test_v3_scratch_database_isolation.py
```

These proofs still answer `what exactly did V3 prove?`; they no longer participate in the current architecture-fitness lane merely because they are Python tests.

## 4. Explicit KEEP decisions in this pass

The following V3-named categories remain current-product evidence for now and are **not** moved merely because their names contain `v3`:

- tenant isolation / party authority adversarial PostgreSQL tests;
- capacity ownership, booking commitment and race tests;
- worker fencing, crash/retry, provider-event and ordering tests;
- reservation lifecycle and released-slot provenance tests;
- delivery lifecycle/race tests;
- communications/reminder safety tests;
- current connection-surface boundary tests.

Their release-era names are historical naming debt, not evidence that the guarantees are historical. Renaming/relocating them is a later promotion step and must not be mixed with provenance extraction when that would obscure behavior changes.

## 5. F1/current-product promotion

`tests/integration/f1_operational_profile/` remains physically feature-local while PR #75 is the active feature branch. Its CI runner is promoted now from an F1-specific product gate to a current-product gate so future migrations/features do not need to preserve `0002_f1_supply` as the permanent Alembic head.

The current-product runner therefore:

1. upgrades to repository `head`;
2. requires exactly one Alembic head;
3. verifies the database is at that current head dynamically;
4. executes the F1 operational/contextual proofs because those capabilities are current head behavior;
5. executes the still-current booking/capacity regression suites because their guarantees remain accepted, not because V3 structure is immutable.

After F1 merges, a promotion audit may relocate/rename feature-era suites by ownership. That rename is not required to make the current-product gate semantically correct.

## 6. Evidence metadata

Pytest keeps execution markers (`postgres`, `integration`, `e2e`, `concurrency`, etc.) and gains evidence/risk markers (`invariant`, `contract`, `fitness`, `adversarial`, `historical`, plus selected critical risks). `tests/architecture/` and `tests/historical/` receive their evidence marker automatically so classification does not require repetitive decorators.

The first inventory tool reports physical scope and explicit marker use. It deliberately does **not** claim full guarantee coverage yet. Guarantee-to-test proof coverage becomes enforceable only after the surviving current proofs are mapped deliberately; manufacturing green coverage from filename heuristics would defeat the purpose of the migration.

## 7. Remaining migration work after this checkpoint

```text
A  complete semantic inventory of surviving current tests
B  reconcile current-guarantees.toml against actual proofs
C  classify critical current tests with evidence/risk markers
D  disposition exact snapshots still living in current architecture tests
E  promote feature-era integration suites by ownership after F1 integration
F  split critical PR adversarial proof from extended/soak/release proof using measured cost
G  add proof-coverage enforcement only after mapping is trustworthy
H  evaluate property/state-machine/mutation strengthening for suitable domains
```

None of those steps may be used as justification to weaken the existing current safety suite while the mapping is incomplete.
