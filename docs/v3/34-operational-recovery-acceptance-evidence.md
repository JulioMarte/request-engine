# F5 Operational Recovery and Communications acceptance evidence

Status: evidence ledger for the F5 completion gate in `32-operational-recovery-communications-contract.md`.

This document records what has actually been demonstrated. It is intentionally stricter than a feature checklist: a scenario is not marked complete merely because related code exists or because an unrelated aggregate suite is green.

## Evidence baseline

Validated feature head:

```text
e987ad426d56373673424c31a6b1b82867e3cb3b
```

Pull request: `#81` (`feature/operational-recovery-communications` -> `development`).

GitHub Actions run: `33071329389` / CI run `#2565`.

The run completed successfully. Its `PostgreSQL 18 current product proof` job ran the repository current-product harness against PostgreSQL 18.6, upgraded through `0008_operational_recovery`, and reported:

```text
224 passed, 2 deselected
```

The aggregate `PostgreSQL 18 V3 candidate and verticals` job also completed successfully, as did Python quality/architecture, V2 design history, repeated V3 bootstrap, frozen V3 compatibility, and observability runtime contract.

This SHA is historical evidence for the implementation state immediately before the documentation-only scope/evidence closure commits. The final branch head still requires its own exact-head CI before merge.

## Contract scenario traceability

| Contract scenario / guarantee | Durable proof at validated SHA | Result | Disposition |
| --- | --- | --- | --- |
| A — material shortfall uses authoritative capacity/commitment semantics | F4/Booking current-product PostgreSQL proofs plus `tests/modules/live_capacity/test_recovery_affected_selection.py` protect affected-selection semantics | PASS as component evidence | The exact 10 -> 6 -> deterministic 4 narrative is not represented as one monolithic E2E; the guarantee is split by owning boundaries. Do not claim an affected-count-only test as sufficient. |
| A — affected set excludes still-executable Reservations | `tests/modules/live_capacity/test_recovery_affected_selection.py` | PASS in Python quality/module suite | Regression proof added during F5 hardening after the naive shortfall-fill algorithm was removed. |
| A — broken current supply cannot accept new intake | existing Booking/F1/F4 PostgreSQL capacity and closure/revalidation proofs in the current-product gate | PASS as reused authority | F5 owns no intake switch; this is deliberately reused Booking authority. |
| B — proposal is immutable/read-only and creates no recovery execution or communication intent | F5 proposal repository/service implementation plus current E2E public-surface/security coverage | PASS as distributed evidence | Proposal semantics are implemented, but a single named scenario-B journey remains desirable if future changes make this boundary less obvious. |
| B — contextual targets are not falsely actionable | `tests/modules/operational_recovery/test_recovery_target_policy.py` | PASS | Explicit fail-closed coverage for unsupported contextual reschedule. |
| C — stale proposal cannot mutate Booking or create notification/outbox effects | F5 execution stale guards and current-product E2E recovery coverage exercised inside `tests/e2e` | PASS in aggregate current-product run | Negative-side-effect semantics are contract requirements; keep them explicit when this suite is refactored. |
| D — exact replay/concurrent execution converges on one recovery action | F5 durable uniqueness/advisory execution serialization plus current-product E2E | PASS in aggregate current-product run | PostgreSQL-backed execution path was included in the 224-test E2E run. |
| D — successful Booking recovery has stable Communications lineage/dedupe | F5 Recovery -> Communications integration plus Communications E2E durability/worker suites | PASS | Communications remains the delivery authority. |
| D — provider/worker retry does not duplicate the business mutation | Communications worker/reconciliation E2E, including `tests/e2e/test_communication_worker_resilience.py` and provider-result/lease/fence coverage | PASS | Repair is Communications-only after Booking success. |
| Public F5 HTTP surface is classified and capability metadata is frozen | `tests/e2e/http_surface_f5.py` + `tests/e2e/test_public_surface_contract.py` | PASS | Prevents silent public-surface growth and checks capability/idempotency metadata. |

## Acceptance interpretation

The validated CI proves the current product tree, migration head, HTTP/runtime journeys and PostgreSQL-backed regression suites were green together. It does **not** redefine the roadmap: scope truth comes from contract 32 and the explicit roadmap disposition in document 33.

The repository evidence policy also does not require every guarantee to live in a file named `test_f5_acceptance_*`. Physical placement follows owning boundary. What is required is traceability from a normative guarantee to falsifiable durable proof and the canonical lane that executed it.

Where the table above says `distributed evidence`, future refactoring must preserve the guarantee rather than the historical filename. If a future reviewer cannot identify the negative side effects or authoritative state asserted by the referenced proof, that row must be strengthened rather than waved through because CI is green.

## Scope truth at closure

F5 v1 delivers immutable recovery proposals, deterministic affected-Reservation provenance, supported one-shot Booking reschedule orchestration, stale/idempotency protection, actor attribution, and bounded Recovery -> Communications lineage with durable Communications reliability semantics.

It does not claim to deliver contextual/cadence-backed reschedule, an F5-owned stop-intake switch, extend-day ScheduleException execution, autonomous replacement selection, or a generalized recovery workflow engine. Their authoritative dispositions are recorded in document 33.

## Final merge gate

Because evidence is exact-head, this ledger cannot make a later commit green retroactively. Before PR #81 is marked ready to merge:

1. run CI on the final branch head;
2. require `PostgreSQL 18 current product proof` success on that head;
3. require the aggregate `PostgreSQL 18 V3 candidate and verticals` success;
4. verify no new unsupported recovery target is exposed as actionable;
5. update this ledger's final-head record only after those results exist.
