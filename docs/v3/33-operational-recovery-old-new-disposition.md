# F5 Operational Recovery old -> new disposition

Status: normative implementation inventory paired with `32-operational-recovery-communications-contract.md`.

F5 composes existing authorities. It does not rename pre-existing concepts into a recovery subsystem.

| Existing surface | Disposition | F5 rule |
| --- | --- | --- |
| F4 `live_capacity` projection | REUSE + EVOLVE PUBLIC CONTRACT | Remains the only live-capacity projection authority. F5 consumes the same assembled F4 projection semantics, including deduplicated Queue/ServiceSession/planned workload, blockers and an opaque source fingerprint. |
| Booking operational availability and ScheduleException truth | REUSE | F5 never queries schedule tables or recalculates effective availability. |
| Booking Reservation / CapacityClaim | REUSE | Booking remains mutation and capacity-consumption authority. F5 stores only Reservation identity/revision provenance. |
| Booking appointment slot planner | REUSE | Recovery alternatives come from Booking's existing availability reader and are revalidated on execution. |
| Booking reschedule command | REUSE + HARDEN LATER | Legacy/non-contextual reschedule is authoritative today. Contextual F1 reschedule remains an explicit unsupported target until Booking closes that pre-existing gap; F5 must not strip assignment provenance to force it through the legacy path. |
| Booking intake capacity enforcement | REUSE / PROVE | A forced closure must already make new Booking consumption fail at the authoritative capacity boundary. F5 adds no UI-only hold or second availability table. |
| F3 queue/service operational state | REUSE INDIRECTLY THROUGH F4 | Recovery does not read QueueEntry/ServiceSession tables directly. F4 assembly incorporates active/queued/planned work with canonical deduplication, and those live inputs participate in F5 materiality and freshness. |
| Platform/Booking idempotency | REUSE | F5 has durable uniqueness for one execution per proposal/Reservation and one actor/idempotency key. Booking receives a stable recovery execution idempotency key and performs the authoritative Reservation transition under its own row/concurrency guards. No PostgreSQL advisory lock is claimed. |
| Communications `CommunicationTask` | REUSE | Communications owns intent/dedupe/scheduling/provider lineage. F5 references the resulting task identity only. |
| Worker leases / ScheduledAction / outbox | REUSE | No recovery-specific worker runtime is introduced. |
| Audit primitives | REUSE | Booking and Communications keep their own audit facts; F5 stores the explicit recovery execution fact and actor. |
| Analytics/reporting operational calculations | DO NOT REUSE AS AUTHORITY | Reporting may consume F5 facts later but cannot independently determine shortfall/affected commitments. |
| Generic workflow engine | DO NOT CREATE | V1 is proposal + one-shot execution, not a long-lived RecoveryWorkflow. |

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
| react when live operations make the plan unrealistic | PARTIAL / CORE DELIVERED | F5 now consumes F4 live workload for materiality and freshness. Automatic event-triggered reprojection/escalation remains future work; current recovery creation is explicit. |
| review affected Reservations after material capacity loss/live pressure | DELIVERED | F4 publishes the authoritative recovery capacity source; F5 persists deterministic affected Reservation provenance in immutable proposals. |
| one-shot Reservation reschedule after explicit selection/revalidation | DELIVERED | F5 orchestrates; Booking remains the only Reservation/capacity mutation authority. |
| contextual/cadence-backed reschedule | UNSUPPORTED / DEFERRED | Booking must first evolve its own reschedule transaction to revalidate contextual assignment/location/commercial provenance. F5 fails closed and must not advertise these targets as actionable. |
| stop new intake from consuming broken capacity | REUSED, NOT AN EXPLICIT F5 ACTION | Existing Booking/capacity authority rejects consumption current schedule/supply no longer permits. A deliberate operator `stop intake` policy beyond natural capacity exhaustion requires a Booking-owned command/contract amendment. |
| extend the day via one-day ScheduleException | DEFERRED | ScheduleException belongs to operational-profile/Booking configuration. F5 does not silently create exceptions. A future recovery action needs an owner-controlled semantic command and explicit authorization/revalidation. |
| find replacement provider/resource options | PARTIAL / DEFERRED | V1 may propose Booking-owned alternatives for the supported local one-shot reschedule path. General contextual/cross-provider replacement requires the missing Booking authority above and is not autonomously selected. |
| communicate impact to affected customers | DELIVERED | A successful explicit recovery execution can create a bounded Communications intent with durable lineage and stable dedupe identity. |
| durable retry, provider-result reconciliation, leases/fencing | DELIVERED BY COMMUNICATIONS | These are Communications-owned reliability semantics reused by F5; F5 does not create a parallel delivery subsystem. |
| event-driven reprojection/escalation on material operational events | DEFERRED | Queue/Delivery changes now invalidate/alter recovery truth when recovery is assessed, but no autonomous trigger loop is claimed by this slice. |
| generalized multi-action recovery workflow | EXPLICIT NON-GOAL FOR V1 | F5 v1 remains immutable proposal + one-shot execution. A long-lived workflow engine requires a new product/contract decision. |

Accordingly, the current branch should be described as the **F5 explicit recovery core slice**, not as proof that the entire original recovery roadmap has been delivered. The deferred rows remain roadmap debt and must be assigned to a subsequent feature before the broader product line can be called complete.

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

F5 introduces exactly two durable concepts:

1. `operational_recovery_proposals`: immutable snapshot/provenance plus the deterministic affected set and proposed Booking targets;
2. `operational_recovery_executions`: one-shot execution fact, idempotent per proposal/Reservation, with optional one-time attachment of the Communications task identity.

No Reservation, capacity, schedule, delivery attempt, or outbox state is copied into a new authority.

## Public contract additions to owning modules

F5 requires narrow owner-controlled ports rather than adapter imports:

- Live Capacity publishes `RecoveryCapacitySource` returning materiality, affected commitments, and an opaque source fingerprint.
- Booking publishes `RecoveryBookingPort` for current Reservation reads, recovery slot suggestions, and delegation to the existing reschedule authority.
- Communications publishes `RecoveryCommunicationPort` for creating a normal transactional `CommunicationTask` with recovery lineage.

These ports belong to the owning modules. Their adapters may use owner-private SQL; `operational_recovery` may not.

## Known pre-existing gap disposition

Contextual F1 appointment options can carry `resource_location_assignment_id`, assignment revision, Location operational revision, commercial terms, and a configuration fingerprint. The existing Booking reschedule path deliberately rejects those options.

F5 does **not** bypass this safeguard. A contextual recovery target is persisted as non-actionable with reason `contextual_reschedule_not_supported`. Closing contextual reschedule correctly requires evolving Booking's own reschedule contract/transaction so it revalidates the same contextual facts as contextual booking. That work is separate from inventing F5 semantics and must be proved at Booking's authority boundary.
