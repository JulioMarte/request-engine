# Booking module

> **V3 baseline module.**

Owns local reservation and reservability truth:

```text
Resource
AvailabilitySchedule
ScheduleException
CapacityClaim
CapacityHold
Reservation
AttendanceResponse / attendance policy coupled to reservation consequences
```

Initial capacity models are only `exclusive` and `units`.

Initial commands/queries include:

```text
FindAppointmentSlots
BookAppointment
CancelReservation
RescheduleReservation
GetReservationStatus
ConfirmAttendance
DeclineAttendance
ChangeResourceAvailability
ChangeScheduleException
```

`CapacityHold` remains the temporary local commitment primitive when a flow needs one. V3 does not require CapacityPool, PlanningRevision, external commitment planning, or advanced field-service feasibility in the baseline.

Before the clean V3 SQL candidate is frozen, re-evaluate whether the V2 `ResourceAllocation` + 1:1 `CapacityClaim` pair contains two independent truths. Prefer one authoritative reservation-consumption claim unless a real operational assignment concept requires a separate entity.

Reschedule must be self-overlap safe: lock the Reservation and old/new capacity sources in canonical order, validate the **final** state excluding claims replaced by the same operation, and atomically replace claims. A replacement Hold must not be a universal prerequisite when it would conflict with the Reservation being replaced.

Reservation confirmation and customer/patient attendance confirmation are distinct. No-response consequences require explicit policy.

Provider/network I/O never occurs while booking locks are held. Confirmation/reminder communications are produced after commit through outbox/communications contracts.
