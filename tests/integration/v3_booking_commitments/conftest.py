from typing import Any, cast

from request_engine.modules.booking.adapters.db import (
    commitment_commands,
    reservation_commands,
    slot_offer_capacity,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
    CapacitySafeSlotOfferCapacity,
)

# The vertical module imports concrete adapter names. Production composes these
# capacity-safe boundaries, so make the integration package exercise that exact
# contract without changing the underlying delegates used by the wrappers.
cast(Any, reservation_commands).PostgresReservationCommands = CapacitySafeReservationCommands
cast(
    Any, commitment_commands
).PostgresBookingCommitmentCommands = CapacitySafeBookingCommitmentCommands
cast(Any, slot_offer_capacity).PostgresSlotOfferCapacity = CapacitySafeSlotOfferCapacity
