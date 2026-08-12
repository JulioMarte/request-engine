# 0007 — Minimal V3 booking/capacity model
Status: Accepted

## Context

V2 represented a broad scheduling/commitment space using CapacityAuthority, CapacityClaim, ResourceAllocation, ReservationItem, CommitmentRequirement, CapacityPool, PlanningRevision and external commitment structures. The model defended sophisticated scenarios but introduced duplicate state and abstractions not required by the first production capabilities.

The V3 proof verticals require deterministic local appointment booking, multi-resource appointments when necessary, temporary holds, cancellation, self-overlap-safe reschedule and waitlist recovery.

## Decision

The V3 baseline uses:

```text
OfferingVersion
  → 0..N mandatory OfferingResourceRequirements
  → ResourceCapability

Resource
AvailabilitySchedule
ScheduleException
CapacityHold
CapacityClaim
Reservation
AttendanceResponse
```

Specific decisions:

1. One `Reservation` represents one `OfferingVersion`, one subject and one interval. No `ReservationItem` baseline.
2. A concrete `Resource` is the local capacity serialization/lock root. No separate one-to-one `CapacityAuthority` baseline.
3. `CapacityClaim` is the common capacity-consumption truth for both temporary Holds and confirmed Reservations.
4. No one-to-one `ResourceAllocation` baseline. A future `ResourceAssignment` may be introduced only when execution assignment is demonstrably independent from capacity consumption.
5. Offering resource requirements are immutable children of `OfferingVersion`, not a reusable generic requirement-template graph.
6. Initial requirement semantics are mandatory AND rows: one concrete Resource satisfying one ResourceCapability and quantity per requirement. No OR/k-of-n/late-binding optimizer.
7. Reschedule locks the Reservation and old/new Resources, validates the final desired state while excluding only claims replaced by that Reservation, then replaces claims atomically. A replacement Hold is not a universal reschedule prerequisite.
8. Wall-clock Hold expiry is authoritative before asynchronous cleanup.

## Consequences

Positive:

- fewer rows/joins/state transitions in the hot booking path;
- one obvious capacity conflict space;
- simpler race proofs for exclusive/units capacity;
- self-overlap reschedule can be expressed without temporary double counting;
- multi-resource appointments remain possible without a universal commitment graph;
- future pools/assignment concepts can be added through explicit migrations when proven.

Trade-offs:

- baseline cannot atomically sell an arbitrary cart of independent Offerings as one Reservation;
- pools/late binding require future schema evolution;
- a future non-Resource capacity source would justify introducing a generalized capacity-source abstraction then;
- a future independent execution assignment lifecycle would require a separate ResourceAssignment model.

## Rejected alternatives

### Preserve CapacityAuthority as a one-to-one Resource lock row

Rejected because the only baseline local capacity source is Resource, so the extra row adds indirection without independent semantics.

### Preserve ResourceAllocation + CapacityClaim 1:1

Rejected because both rows represent the same baseline capacity consumption and require synchronization machinery.

### Remove resource requirements entirely

Rejected because a real appointment can legitimately need more than one local resource atomically (for example provider + room/equipment). The accepted requirement model is deliberately smaller than V2 rather than absent.

### Require replacement Hold for every reschedule

Rejected because an overlapping self-reschedule can conflict with the Reservation it intends to replace even when the final state is valid.
