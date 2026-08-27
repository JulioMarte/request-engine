# F5 Operational Recovery and Communications acceptance evidence

Status: evidence ledger for the F5 explicit-recovery core completion gate in `32-operational-recovery-communications-contract.md`.

This document records what has actually been demonstrated. It is intentionally stricter than a feature checklist: a scenario is not marked complete merely because related code exists or because an unrelated aggregate suite is green.

## Evidence baseline

Latest implementation/test head with exact-head CI currently validated before the documentation reconciliation commits:

```text
87284abc38b7e0d7064e8ce78b3b7eafae8d2393
```

Pull request: `#81` (`feature/operational-recovery-communications` -> `development`).

GitHub Actions: CI run `#2572` on the SHA above, completed successfully, including Python quality/architecture and the PostgreSQL 18 current-product and aggregate V3 lanes.

The hardening between the earlier evidence ledger and this SHA added direct invariant coverage for live recovery semantics:

- `tests/modules/live_capacity/test_recovery_affected_selection.py`
- `tests/modules/live_capacity/test_recovery_pressure.py`
- `tests/modules/live_capacity/test_recovery_source_fingerprint.py`

The final documentation descendant still requires its own exact-head CI. A green run for `87284abc...` does not prove a later documentation/code SHA.

## What changed during adversarial closure

The recovery source previously rebuilt F4 with `work_items=()`. That was not valid operational recovery: Queue/ServiceSession pressure could make the day unrealistic while F5 still saw only scheduled Booking commitments. The current implementation now:

1. shares canonical F4 projection assembly with the staff projection;
2. includes deduplicated active/queued/planned live work and blocker state;
3. computes structural scheduled shortfall separately from incremental live pressure;
4. preserves the rule that schedule loss cannot mark a still-fitting Reservation merely to numerically fill a shortfall;
5. lets genuine live pressure deterministically displace latest still-planned commitments;
6. includes live work/progress/blockers in the source fingerprint so operational changes stale old proposals.

The previous documentation also claimed a PostgreSQL advisory recovery-execution lock. No such primitive exists in the implementation. That claim has been removed. The actual protocol is durable F5 uniqueness + stable Booking idempotency + Booking transactional guards + conditional F5 transitions + Communications dedupe/conditional attachment.

## Contract scenario traceability

| Contract scenario / guarantee | Durable proof at validated implementation SHA | Result | Disposition |
| --- | --- | --- | --- |
| A — structural schedule shortfall does not fill affected set with still-executable Reservations | `tests/modules/live_capacity/test_recovery_affected_selection.py` | PASS | Direct regression proof for the bug found during F5 hardening. |
| A — live Queue/ServiceSession pressure participates in recovery materiality | `tests/modules/live_capacity/test_recovery_pressure.py` plus shared `assemble_live_capacity_projection` path | PASS at invariant/component level | Directly proves the materiality formula; the full PostgreSQL 10->6 plus live-overrun narrative is not yet one named F5 E2E. |
| A — live pressure deterministically displaces latest future commitments | `tests/modules/live_capacity/test_recovery_affected_selection.py` | PASS | Direct deterministic policy proof. |
| A/C — live operational changes invalidate recovery freshness | `tests/modules/live_capacity/test_recovery_source_fingerprint.py` | PASS | Fingerprint changes with live service progress and blockers. |
| A — broken current supply cannot accept new intake | existing Booking/F1/F4 PostgreSQL capacity/closure/revalidation proofs | PASS as reused authority | This proves natural Booking enforcement, not a distinct explicit operator stop-intake policy. |
| B — proposal is immutable at the F5 persistence boundary | migration trigger `guard_operational_recovery_proposal` plus bootstrap/current-product migration lanes | PASS at schema level | The schema rejects UPDATE/DELETE and app role has SELECT/INSERT only. A named journey asserting zero Booking/Communications side effects remains desirable. |
| B — contextual targets are not falsely actionable | `tests/modules/operational_recovery/test_recovery_target_policy.py` | PASS | Explicit fail-closed coverage for unsupported contextual reschedule. |
| C — stale source cannot legally reschedule through Booking | F5 source fingerprint/revalidation plus Booking recovery source/revision/target guards exercised by the current product PostgreSQL suite | PASS as composed guard evidence | This is stronger than HTTP-only evidence, but a single named stale F5 journey that inspects Reservation + execution + CommunicationTask + outbox remains an open evidence gap. |
| D — durable duplicate execution identity | migration uniqueness on proposal/Reservation and actor/idempotency identities; stable execution fingerprint/unit coverage | PASS at persistence/contract level | Prevents two logical F5 execution identities for the same proposal/Reservation. |
| D — Booking replay identity is stable | `recovery:{execution_id}:booking:v1` in execution orchestration + Booking idempotent reschedule authority | PASS as composition evidence | A real two-client race remains the required strongest proof of convergence. |
| D — Communications dedupe/attachment identity is stable | execution-derived notification idempotency/dedupe + conditional attachment; existing Communications PostgreSQL durability/worker tests | PASS as composition evidence | A named end-to-end F5 race asserting one task/outbox is still open evidence. |
| Public F5 HTTP surface is classified and capability metadata is frozen | `tests/e2e/http_surface_f5.py` + `tests/e2e/test_public_surface_contract.py` | PASS | Surface/security metadata proof, not recovery semantic acceptance. |

## Evidence gaps that must not be waved through

The following direct PostgreSQL journeys are still stronger than the current distributed evidence and are required before this ledger may describe the explicit F5 core as fully acceptance-proven:

1. **Scenario A journey:** authoritative 10 commitments -> 6 executable, exact four structurally affected identities, plus a separate live-overrun case proving Queue/ServiceSession pressure.
2. **Scenario B journey:** proposal creation with authoritative before/after checks proving zero Reservation mutation, zero RecoveryExecution and zero Communications/outbox intent.
3. **Scenario C journey:** create proposal, advance authoritative source/live truth, execute, observe `STALE_RECOVERY_PROPOSAL`, and inspect zero recovery-caused Reservation/notification/outbox effects.
4. **Scenario D race:** two concurrent identical executions against PostgreSQL, asserting one logical Booking transition, one F5 execution identity, one CommunicationTask/dedupe lineage and correct final Reservation state.

Until those journeys exist, aggregate current-product success is valuable regression evidence but MUST NOT be described as if it were direct scenario C/D acceptance evidence.

## Scope truth at closure

The current F5 core delivers:

- canonical F4-derived recovery materiality including live workload;
- immutable recovery proposals and deterministic affected-Reservation provenance;
- supported one-shot Booking reschedule orchestration;
- stale/idempotency guards and actor attribution;
- bounded Recovery -> Communications lineage with durable owner-controlled reliability semantics.

The broader original roadmap still has explicit future work:

- automatic event-triggered reprojection/escalation;
- explicit operator stop-intake policy beyond natural Booking capacity rejection;
- extend-day ScheduleException recovery execution;
- contextual/cadence-backed and generalized replacement reschedule.

These are not renamed away by calling the current core “F5”. Their authoritative disposition is document 33.

## Final merge gate

PR #81 should remain draft while the four direct PostgreSQL journeys above are absent. Before marking the explicit F5 core ready to merge:

1. add the direct scenario A-D PostgreSQL journeys or explicitly amend the contract/evidence policy through a separate accepted architecture decision rather than silently lowering it;
2. run CI on the final branch head;
3. require `PostgreSQL 18 current product proof` success on that head;
4. require the aggregate `PostgreSQL 18 V3 candidate and verticals` success;
5. verify no unsupported contextual recovery target is exposed as actionable;
6. record the exact final SHA/run here only after those results exist.
