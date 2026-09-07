from __future__ import annotations

from typing import TYPE_CHECKING

from request_engine.modules.booking.contracts.appointments import AppointmentSlot

if TYPE_CHECKING:
    from request_engine.modules.discovery.application.queries.search_supply import DiscoveryOption


def is_f2_discoverable(slot: AppointmentSlot) -> bool:
    return bool(slot.resources) and all(
        choice.resource_location_assignment_id is not None
        and choice.assignment_revision is not None
        and choice.assignment_revision > 0
        and choice.availability_revision is not None
        and choice.availability_revision > 0
        for choice in slot.resources
    )


def option_order(option: DiscoveryOption) -> tuple[object, ...]:
    resource_ids = tuple(str(choice.resource_id) for choice in option.slot.resources)
    return (
        option.slot.start_at,
        option.candidate.distance_meters,
        str(option.candidate.organization_id),
        str(option.candidate.location_id),
        str(option.candidate.offering_id),
        resource_ids,
        str(option.candidate.publication_id),
    )
