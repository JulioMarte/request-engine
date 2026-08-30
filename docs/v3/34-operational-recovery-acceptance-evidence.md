# F5 Operational Recovery and Communications acceptance evidence

Status: evidence ledger for the F5 completion gate in `32-operational-recovery-communications-contract.md`. Slice-1 evidence was demonstrated at the PR #81 baseline; current-tranche evidence is registered from `feature/f5-roadmap-authoritative-recovery`.

This document records what has actually been demonstrated. It is intentionally stricter than a feature checklist: a scenario is not marked complete merely because related code exists or because an unrelated aggregate suite is green.

## Validated implementation and acceptance baseline

The implementation/test tree carrying the complete direct PostgreSQL A-D journeys plus the final FORCE-RLS/SECURITY-DEFINER tenant-isolation hardening is:

```text
81019f88cb03a02a061e48d327123cb9a2fc9f0e
```

Pull request: `#81` (`feature/operational-recovery-communications` -> `development`).

GitHub Actions run `33109778886`, CI `#2610`, completed that code-bearing baseline successfully. The same SHA passed:

- `Python quality and architecture`;
- `PostgreSQL 18 current product proof`;
- `PostgreSQL 18 V3 repeated bootstrap proof`;
- `PostgreSQL 18 frozen V3 compatibility`;
- `PostgreSQL 18 V2 design history`;
- `Observability runtime contract`;
- aggregate `PostgreSQL 18 V3 candidate and verticals`.

Earlier A-D acceptance provenance remains available at `51e8b32815b1600d881fc5004acb7b6f1d8ab8be`, CI `#2595` / Actions run `33099372037`. The later baseline supersedes it for merge-time code evidence because it includes the freshness serialization and RLS hardening found during adversarial closure.

The ledger itself is a documentation descendant of the validated code-bearing SHA. The authoritative merge-time exact-head condition is the GitHub required-check state on the actual PR head; recording a run inside this file must not create an infinite self-referential commit loop.

## What changed during adversarial closure

The recovery source previously rebuilt F4 with `work_items=()`. That was not valid operational recovery: Queue/ServiceSession pressure could make the day unrealistic while F5 still saw only scheduled Booking commitments. The hardened implementation now:

1. shares canonical F4 projection assembly with the staff projection;
2. includes deduplicated active/queued/planned live work and blocker state;
3. computes structural scheduled shortfall separately from incremental live pressure;
4. preserves the rule that schedule loss cannot mark a still-fitting Reservation merely to numerically fill a shortfall;
5. lets genuine live pressure deterministically displace latest still-planned commitments;
6. includes live work/progress/blockers in the source fingerprint so operational changes stale old proposals.

Freshness serialization added another defect during closure. `recovery_source_revisions` correctly used `FORCE ROW LEVEL SECURITY`, but the first internal-writer correction granted the schema owner an unconditional `FOR ALL ... USING (true)` policy. Because the public recovery revision read/lock functions are `SECURITY DEFINER` functions owned by that same role, an unconditional owner policy would also have allowed those functions to see or lock a revision row for a caller-supplied foreign tenant. The final policy is deliberately narrower: schema-owner access is admitted only while an owner-controlled source-table trigger is executing (`pg_trigger_depth() > 0`). A direct PostgreSQL runtime-role test now proves own-tenant read remains available while cross-tenant `SECURITY DEFINER` read/lock paths remain RLS-filtered/fail-closed.

The previous documentation also claimed a PostgreSQL advisory recovery-execution lock. No such primitive exists in the implementation. The actual convergence protocol is durable F5 uniqueness + stable Booking idempotency + Booking transactional guards + conditional F5 transitions + Communications dedupe/conditional attachment.

## Direct contract scenario traceability

| Contract scenario / guarantee | Durable proof | Result | What is observed |
| --- | --- | --- | --- |
| A — 10 valid commitments reduced to 6 executable select the exact deterministic four | `tests/e2e/test_f5_recovery_materiality.py::test_f5_ten_commitments_reduced_to_six_selects_exact_last_four_and_blocks_intake` | PASS | PostgreSQL-backed 3000s committed, 1800s executable, 1200s shortfall, exact last four Reservation identities/revisions, and broken intake cannot add an eleventh confirmed Reservation. |
| A — live Queue pressure participates in materiality without fabricating affected Reservations | `tests/e2e/test_f5_recovery_live_pressure.py::test_f5_live_pressure_changes_risk_without_fabricating_more_affected_reservations` + `test_f5_live_only_pressure_persists_risk_only_proposal_with_no_affected_reservations` | PASS | An authoritative walk-in moves the material shortfall from 1200s to 2400s and changes the source fingerprint while the affected set stays exactly the structurally affected Reservations; a live-only shortfall persists a risk-only proposal with zero affected Reservations (contract §6). |
| A — structural loss does not numerically fill affected set with still-executable Reservations | `tests/modules/live_capacity/test_recovery_affected_selection.py` | PASS | Direct regression proof for the bug found during F5 hardening. |
| A/C — live operational changes participate in freshness | `tests/modules/live_capacity/test_recovery_source_fingerprint.py` plus the live-pressure/stale PostgreSQL journeys | PASS | Fingerprint changes with material live state and an old proposal is rejected rather than silently refreshed. |
| Freshness writer preserves tenant isolation under FORCE RLS | `tests/e2e/test_f5_recovery_source_security.py::test_f5_recovery_source_security_definer_paths_remain_tenant_scoped` | PASS | An app runtime bound to tenant A can read A's revision, cannot read tenant B's revision through the `SECURITY DEFINER` read function, and cannot lock B's revision through the command function; admin inspection proves both rows actually exist. Source-table triggers still advance revisions under the same migration and current-product proof. |
| B — proposal creation is read-only | `tests/e2e/test_f5_recovery_materiality.py::test_f5_proposal_is_read_only_and_uses_booking_generated_replacement_target` | PASS | Authoritative Reservation rows are identical before/after proposal creation; RecoveryExecution, CommunicationTask and outbox counts do not change; returned actionable targets come from Booking authority. |
| B — persisted proposal is immutable | migration trigger `guard_operational_recovery_proposal` plus migration/bootstrap lanes | PASS | UPDATE/DELETE are rejected by schema authority; app role receives SELECT/INSERT only. |
| B (module) — legacy reschedule path never exposes contextual targets as actionable | `tests/modules/operational_recovery/test_recovery_target_policy.py` | PASS | A legacy source skips contextual targets for legacy slots, a contextual source selects a contextual target, a contextual source with only a legacy target fails closed, and the execution replay fingerprint is bound to actor and idempotency key. |
| C — stale proposal fails closed with no recovery-caused Booking/Communications side effects | `tests/e2e/test_f5_recovery_stale.py::test_f5_live_truth_change_rejects_stale_proposal_without_booking_or_notification` | PASS | After proposal creation, authoritative live truth advances. Execution returns `STALE_RECOVERY_PROPOSAL`/409, Reservation state remains unchanged, the one F5 execution fact is terminal `rejected`, and no CommunicationTask/outbox is created by recovery. |
| D — identical concurrent execution and replay converge | `tests/e2e/test_f5_recovery_concurrency.py::test_f5_identical_concurrent_execution_converges_on_one_booking_and_communication` | PASS | Two independent clients race the same idempotent command and an exact replay follows; all resolve to one execution identity, Reservation revision advances exactly once, actor/original/result revisions are preserved, one Communications lineage exists and exactly one task-created outbox record is present. |
| Public F5 HTTP surface/capability metadata remains classified | `tests/e2e/http_surface_f5.py` + `tests/e2e/test_public_surface_contract.py` | PASS | Prevents silent public-surface growth and verifies capability/idempotency metadata independently of semantic acceptance. |
| B — explicit stop/reopen intake is transactional, idempotent and conflicting-payload-safe | `tests/e2e/test_f5_recovery_intake_control.py::test_f5_stop_and_reopen_intake_is_transactional_and_idempotent` | PASS | With remaining theoretical capacity, STOP_INTAKE under a recovery source revision flips Queue-owned intake to stopped (revision 2); replay returns the same action identity, a different payload under the same idempotency key is 409, walk-in check-in fails with `queue_intake_stopped` and zero QueueEntry creation, and REOPEN_INTAKE restores admission (revision 3). |
| B (module) — intake action orchestration is idempotent and stale-safe | `tests/modules/operational_recovery/test_workflow_intake_action.py` | PASS | Owner delegation with stable identity, terminal replay does not call the owner twice, response-loss retry reuses the same expected revision, and a stale action rejects before any owner mutation. |
| C — extend-day clears a closing-time shortfall without rewriting recurring schedules | `tests/e2e/test_f5_recovery_extend_day_success.py::test_f5_extend_day_clears_closing_shortfall_without_rewriting_recurring_schedules` | PASS | One-day Location additional-hours plus assignment additional-availability exceptions are created, the fresh reassessment reports zero scheduled shortfall with the incident `resolved`, and the recurring schedule snapshot is unchanged. |
| C — extend-day partial saga is visible and idempotent under a stale second step | `tests/e2e/test_f5_recovery_extend_day_atomicity.py::test_f5_extend_day_stale_second_step_is_visible_and_idempotent` | PASS | After Booking availability advances post-authorization, both attempts return 409, the action stays `partially_applied` with the Catalog owner step committed, exactly one Location exception exists, no assignment exception is created, and owner revisions advanced only by the committed step. |
| C (module) — extend-day orchestration covers both owners, retry and stale rejection | `tests/modules/operational_recovery/test_workflow_schedule_action.py` | PASS | Both owner steps run with reprojection/resolution, retry preserves the partial owner step and identity, and a stale authorization rejects before owner mutation. |
| D — contextual reschedule preserves assignment and commercial provenance | `tests/e2e/test_f5_recovery_contextual_reschedule.py::test_f5_contextual_reschedule_preserves_assignment_and_commercial_commitment` | PASS | The actionable contextual target keeps the same `resource_location_assignment_id`, the active capacity claim moves to that assignment, and the commercial commitment (amount/currency/duration/fingerprint) is unchanged. |
| D — contextual reschedule action commits the authorized target idempotently | `tests/e2e/test_f5_recovery_contextual_reschedule_action.py::test_f5_contextual_reschedule_action_commits_authorized_target` | PASS | The incident reschedule action succeeds and replays to the same action identity; Reservation revision advances exactly once, planned times move to the authorized target, the commercial commitment is preserved and the target claim is active. |
| D — contextual proposal fails closed after material configuration change | `tests/e2e/test_f5_recovery_contextual_stale.py::test_f5_contextual_proposal_fails_closed_after_material_configuration_change` | PASS | Parametrized price, Location-hours and assignment-schedule changes after authorization each yield 409 with zero Reservation state change. |
| D (module) — reschedule orchestration replays across incident truth advance | `tests/modules/operational_recovery/test_workflow_reschedule_action.py` | PASS | Stable Booking identity with reprojection, and retry replay after incident truth advances. |
| E — replacement target policy keeps time, changes resource and fails closed across context boundary | `tests/modules/operational_recovery/test_replacement_target_policy.py` | PASS | Replacement keeps the time and swaps the degraded Resource, never relabels a reschedule as replacement, and fails closed across a context boundary. |
| E — contextual replacement commits an alternate Resource with time and commercial truth preserved | `tests/e2e/test_f5_recovery_contextual_replace_resource.py::test_f5_contextual_replace_resource_preserves_time_and_commercial_truth` | PASS | The proposal exposes a same-time alternate Resource/assignment replacement target; the action succeeds and replays idempotently, the active claim moves to the alternate assignment, and the interval plus commercial commitment are unchanged. |
| E (module) — replace-resource orchestration resumes after source revision advance | `tests/modules/operational_recovery/test_workflow_replace_resource_action.py` | PASS | Same-time alternate target with reprojection, and retry resume after the source revision advances. |
| A — scheduled reassessment persists current material truth and replays idempotently | `tests/e2e/test_f5_scheduled_reassessment.py::test_f5_scheduled_reassessment_persists_and_replays_current_material_truth` | PASS | The leased handler opens one incident at the current source revision and persists exactly one automatic proposal created by no human principal; replay is a no-op returning the same proposal identity with incident/proposal state unchanged. |
| A — scheduled reassessment cannot commit superseded truth | `tests/e2e/test_f5_scheduled_reassessment.py::test_f5_scheduled_reassessment_cannot_commit_superseded_truth` | PASS | After an authoritative Location-hours change advances the source revision, committing the stale assessment is fenced (`applied=false, stale=true`) with no incident and no automatic proposal. |
| A (module) — assessment classification and fresh-only resolution | `tests/modules/operational_recovery/test_workflow_assessment.py` | PASS | Indeterminate projection is material, live-only shortfall is delay and not structural shortfall, healthy scope without incident is a no-op, and an existing incident resolves only from a fresh healthy assessment. |
| Freshness triggers — schedule/assignment source changes advance revisions and schedule one deduped reassessment | `tests/e2e/test_f5_recovery_schedule_source_freshness.py::test_f1_schedule_changes_advance_and_schedule_f5_source_once` | PASS | A Location-hours exception and a ResourceLocationAssignment schedule exception each advance the recovery source revision exactly once and schedule exactly one `reassess_recovery_scope` action per revision. |

The queue/session/interruption/activity and projection/estimate-policy freshness roots are the same `bump_recovery_source_revision` mechanics introduced by migration `0009_f5_recovery_source_freshness` (extended by `0012_f5_schedule_source_freshness` for Location operational revision and Resource availability revision, and by `0015_f5_commitment_freshness` for Booking commitment changes). The walk-in journey in `tests/e2e/test_f5_recovery_live_pressure.py` proves the `queue_entries` root end-to-end through a changed source fingerprint; the Location/assignment roots are proven directly above.

## Current-tranche closure proofs

The following required proofs were produced on this tranche and are registered here:

| Guarantee | Proof | Status | Contract meaning |
| --- | --- | --- | --- |
| Delay/impact communication (15 G) | `tests/e2e/test_f5_recovery_delay_communication.py`; handler semantics `tests/modules/operational_recovery/test_workflow_communication_action.py` | PASS | A material delay with no capacity shortfall opens the incident through the real scheduled handler, executes COMMUNICATE_IMPACT, and creates exactly one deduped Communications-owned customer-impact task per (incident, recipient, purpose, source revision); replay and different-key retries converge on the same durable task without rescheduling the Reservation. The persisted purpose is the typed `operational_recovery_impact` (delay/impact), never the post-reschedule purpose, because no Reservation was rescheduled. |
| Multi-action workflow (15 F) | `tests/e2e/test_f5_recovery_multi_action_workflow.py` | PASS | One incident executes STOP_INTAKE then EXTEND_DAY through the real HTTP surface with a fresh reprojection between actions; stale authorization is rejected with conflict semantics; same-key races and replays converge without duplicate owner mutations; intake stays stopped after resolution until an explicit reopen. |
| Workflow-table RLS/least privilege (15 H) | `tests/db/test_f5_workflow_rls_isolation.py` | PASS | `operational_recovery_incidents/actions/proposals` are FORCE-RLS tenant-isolated even for the table owner; the app role has exactly SELECT/INSERT/UPDATE and the worker role none; the recovery bump fence is not executable by runtime roles. |
| Commitment-change freshness (5) | `tests/db/test_f5_commitment_freshness.py` | PASS | CapacityClaim/Reservation changes that enter, move or leave the assessed scope advance the recovery source revision once per material row change and enqueue exactly one deduped reassessment per revision; off-scope commitments change nothing. |
| Bump fence tenant authority (15 H) + intake reprojection (12) | `tests/db/test_f5_bump_guard_intake_freshness.py` | PASS | The SECURITY DEFINER bump rejects a session whose tenant context differs from the requested organization (migration `0016_f5_bump_guard_freshness`), and a Queue intake-control mutation durably schedules one deduped fresh reprojection per material change while no-op updates schedule nothing. |
| Scheduled escalation/communication policy evaluation (5.6/13) | `tests/e2e/test_f5_recovery_escalation_policy.py`; policy matrix `tests/modules/operational_recovery/test_recovery_escalation_policy.py` | PASS | The real scheduled handler evaluates escalation/communication policy in the same transaction that commits incident truth and records an immutable outcome per incident and source revision: a newly material incident requires operator escalation and requests customer-impact notification exactly for affected commitment subjects; replay is a no-op; a superseded revision records nothing; a delay that worsens into a capacity shortfall re-escalates with `worsening_severity` and now identifies recipients; a fresh resolving assessment records a cleared outcome. |
| Escalation-fact immutability and tenant isolation (15 H) | `tests/db/test_f5_escalation_rls_isolation.py` | PASS | `operational_recovery_escalations` is append-only (guard trigger rejects UPDATE/DELETE with `23514`), FORCE-RLS tenant-isolated for the app role, cross-tenant escalation inserts fail closed, and the worker role has no access. |
| Escalation ledger closure after operator action (5.6/13) | `tests/e2e/test_f5_recovery_escalation_ledger.py` | PASS | An operator EXTEND_DAY resolution advances incident truth without recording an escalation outcome; the material source change the action causes schedules exactly one deduped reassessment, whose healthy assessment records the cleared outcome for the new revision exactly once (append-only, replay is a no-op) without creating recovery actions, communication tasks or outbox rows. |
| Change-storm coalescing (5) | `tests/db/test_f5_reassessment_coalescing.py` | PASS | The shared supersede-enqueue primitive is the single enqueue path for the freshness bump trigger and the bounded sweep: a real 50-bump trigger storm leaves exactly one pending reassessment at the maximum revision with all older pendings cancelled, two concurrent connections bumping the same scope converge deterministically to one survivor, and the sweep repairs a lost wake-up through the same primitive without resurrecting cancelled actions. |
| Autonomous customer-impact communication (13/14) | `tests/e2e/test_f5_recovery_autonomous_impact.py`; policy facts `tests/e2e/test_f5_recovery_escalation_policy.py` | PASS | The scheduled handler, after committing a customer-impact outcome, autonomously delivers exactly one impact CommunicationTask per affected recipient under the `operational_recovery_automation` service principal (idempotency-record attribution), creates no recovery actions, replays without duplicates, and the explicit operator `COMMUNICATE_IMPACT` action for the same incident/recipient/revision converges on the same task through the section 13 dedupe identity. Healthy/worsening/clearing policy worlds keep recovery actions at zero and create communication tasks only for customer-impact outcomes. |
| Cross-Organization replacement saga (11) | `tests/e2e/test_f5_recovery_cross_organization_replacement.py` | PASS | With one Organization's material incident and no internal replacement target, the operator selects one published external option through the real F2 discovery search: a stale/bogus handoff fails closed (action rejected `EXTERNAL_COMMIT_FAILED`, source commitment untouched), a valid handoff first secures the new commitment in the provider Organization (handoff consumed once, provider subject, published commercial terms, active provider claim) and only then disposes the degraded source commitment (cancelled, no active claims), and replaying the same idempotency key returns the same action with no duplicate external commitment or disposal. |

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

The F5 core slice plus the current recovery workflow tranche deliver (with evidence registered above):

- canonical F4-derived recovery materiality including live workload;
- immutable recovery proposals and deterministic affected-Reservation provenance;
- supported one-shot Booking reschedule orchestration;
- stale/idempotency guards and actor attribution;
- FORCE-RLS-safe recovery freshness serialization without widening cross-tenant runtime authority;
- bounded Recovery -> Communications lineage with durable owner-controlled reliability semantics;
- explicit stop/reopen intake through the Queue-owned typed intake control;
- the extend-day two-owner saga with visible partial state and fresh reprojection before resolution;
- contextual provenance-preserving reschedule with stale fail-closed semantics;
- intra-Organization replacement target policy and contextual replacement;
- scheduled reassessment with source-revision fencing, incident upsert and deduped automatic proposals;
- scheduled escalation/communication policy evaluation with durable immutable outcome facts per incident and source revision (contract §5.6/§13);
- schedule/assignment freshness triggers with one deduped reassessment action per source revision;
- direct PostgreSQL acceptance evidence for scenarios A-E plus the freshness/security rows above.

The broader original roadmap still has explicit open work:

- cross-Organization provider replacement — delivered through the two-boundary discovery handoff saga: `tests/e2e/test_f5_recovery_cross_organization_replacement.py` proves the fail-closed stale-handoff rejection, external-commit-first sequencing, source disposal and replay convergence;
- change-storm coalescing — delivered through the shared supersede-enqueue primitive: `tests/db/test_f5_reassessment_coalescing.py` proves one pending reassessment survives a real trigger storm, deterministic two-connection convergence, and sweep repair without resurrection;
- bounded fallback sweep — delivered (sweep lane, PR #93): `tests/db/test_f5_recovery_sweep.py` proves a lost wake-up is repaired with the exact trigger identity and processed by the real handler, live actions are a clean no-op, dead/cancelled actions are never resurrected, discovery is a worker-only cross-tenant surface over scheduled actions, and repair composition converges to one action per revision;
- autonomous reschedule/extend-day escalation (requires a later accepted policy and operator-visible authority grant).

These are not renamed away by calling the current tranche “F5”. Their authoritative disposition is document 33. The proofs F, G, H and commitment-change triggers that earlier revisions of this ledger listed as in flight are registered above as PASS; the open items above remain the F5 completion debt.

## Final merge gate

The semantic/evidence gaps that previously required PR #81 to remain draft are now closed for the contracted F5 v1 core. Before merge, the actual PR head must still satisfy repository policy:

1. required GitHub checks green on the current head;
2. `PostgreSQL 18 current product proof` green;
3. aggregate `PostgreSQL 18 V3 candidate and verticals` green;
4. no unsupported contextual recovery target exposed as actionable;
5. no unresolved review/branch-protection requirement.

The code-bearing acceptance baseline above is historical provenance; GitHub's required checks on the actual PR head are the authoritative exact-head merge gate. The recovery workflow tranche (`feature/f5-roadmap-authoritative-recovery`, PR #83) and the bounded fallback sweep (`feature/f5-recovery-fallback-sweep`, PR #93) satisfied that gate at their merges; future rows registered here become merge evidence only when their PR head's required checks are green.
