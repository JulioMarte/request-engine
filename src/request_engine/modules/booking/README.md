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
AttendanceResponse history / attendance policy consequences
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
DeclineAttendance
ChangeResourceAvailability
ChangeScheduleException
```

### Baseline decisions

- `1 Reservation = 1 OfferingVersion + 1 subject + 1 interval`.
- No `ReservationItem` baseline.
- Concrete `Resource` is the capacity serialization/lock root; no separate one-to-one `CapacityAuthority` baseline.
- `CapacityClaim` is the common Hold/Reservation capacity-consumption truth.
- No `ResourceAllocation` baseline. Add a future `ResourceAssignment` only if execution assignment becomes independently mutable from capacity consumption.
- No CapacityPool, PlanningRevision, external commitment planning or field-service feasibility baseline.

An OfferingVersion may have multiple mandatory resource requirements. Booking must satisfy them atomically with one concrete Resource per requirement and the required units. No OR/k-of-n/late-binding expression language in baseline.

`CapacityHold` is a temporary commitment. Wall-clock expiry is authoritative even before cleanup persists an `expired` state.

Hold confirmation must promote/associate existing claims with the Reservation without temporary Hold + Reservation double counting.

Reschedule is self-overlap safe: lock the Reservation, then the union of old/new Resources in stable-id order; validate the **final** desired state excluding only this Reservation's claims being replaced; atomically mark old claims replaced and insert new claims. Failure/rollback preserves the original Reservation and claims.

Routine schedule changes do not silently rewrite already-committed Reservations. New booking/hold acquisition revalidates schedule under Resource locks; administrative invalidation of an existing Hold/Reservation must be an explicit semantic command.

Reservation confirmation and customer/patient attendance confirmation are distinct. Attendance responses are history-preserving facts/current projection; no-response or decline changes Reservation/capacity only through explicit versioned policy.

Provider/network I/O never occurs while booking locks are held. Confirmation/reminder communications and waitlist recovery begin after booking commit through outbox/contracts.

The authoritative transaction/race contract is `docs/v3/02-pre-sql-contract.md`.
