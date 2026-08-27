# F5 Operational Recovery old -> new disposition

Status: normative implementation inventory paired with `32-operational-recovery-communications-contract.md`.

F5 composes existing authorities. It does not rename pre-existing concepts into a recovery subsystem.

| Existing surface | Disposition | F5 rule |
| --- | --- | --- |
| F4 `live_capacity` projection | REUSE + EVOLVE PUBLIC CONTRACT | Remains the only live-capacity projection authority. F5 consumes a narrow recovery assessment contract and opaque source fingerprint. |
| Booking operational availability and ScheduleException truth | REUSE | F5 never queries schedule tables or recalculates effective availability. |
| Booking Reservation / CapacityClaim | REUSE | Booking remains mutation and capacity-consumption authority. F5 stores only Reservation identity/revision provenance. |
| Booking appointment slot planner | REUSE | Recovery alternatives come from Booking's existing availability reader and are revalidated on execution. |
| Booking reschedule command | REUSE + HARDEN LATER | Legacy/non-contextual reschedule is authoritative today. Contextual F1 reschedule remains an explicit unsupported target until Booking closes that pre-existing gap; F5 must not strip assignment provenance to force it through the legacy path. |
| Booking intake capacity enforcement | REUSE / PROVE | A forced closure must already make new Booking consumption fail at the authoritative capacity boundary. F5 adds no UI-only hold or second availability table. |
| F3 queue/service operational state | REUSE INDIRECTLY THROUGH F4 | Recovery does not read QueueEntry/ServiceSession tables directly. |
| Platform idempotency | REUSE | Existing command idempotency remains available to owning modules. F5 additionally serializes one execution per proposal/Reservation with durable uniqueness and a PostgreSQL advisory execution lock. |
| Communications `CommunicationTask` | REUSE | Communications owns intent/dedupe/scheduling/provider lineage. F5 references the resulting task identity only. |
| Worker leases / ScheduledAction / outbox | REUSE | No recovery-specific worker runtime is introduced. |
| Audit primitives | REUSE | Booking and Communications keep their own audit facts; F5 stores the explicit recovery execution fact and actor. |
| Analytics/reporting operational calculations | DO NOT REUSE AS AUTHORITY | Reporting may consume F5 facts later but cannot independently determine shortfall/affected commitments. |
| Generic workflow engine | DO NOT CREATE | V1 is proposal + one-shot execution, not a long-lived RecoveryWorkflow. |

## Roadmap scope disposition

The roadmap intentionally described the broader recovery product direction. Contract 32 narrows the first executable F5 slice. The following table is the authoritative disposition of that delta; `deferred` does not mean silently delivered by F5.

| Roadmap recovery capability | F5 v1 disposition | Authority / follow-up |
| --- | --- | --- |
| review affected Reservations after material capacity loss | DELIVERED | F4 publishes the authoritative recovery capacity source; F5 persists deterministic affected Reservation provenance in immutable proposals. |
| one-shot Reservation reschedule after explicit selection/revalidation | DELIVERED | F5 orchestrates; Booking remains the only Reservation/capacity mutation authority. |
| contextual/cadence-backed reschedule | UNSUPPORTED / DEFERRED | Booking must first evolve its own reschedule transaction to revalidate contextual assignment/location/commercial provenance. F5 fails closed and must not advertise these targets as actionable. |
| stop new intake from consuming broken capacity | REUSED / PROVED, NOT F5-OWNED | Existing Booking/capacity authority must reject consumption that current schedule/supply no longer permits. F5 introduces no second intake switch. |
| extend the day via one-day ScheduleException | DEFERRED | ScheduleException already belongs to Booking/operational-profile configuration. F5 v1 does not expose an extend-day recovery action or silently create exceptions. A future recovery composition capability requires a contract amendment and explicit authorization semantics. |
| find replacement provider/resource options | PARTIAL / DEFERRED | V1 may propose Booking-owned alternatives for the supported one-shot reschedule path. It is not a generalized replacement/remediation workflow and does not autonomously select a replacement provider. |
| communicate impact to affected customers | DELIVERED | A successful explicit recovery execution can create a bounded Communications intent with durable lineage and stable dedupe identity. |
| durable retry, provider-result reconciliation, leases/fencing | DELIVERED BY COMMUNICATIONS | These are Communications-owned reliability semantics reused by F5; F5 does not create a parallel delivery subsystem. |
| generalized multi-action recovery workflow | EXPLICIT NON-GOAL / DEFERRED | F5 v1 remains immutable proposal + one-shot execution. A long-lived workflow engine requires a new product/contract decision. |

This disposition is part of F5 completion truth. Therefore "F5 complete" means complete against contract 32 plus the delivered/reused rows above; it does **not** mean that every potential action named by the roadmap has been implemented.

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
