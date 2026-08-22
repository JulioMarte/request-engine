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

`test_v3_release_harness.py` contained one mixed concern: fail-closed behavior of the **current** required CI aggregate. That guarantee received `KEEP` by extracting a current `tests/architecture/test_ci_required_gate.py` proof while the original V3 harness remains historical. This deliberately favors temporary duplicate evidence over silently losing a current safety gate during the split.

## 4. Snapshot/shape adaptations

Three current architecture tests encoded useful guarantees through unnecessarily exact inventories. They received `ADAPT`, not removal:

### Repository/module inventory

Old shape:

```text
actual business modules == one exact V3-era set
historical design-chain SQL filenames == one exact list
```

New proof:

```text
all discovered business modules have ownership docs
baseline/deferred labels remain internally consistent
all discovered modules are inspected by layering/contract rules
all discovered modules must have an explicit dependency-policy entry
module dependency graph remains acyclic
executable SQL remains owned by migrations, not docs
```

A new module is therefore allowed, but it cannot silently evade architecture enforcement.

### Party-authority inventory

Old shape:

```text
current party-scoped capability map == exact release inventory
```

New proof:

```text
required current compatibility minima remain supported
AND every current runtime party-scoped capability is public, has an explicit operator override,
and that override is non-runtime/non-party-scoped
```

Additive capabilities are allowed only if they satisfy the same authority model.

### Retryable-command inventory

Old shape:

```text
all externally reachable runtime commands == exact historical set
```

New proof:

```text
every externally reachable runtime command requires idempotency
required caller-selected revision contracts remain required
server-selected revision for queue.call_next remains explicit
```

This is stronger against newly added unsafe commands while no longer making command inventory size itself a contract.

## 5. Explicit KEEP decisions in this pass

The following V3-named categories remain current-product evidence for now and are **not** moved merely because their names contain `v3`:

- tenant isolation / party authority adversarial PostgreSQL tests;
- capacity ownership, booking commitment and race tests;
- worker fencing, crash/retry, provider-event and ordering tests;
- reservation lifecycle and released-slot provenance tests;
- delivery lifecycle/race tests;
- communications/reminder safety tests;
- current connection-surface boundary tests.

Their release-era names are historical naming debt, not evidence that the guarantees are historical. Renaming/relocating them is a later promotion step and must not be mixed with provenance extraction when that would obscure behavior changes.

## 6. F1/current-product promotion

`tests/integration/f1_operational_profile/` remains physically feature-local while PR #75 is the active feature branch. Its CI runner is promoted now from an F1-specific product gate to a current-product gate so future migrations/features do not need to preserve `0002_f1_supply` as the permanent Alembic head.

The current-product runner therefore:

1. upgrades to repository `head`;
2. requires exactly one Alembic head;
3. verifies the database is at that current head dynamically;
4. executes the F1 operational/contextual proofs because those capabilities are current head behavior;
5. executes the still-current booking/capacity regression suites because their guarantees remain accepted, not because V3 structure is immutable.

After F1 merges, a promotion audit may relocate/rename feature-era suites by ownership. That rename is not required to make the current-product gate semantically correct.

## 7. Evidence metadata and inventory

Pytest keeps execution markers (`postgres`, `integration`, `e2e`, `concurrency`, etc.) and gains evidence/risk markers (`invariant`, `contract`, `fitness`, `adversarial`, `historical`, plus selected critical risks). `tests/conftest.py` automatically classifies `tests/architecture/` as `fitness` and `tests/historical/` as `historical` without child-conftest import/fixture ambiguity.

`scripts/ci/audit_test_architecture.py` produces a JSON inventory containing physical scope, explicit/effective evidence metadata, remaining V3-named current files, and feature-era current files. It fails if declared evidence markers disappear or obvious release-provenance tests drift back into `tests/architecture/`.

`docs/testing/current-proof-map.toml` is explicitly non-normative migration evidence that maps every current guarantee to representative surviving proofs and required evidence classes. The normative guarantee inventory remains path-free.

## 8. Historical source-owner resolution

The first separated historical-lane run exposed a useful false coupling: `test_v3_adversarial_failure_proof.py` verified G18 source-owner paths against the **current checkout**. After `test_retryable_command_inventory.py` was deliberately adapted/renamed, frozen V3 compatibility still passed, but that historical test failed because the old path no longer existed today.

Disposition: `ADAPT` the historical assertion, not the current architecture.

The corrected proof resolves each declared G18 source-owner path against `candidate_source_commit` from `docs/release/v3-candidate-freeze.json` using Git object lookup. It therefore answers the historical question accurately:

```text
did this declared source owner exist in the source tree whose V3 evidence was frozen?
```

It no longer asks the invalid current-product question:

```text
does current Request Engine still keep every V3 proof at its old path?
```

This preserves V3 provenance while allowing explicitly dispositioned current tests to evolve.

## 9. Frozen V3 execution-boundary disposition

A later exact-head run exposed the same category of false coupling at runtime. The frozen V3 lane installed `0001_initial` but then executed the **current post-V3 application code** and current V3-named integration tests against that deliberately stale schema. After contextual supply changed current scheduling semantics, four still-valid reservation-lifecycle proofs failed because current code correctly expected current scheduling state that `0001_initial` cannot represent.

The protected guarantees were not removed. Their disposition is:

```text
reservation lifecycle / slot recovery invariants  KEEP in current-product proof
released V3 behavior reproducibility              HISTORICAL against released V3 tree
released V3 public API compatibility minima       KEEP against current head
current-head execution on stale 0001 schema       REMOVE as a false compatibility premise
```

The historical runner now separates three questions:

```text
CURRENT PRODUCT
  current source + current Alembic head
  -> current lifecycle/capacity/authority guarantees

V3 PUBLIC COMPATIBILITY
  current source + frozen V3 public-contract baseline
  -> released operations/capabilities/errors required by compatibility remain present

V3 HISTORICAL REPRODUCIBILITY
  released V3 source tree + released 0001_initial
  -> the released behavior still reproduces in its own historical execution boundary
```

This is an `ADAPT`, not a weakening. Running current application behavior on an intentionally un-upgraded database is not a supported deployment mode and was never an external compatibility promise. Keeping that combination would make historical provenance dictate current internal scheduling implementation. `tests/architecture/test_current_product_ci_contract.py` now protects the separation so the stale-schema/current-code coupling cannot silently return.

## 10. Remaining migration work after this checkpoint

```text
A  complete semantic inventory of surviving current tests
B  continue reconciling current-guarantees.toml against actual proofs as capabilities evolve
C  classify additional critical current tests with evidence/risk markers where selection value justifies it
D  disposition remaining exact snapshots in current architecture/contract tests
E  promote feature-era integration suites by ownership after F1 integration
F  split critical PR adversarial proof from extended/soak/release proof using measured cost
G  strengthen proof-coverage enforcement only where mappings are trustworthy and non-brittle
H  evaluate property/state-machine/mutation strengthening for suitable domains
```

None of those steps may be used as justification to weaken the existing current safety suite while the mapping is incomplete.
