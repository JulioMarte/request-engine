from request_engine.modules.booking.adapters.db import commitment_commands, reservation_commands
from request_engine.modules.booking.adapters.db import slot_offer_capacity as slot_offer_capacity_module
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
    CapacitySafeSlotOfferCapacity,
)

# These vertical tests import the concrete adapter names directly. Production
# composes the capacity-safe boundary around those delegates, so expose the same
# boundary here before pytest imports the test modules.
setattr(
    reservation_commands,
    "PostgresReservationCommands",
    CapacitySafeReservationCommands,
)
setattr(
    commitment_commands,
    "PostgresBookingCommitmentCommands",
    CapacitySafeBookingCommitmentCommands,
)
setattr(
    slot_offer_capacity_module,
    "PostgresSlotOfferCapacity",
    CapacitySafeSlotOfferCapacity,
)
