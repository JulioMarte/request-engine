# F5 Operational Recovery old -> new disposition

Status: normative implementation inventory paired with `32-operational-recovery-communications-contract.md`.

F5 composes existing authorities. It does not rename pre-existing concepts into a recovery subsystem.

| Existing surface | Disposition | F5 rule |
| --- | --- | --- |
| F4 `live_capacity` projection | REUSE + EVOLVE PUBLIC CONTRACT | Remains the only live-capacity projection authority. F5 consumes the same assembled F4 projection semantics, including deduplicated Queue/ServiceSession/planned workload, blockers and an opaque source fingerprint. |
| Booking operational availability and ScheduleException truth | REUSE | F5 never queries schedule tables or recalculates effective availability. |
| Booking Reservation / CapacityClaim | REUSE | Booking remains mutation and capacity-consumption authority. F5 stores only Reservation identity/revision provenance. |
| Booking appointment slot planner | REUSE | Recovery alternatives come from Booking's existing availability reader and are revalidated on execution. |
| Booking reschedule command | REUSE + EVOLVED | The pre-existing contextual reschedule gap is now closed by the recovery workflow tranche: Booking revalidates assignment/location/commercial provenance inside its own transaction (contract §10), and F5 contextual targets are actionable without stripping provenance through the legacy path. Evidence: `34-operational-recovery-acceptance-evidence.md`. |
| Booking intake capacity enforcement | REUSE / PROVE | A forced closure must already make new Booking consumption fail at the authoritative capacity boundary. F5 adds no UI-only hold or second availability table. |
| F3 queue/service operational state | REUSE INDIRECTLY THROUGH F4 | Recovery does not read QueueEntry/ServiceSession tables directly. F4 assembly incorporates active/queued/planned work with canonical deduplication, and those live inputs participate in F5 materiality and freshness. |
| Platform/Booking idempotency | REUSE | F5 has durable uniqueness for one execution per proposal/Reservation and one actor/idempotency key. Booking receives a stable recovery execution idempotency key and performs the authoritative Reservation transition under its own row/concurrency guards. No PostgreSQL advisory lock is claimed. |
| Communications `CommunicationTask` | REUSE | Communications owns intent/dedupe/scheduling/provider lineage. F5 references the resulting task identity only. |
| Worker leases / ScheduledAction / outbox | REUSE | No recovery-specific worker runtime is introduced. |
| Audit primitives | REUSE | Booking and Communications keep their own audit facts; F5 stores the explicit recovery execution fact and actor. |
| Analytics/reporting operational calculations | DO NOT REUSE AS AUTHORITY | Reporting may consume F5 facts later but cannot independently determine shortfall/affected commitments. |
| Generic workflow engine | DO NOT CREATE | F5 implements a domain-specific `RecoveryIncident`/`RecoveryAction` workflow with a closed action set (contract §12), not a generic BPM/workflow engine. No generic engine exists or may be introduced. |

## Recovery materiality disposition

F5 uses two distinct forms of pressure and must not collapse them into a count-fill algorithm:

1. **structural scheduled shortfall** — scheduled Booking commitments exceed remaining executable operational time; a Reservation is structurally affected only when its planned commitment no longer fits an authoritative remaining interval;
2. **incremental live pressure** — F4's deduplicated active/queued/planned workload exceeds the remaining day beyond the structural shortfall; this pressure deterministically displaces the latest still-planned commitments first.

This preserves the hardening rule that a Schedule/capacity reduction cannot mark a still-executable Reservation merely to make affected durations add up to the shortfall, while allowing real Queue/ServiceSession overruns and walk-in workload to make later commitments operationally at risk.

The source fingerprint includes every material F4 recovery input used by this decision, including live work identity/duration/progress and open interruption/resource-activity blockers. A proposal therefore becomes stale when the live operational truth on which it was authorized changes.

## Roadmap scope disposition

The roadmap described the broader recovery product direction before the first F5 executable slice was contracted. That broader commitment is preserved here rather than being retroactively declared delivered. The table below is the authoritative old -> new disposition; `deferred` means future product work, not F5 completion by documentation.

| Original roadmap recovery capability | Current F5 slice | Authority / follow-up |
| --- | --- | --- |
| react when live operations make the plan unrealistic | PARTIAL / AUTOMATIC REPROJECTION DELIVERED | F5 consumes F4 live workload for materiality and freshness. Durable scheduled reassessment now opens/updates incidents, persists automatic proposals and evaluates escalation/communication policy under source-revision fencing (contract §5/§13); commitment-change freshness triggers and the delay/impact communication action (proof G) are delivered on this tranche. |
| review affected Reservations after material capacity loss/live pressure | DELIVERED | F4 publishes the authoritative recovery capacity source; F5 persists deterministic affected Reservation provenance in immutable proposals. |
| one-shot Reservation reschedule after explicit selection/revalidation | DELIVERED | F5 orchestrates; Booking remains the only Reservation/capacity mutation authority. |
| contextual/cadence-backed reschedule | DELIVERED | Booking now owns a contextual recovery reschedule authority that revalidates assignment/location/commercial provenance inside one transaction (contract §10). Evidence: contextual reschedule success, action commit and stale fail-closed in `34-operational-recovery-acceptance-evidence.md`. |
| stop new intake from consuming broken capacity | DELIVERED | Queue owns a typed, revisioned intake control and F5 exposes explicit STOP_INTAKE/REOPEN_INTAKE actions gated by recovery source revision (contract §8). Stopped intake transactionally rejects walk-in admission; evidence in `34-operational-recovery-acceptance-evidence.md`. |
| extend the day via one-day ScheduleException | DELIVERED | `EXTEND_DAY` composes Catalog Location additional-hours and Booking Resource/assignment additional-availability exceptions as a durable, partially-visible saga with fresh reprojection before resolution (contract §9). Evidence in `34-operational-recovery-acceptance-evidence.md`. |
| find replacement provider/resource options | DELIVERED (INTRA- + CROSS-ORGANIZATION) | Booking's authoritative contextual slot planner proposes and commits same-time alternate Resources/assignments inside one Organization (contract §11). Cross-Organization replacement is delivered as the two-boundary saga of contract §11: F2 discovery search issues the opaque handoff for one published external option, the provider Organization secures the new commitment through the handoff fence under its own referral principal, and only then is the degraded source commitment disposed; each boundary is idempotent and replay resumes the saga. Evidence in `34-operational-recovery-acceptance-evidence.md`. |
| communicate impact to affected customers | DELIVERED (AUTONOMOUS + EXPLICIT) | A successful explicit recovery execution can create a bounded Communications intent with durable lineage and stable dedupe identity, and the delay/impact communication action (proof G) is delivered with a typed recovery purpose: impact/risk communication is persisted as `operational_recovery_impact`, distinct from the post-reschedule purpose, so the task reason matches what actually happened (contract §13). The accepted autonomous policy additionally delivers the same impact notification under the dedicated system actor when a scheduled assessment commits a customer-impact outcome (contract §14). |
| durable retry, provider-result reconciliation, leases/fencing | DELIVERED BY COMMUNICATIONS | These are Communications-owned reliability semantics reused by F5; F5 does not create a parallel delivery subsystem. |
| event-driven reprojection/escalation on material operational events | PARTIAL / REPROJECTION + POLICY EVALUATION + AUTONOMOUS IMPACT COMMUNICATION DELIVERED | Authoritative source-table triggers durably advance the recovery source revision and schedule one deduped reassessment per revision; the handler commits incidents/proposals and evaluates escalation/communication policy only at current truth (contract §5). The evaluation records a durable immutable escalation outcome per incident and revision; when that outcome requires customer-impact communication, the handler autonomously delivers it under the `operational_recovery_automation` system principal, converging with the explicit COMMUNICATE_IMPACT action on the same dedupe identity. Change-storm coalescing policy is delivered through the shared supersede-enqueue primitive (`10-worker-runtime-hardening.md`). The bounded fallback sweep is delivered (sweep lane, PR #93: a worker stream that repairs lost wake-ups without resuscitating dead/cancelled actions). Autonomous reschedule/extend-day remains a separate requirement needing its own accepted policy and evidence. |
| generalized multi-action recovery workflow | IMPLEMENTED AS DOMAIN-SPECIFIC WORKFLOW | The V1 generic-engine non-goal became a domain-specific `RecoveryIncident`/`RecoveryAction` workflow with a closed action set and per-action owner steps (contract §12). The end-to-end multi-action proof (F) is registered in `34-operational-recovery-acceptance-evidence.md`. |

Accordingly, the delivered F5 state should be described as the **F5 core slice plus the full recovery workflow tranche plus the bounded fallback sweep plus change-storm coalescing plus autonomous customer-impact communication plus cross-Organization replacement**, not as proof that the entire original recovery roadmap has been delivered. The remaining open row — autonomous reschedule/extend-day escalation — remains roadmap debt and must be delivered or explicitly superseded before the broader product line can be called complete.

## Concurrency protocol actually implemented

Concurrent/replayed execution converges through composition of owner-controlled durable mechanisms:

- `operational_recovery_executions` has uniqueness on `(organization_id, proposal_id, reservation_id)` and actor/idempotency identity;
- the selected Booking operation receives the stable key `recovery:{execution_id}:booking:v1`;
- Booking performs the authoritative Reservation mutation under its own transactional row/concurrency guards and source/revision revalidation;
- recovery terminal transitions are conditional (`prepared -> succeeded|rejected`) and idempotently reread the terminal fact;
- Communications receives stable execution-derived idempotency/dedupe identities;
- attachment of the resulting `CommunicationTask` is conditional and accepts only the same task identity on replay.

This is the protocol that must be tested. The repository does **not** currently implement or depend on a PostgreSQL advisory recovery-execution lock, and documentation must not claim one.

## New F5-owned persistence

The slice-1 core introduced two durable concepts:

1. `operational_recovery_proposals`: immutable snapshot/provenance plus the deterministic affected set and proposed Booking targets;
2. `operational_recovery_executions`: one-shot execution fact, idempotent per proposal/Reservation, with optional one-time attachment of the Communications task identity.

The recovery workflow tranche adds:

3. `operational_recovery_incidents`: the durable recovery workflow aggregate with at most one unresolved incident per authoritative recovery scope (contract §4);
4. `operational_recovery_actions`: the closed-set action facts with owner-step state, idempotency identity and failure codes (contract §12);
5. `recovery_source_revisions`: freshness serialization advanced only by owner-controlled source-table triggers (contract §7);
6. `operational_recovery_escalations`: append-only escalation/communication policy outcomes, one immutable fact per incident and source revision (contract §5.6/§13).

Escalation policy has a single evaluation authority: the scheduled reassessment handler, whose outcome is recorded in the same transaction as incident truth. Action-driven reprojection after owner mutations advances incident truth without recording an escalation outcome; the material source changes those actions cause schedule a fresh deduped reassessment, which records the outcome for the new revision.

`service_queue_intake_controls` is the Queue-owned typed intake policy surface required by contract §8; F5 references it through the owner contract rather than owning it.

No Reservation, capacity, schedule, delivery attempt, or outbox state is copied into a new authority.

## Public contract additions to owning modules

F5 requires narrow owner-controlled ports rather than adapter imports:

- Live Capacity publishes `RecoveryCapacitySource` returning materiality, affected commitments, and an opaque source fingerprint.
- Booking publishes `RecoveryBookingPort` for current Reservation reads, recovery slot suggestions, and delegation to the existing reschedule authority.
- Communications publishes `RecoveryCommunicationPort` for creating a normal transactional `CommunicationTask` with recovery lineage and a typed recovery purpose (`operational_recovery_impact` for delay/impact, `operational_recovery_rescheduled` for post-reschedule confirmation).

These ports belong to the owning modules. Their adapters may use owner-private SQL; `operational_recovery` may not.

## Closed pre-existing gap disposition

Contextual F1 appointment options carry `resource_location_assignment_id`, assignment revision, Location operational revision, commercial terms, and a configuration fingerprint. The original slice-1 Booking reschedule path deliberately rejected those options, and slice-1 F5 persisted contextual targets as non-actionable with reason `contextual_reschedule_not_supported`.

That pre-existing gap is now closed by the recovery workflow tranche: Booking evolved its own reschedule contract/transaction to revalidate the same contextual facts as contextual booking (contract §10), and contextual recovery targets are actionable without bypassing the safeguard. The stale reason code above is historical to slice-1; contextual staleness is now proven fail-closed at Booking's authority boundary in `34-operational-recovery-acceptance-evidence.md`.
