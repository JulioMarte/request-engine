from request_engine.modules.booking.contracts.appointments import AppointmentSlot


def is_f2_discoverable(slot: AppointmentSlot) -> bool:
    return (
        slot.location_id is not None
        and slot.configuration_fingerprint is not None
        and slot.planned_duration_minutes is not None
        and slot.amount is not None
        and slot.currency is not None
    )


def option_order(item: object) -> tuple[object, ...]:
    from request_engine.modules.discovery.application.queries.search_supply import DiscoveryOption

    option = item
    assert isinstance(option, DiscoveryOption)
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
