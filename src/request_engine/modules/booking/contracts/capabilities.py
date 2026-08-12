"""Stable booking capability identities and their current permission requirements.

Capability IDs are public/application semantic identities. Permission strings are
an authorization vocabulary and may differ. Neither is derived from Python handler,
adapter, or SQL routine names by convention; both are explicit contracts.
"""

FIND_SLOTS = "appointments.find_slots"
HOLD = "appointments.hold"
BOOK = "appointments.book"
GET = "appointments.get"
CANCEL = "appointments.cancel"
RESCHEDULE = "appointments.reschedule"
CONFIRM_ATTENDANCE = "appointments.confirm_attendance"

FIND_SLOTS_PERMISSION = "booking.find_slots"
HOLD_PERMISSION = "booking.acquire_capacity_hold"
BOOK_PERMISSION = "booking.book_appointment"
GET_PERMISSION = "booking.read"
CANCEL_PERMISSION = "booking.cancel_reservation"
RESCHEDULE_PERMISSION = "booking.reschedule_reservation"
CONFIRM_ATTENDANCE_PERMISSION = "booking.confirm_attendance"
