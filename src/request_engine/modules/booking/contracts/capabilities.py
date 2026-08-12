"""Stable public capability identities owned by the booking module.

These identifiers are part of the application/public contract. They are deliberately
independent from Python handler names, adapter class names, and database routines.
Renaming an implementation detail must not silently change authorization or
idempotency scope.
"""

FIND_SLOTS = "appointments.find_slots"
HOLD = "appointments.hold"
BOOK = "appointments.book"
GET = "appointments.get"
CANCEL = "appointments.cancel"
RESCHEDULE = "appointments.reschedule"
CONFIRM_ATTENDANCE = "appointments.confirm_attendance"
