# Booking module

Owns reservability and commitment truth: resources/capabilities, schedules, operating-location eligibility, pools, capacity authorities/claims, holds, reservations, commitment requirements, allocations, and external commitment dependencies.

Initial commands include `CreateCapacityHold`, `ReleaseCapacityHold`, `ConfirmReservation`, `CancelReservationScope`, `RescheduleReservation`, `ReplaceResourceAllocation`, and reservability configuration mutations.

Owns reservation/external-commitment read contracts and Python wrappers for capacity/planning `request_cmd` primitives.

The module is intentionally broad because schedules, locations, pools, claims, holds, and reservations share the same authority/revision and race protocols.
