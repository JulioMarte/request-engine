# Booking module

> **V3 baseline module.**

Owns local reservation and reservability truth:

```text
Resource
resource capability assignment
AvailabilitySchedule
ScheduleException
CapacityClaim
CapacityHold
Reservation
AttendanceResponse history
ReservationAttendance execution outcome
ReservationArrivalEstimate history
```

Catalog owns `ResourceCapability` vocabulary and immutable `OfferingVersion` mandatory resource requirements; booking resolves those requirements to concrete Resources.

Initial capacity models are only:

```text
exclusive
units
```

Initial commands/queries:

```text
FindAppointmentSlots
AcquireCapacityHold
BookAppointment
ConfirmCapacityHold
CancelReservation
RescheduleReservation
GetReservationStatus
ConfirmAttendance
RecordArrivalEstimate
DeclineAttendance
CheckInReservation
EvaluateNoShow
ChangeResourceAvailability
ChangeScheduleException
```

### Baseline decisions

- `1 Reservation = 1 OfferingVersion + 1 subject + 1 interval`.
- No `ReservationItem` baseline.
- Concrete `Resource` is the baseline tenant-local capacity serialization/lock root; no separate one-to-one `CapacityAuthority` baseline.
- For an explicitly authorized cross-tenant shared-capacity binding on an `exclusive` Resource, Booking locks the tenant-local Resource first and then the hidden `SharedCapacityIdentity` root. Unbound Resources retain the baseline protocol.
- `CapacityClaim` is the common Hold/Reservation capacity-consumption truth. Shared-capacity claim links are private serialization provenance, never a second capacity ledger.
- No `ResourceAllocation` baseline. Add a future `ResourceAssignment` only if execution assignment becomes independently mutable from capacity consumption.
- No CapacityPool, PlanningRevision, external commitment planning or field-service feasibility baseline.

An OfferingVersion may have multiple mandatory resource requirements. Booking must satisfy them atomically with one concrete Resource per requirement and the required units. No OR/k-of-n/late-binding expression language in baseline.

`CapacityHold` is a temporary commitment. Wall-clock expiry is authoritative even before cleanup persists an `expired` state.

Hold confirmation must promote/associate existing claims with the Reservation without temporary Hold + Reservation double counting.

Reschedule is self-overlap safe: lock the Reservation, then the union of old/new Resources in stable-id order; for bound Resources lock the complete shared-root set in stable-id order only after all local Resources; validate the **final** desired state excluding only this Reservation's claims being replaced; atomically mark old claims replaced and insert new claims. Failure/rollback preserves the original Reservation and claims.

Routine schedule changes do not silently rewrite already-committed Reservations. New booking/hold acquisition revalidates schedule under Resource locks; administrative invalidation of an existing Hold/Reservation must be an explicit semantic command.

## Reservation lifecycle and attendance

Reservation commitment and attendance execution are deliberately orthogonal:

```text
Reservation.status
confirmed | cancelled

ReservationAttendance.status
pending | checked_in | no_show
```

`AttendanceResponse` is append-only response history (`accepted|declined`). The newest response is the current response projection. A response changes Reservation concurrency state by advancing `Reservation.revision`.

`ReservationAttendance` records what happened operationally. Check-in and no-show serialize on the Reservation before mutating the one-per-Reservation execution projection.

A no-show is **not** a cancellation. It does not release capacity retroactively and it never creates a `SlotOpportunity`; the reserved interval has already occurred. A decline may cancel a future Reservation only when the immutable `booking_policy_snapshot` explicitly selects `decline_action=cancel`.

Lifecycle automation reads only the Reservation's policy snapshot. It does not reinterpret the current mutable Offering policy after booking.

Cancellation and reschedule may expose future capacity for recovery. That recovery begins only after the Booking transaction commits and then enters Queue through its public contract and the Phase 2B `SlotOpportunity -> SlotOffer` state machine.

Provider/network I/O never occurs while booking locks are held. Confirmation/reminder communications and waitlist recovery begin after booking commit through outbox/contracts — but only where the reservation lifecycle outbox handler is actually composed (the reference worker factory passes `reservation_lifecycle_factory`; a `build_worker_process` composition that omits it persists lifecycle events without processing them).

The authoritative transaction/race contract is `docs/v3/02-pre-sql-contract.md`. The cross-tenant extension design and privacy rationale are documented in `docs/v3/12-cross-tenant-shared-capacity-design.md` and ADR 0011.
