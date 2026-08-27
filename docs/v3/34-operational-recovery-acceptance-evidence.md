# F5 Operational Recovery and Communications acceptance evidence

Status: evidence ledger for the F5 explicit-recovery core completion gate in `32-operational-recovery-communications-contract.md`.

This document records what has actually been demonstrated. It is intentionally stricter than a feature checklist: a scenario is not marked complete merely because related code exists or because an unrelated aggregate suite is green.

## Validated implementation and acceptance baseline

The implementation/test tree carrying the complete direct PostgreSQL A-D acceptance journeys is:

```text
51e8b32815b1600d881fc5004acb7b6f1d8ab8be
```

Pull request: `#81` (`feature/operational-recovery-communications` -> `development`).

GitHub Actions run `33099372037`, CI `#2595`, completed the feature's code-bearing acceptance baseline successfully. The same SHA passed:

- `Python quality and architecture`;
- `PostgreSQL 18 current product proof`;
- `PostgreSQL 18 V3 repeated bootstrap proof`;
- `PostgreSQL 18 frozen V3 compatibility`;
- `PostgreSQL 18 V2 design history`;
- `Observability runtime contract`;
- aggregate `PostgreSQL 18 V3 candidate and verticals`.

The ledger itself is a documentation descendant of that validated code-bearing SHA. The authoritative merge-time exact-head condition is the GitHub required-check state on the actual PR head; recording a run inside this file must not create an infinite self-referential commit loop.

## What changed during adversarial closure

The recovery source previously rebuilt F4 with `work_items=()`. That was not valid operational recovery: Queue/ServiceSession pressure could make the day unrealistic while F5 still saw only scheduled Booking commitments. The hardened implementation now:

1. shares canonical F4 projection assembly with the staff projection;
2. includes deduplicated active/queued/planned live work and blocker state;
3. computes structural scheduled shortfall separately from incremental live pressure;
4. preserves the rule that schedule loss cannot mark a still-fitting Reservation merely to numerically fill a shortfall;
5. lets genuine live pressure deterministically displace latest still-planned commitments;
6. includes live work/progress/blockers in the source fingerprint so operational changes stale old proposals.

The previous documentation also claimed a PostgreSQL advisory recovery-execution lock. No such primitive exists in the implementation. The actual convergence protocol is durable F5 uniqueness + stable Booking idempotency + Booking transactional guards + conditional F5 transitions + Communications dedupe/conditional attachment.

## Direct contract scenario traceability

| Contract scenario / guarantee | Durable proof | Result | What is observed |
| --- | --- | --- | --- |
| A — 10 valid commitments reduced to 6 executable select the exact deterministic four | `tests/e2e/test_f5_recovery_materiality.py::test_f5_ten_commitments_reduced_to_six_selects_exact_last_four_and_blocks_intake` | PASS | PostgreSQL-backed 3000s committed, 1800s executable, 1200s shortfall, exact last four Reservation identities/revisions, and broken intake cannot add an eleventh confirmed Reservation. |
| A — live Queue pressure participates in materiality and expands the affected set | `tests/e2e/test_f5_recovery_live_pressure.py::test_f5_live_walk_in_pressure_expands_shortfall_and_affected_set` | PASS | Starts from the structural 1200s shortfall, inserts an authoritative walk-in carrying a 1200s estimate, observes a changed source fingerprint, 2400s material shortfall and deterministic expansion from four to eight affected Reservations. |
| A — structural loss does not numerically fill affected set with still-executable Reservations | `tests/modules/live_capacity/test_recovery_affected_selection.py` | PASS | Direct regression proof for the bug found during F5 hardening. |
| A/C — live operational changes participate in freshness | `tests/modules/live_capacity/test_recovery_source_fingerprint.py` plus the live-pressure/stale PostgreSQL journeys | PASS | Fingerprint changes with material live state and an old proposal is rejected rather than silently refreshed. |
| B — proposal creation is read-only | `tests/e2e/test_f5_recovery_materiality.py::test_f5_proposal_is_read_only_and_uses_booking_generated_replacement_target` | PASS | Authoritative Reservation rows are identical before/after proposal creation; RecoveryExecution, CommunicationTask and outbox counts do not change; returned actionable targets come from Booking authority. |
| B — persisted proposal is immutable | migration trigger `guard_operational_recovery_proposal` plus migration/bootstrap lanes | PASS | UPDATE/DELETE are rejected by schema authority; app role receives SELECT/INSERT only. |
| B — unsupported contextual reschedule is fail-closed | `tests/modules/operational_recovery/test_recovery_target_policy.py` | PASS | Contextual source/target states are not falsely exposed as actionable through the legacy reschedule path. |
| C — stale proposal fails closed with no recovery-caused Booking/Communications side effects | `tests/e2e/test_f5_recovery_stale.py::test_f5_live_change_stales_proposal_without_booking_or_notification_side_effects` | PASS | After proposal creation, authoritative live truth advances. Execution returns `STALE_RECOVERY_PROPOSAL`/409, Reservation state remains unchanged, the one F5 execution fact is terminal `rejected`, and no CommunicationTask/outbox is created by recovery. |
| D — identical concurrent execution and replay converge | `tests/e2e/test_f5_recovery_concurrency.py::test_f5_identical_concurrent_execution_converges_on_one_booking_and_communication` | PASS | Two independent clients race the same idempotent command and an exact replay follows; all resolve to one execution identity, Reservation revision advances exactly once, actor/original/result revisions are preserved, one Communications lineage exists and exactly one task-created outbox record is present. |
| Public F5 HTTP surface/capability metadata remains classified | `tests/e2e/http_surface_f5.py` + `tests/e2e/test_public_surface_contract.py` | PASS | Prevents silent public-surface growth and verifies capability/idempotency metadata independently of semantic acceptance. |

## Concurrency interpretation

Scenario D does not depend on a process-local mutex or a fictitious F5 advisory lock. The tested protocol is compositional:

```text
F5 durable execution uniqueness
        +
stable execution identity
        -> Booking idempotency recovery:{execution_id}:booking:v1
        -> Booking transactional source/revision/target guards
        -> conditional F5 terminal transition
        -> stable Communications idempotency/dedupe
        -> conditional one-time CommunicationTask attachment
```

The PostgreSQL race is the falsifiable proof that this composition converges for the supported one-shot command. If any owning boundary changes its concurrency semantics, Scenario D must remain green or the composition is no longer proven.

## Scope truth at closure

The explicit F5 recovery core delivers:

- canonical F4-derived recovery materiality including live workload;
- immutable recovery proposals and deterministic affected-Reservation provenance;
- supported one-shot Booking reschedule orchestration;
- stale/idempotency guards and actor attribution;
- bounded Recovery -> Communications lineage with durable owner-controlled reliability semantics;
- direct PostgreSQL acceptance evidence for scenarios A-D.

The broader original roadmap still has explicit future work:

- automatic event-triggered reprojection/escalation;
- explicit operator stop-intake policy beyond natural Booking capacity rejection;
- extend-day ScheduleException recovery execution;
- contextual/cadence-backed and generalized replacement reschedule.

These are not renamed away by calling the current core “F5”. Their authoritative disposition is document 33.

## Final merge gate

The semantic/evidence gaps that previously required PR #81 to remain draft are now closed for the contracted F5 v1 core. Before merge, the actual PR head must still satisfy repository policy:

1. required GitHub checks green on the current head;
2. `PostgreSQL 18 current product proof` green;
3. aggregate `PostgreSQL 18 V3 candidate and verticals` green;
4. no unsupported contextual recovery target exposed as actionable;
5. no unresolved review/branch-protection requirement.

The code-bearing acceptance baseline above is historical provenance; GitHub's required checks on the actual PR head are the authoritative exact-head merge gate.