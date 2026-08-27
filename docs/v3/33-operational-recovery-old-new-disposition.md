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
