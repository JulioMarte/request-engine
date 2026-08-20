from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import uuid4

import pytest

from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    CapacityModel,
    ExceptionKind,
    RecurringAvailability,
    ResourceAvailability,
)
from request_engine.modules.booking.domain.contextual_supply import (
    BaseBookingTerms,
    ConflictingContextualTerms,
    ContextBookingTerms,
    ContextNotBookable,
    ContextualResourceAvailability,
    MissingCommercialTerms,
    find_contextual_resource_intervals,
    resolve_booking_terms,
)


def _profile(
    *,
    schedules: tuple[RecurringAvailability, ...] = (),
    exceptions: tuple[AvailabilityException, ...] = (),
) -> ResourceAvailability:
    return ResourceAvailability(
        capacity_model=CapacityModel.EXCLUSIVE,
        capacity_units=1,
        default_timezone="America/Santo_Domingo",
        schedules=schedules,
        exceptions=exceptions,
        live_claims=(),
    )


def _monday_schedule(start: time, end: time) -> RecurringAvailability:
    return RecurringAvailability(
        weekday=0,
        local_start=start,
        local_end=end,
        timezone="America/Santo_Domingo",
        valid_from=date(2030, 1, 1),
        valid_until=None,
    )


@pytest.mark.unit
def test_contextual_intervals_intersect_location_and_resource_hours() -> None:
    context = ContextualResourceAvailability(
        location=_profile(schedules=(_monday_schedule(time(8), time(18)),)),
        resource=_profile(schedules=(_monday_schedule(time(13), time(17)),)),
    )

    intervals = find_contextual_resource_intervals(
        context,
        window_start=datetime(2030, 1, 7, 12, tzinfo=UTC),
        window_end=datetime(2030, 1, 7, 22, tzinfo=UTC),
        duration_minutes=60,
        step_minutes=60,
        required_quantity=1,
    )

    assert [(value.start_at.hour, value.end_at.hour) for value in intervals] == [
        (17, 18),
        (18, 19),
        (19, 20),
        (20, 21),
    ]


@pytest.mark.unit
def test_resource_additional_availability_cannot_open_closed_location() -> None:
    resource_extra = AvailabilityException(
        start_at=datetime(2030, 1, 7, 21, tzinfo=UTC),
        end_at=datetime(2030, 1, 7, 22, tzinfo=UTC),
        kind=ExceptionKind.AVAILABLE,
    )
    context = ContextualResourceAvailability(
        location=_profile(schedules=(_monday_schedule(time(8), time(16)),)),
        resource=_profile(
            schedules=(_monday_schedule(time(9), time(15)),),
            exceptions=(resource_extra,),
        ),
    )

    intervals = find_contextual_resource_intervals(
        context,
        window_start=datetime(2030, 1, 7, 12, tzinfo=UTC),
        window_end=datetime(2030, 1, 7, 23, tzinfo=UTC),
        duration_minutes=60,
        step_minutes=60,
        required_quantity=1,
    )

    assert all(value.start_at != resource_extra.start_at for value in intervals)


@pytest.mark.unit
def test_location_closure_blocks_resource_recurring_interval() -> None:
    closure = AvailabilityException(
        start_at=datetime(2030, 1, 7, 18, tzinfo=UTC),
        end_at=datetime(2030, 1, 7, 20, tzinfo=UTC),
        kind=ExceptionKind.UNAVAILABLE,
    )
    context = ContextualResourceAvailability(
        location=_profile(
            schedules=(_monday_schedule(time(8), time(18)),),
            exceptions=(closure,),
        ),
        resource=_profile(schedules=(_monday_schedule(time(13), time(17)),)),
    )

    intervals = find_contextual_resource_intervals(
        context,
        window_start=datetime(2030, 1, 7, 16, tzinfo=UTC),
        window_end=datetime(2030, 1, 7, 22, tzinfo=UTC),
        duration_minutes=60,
        step_minutes=60,
        required_quantity=1,
    )

    assert all(not (value.start_at < closure.end_at and closure.start_at < value.end_at) for value in intervals)


@pytest.mark.unit
def test_exact_context_terms_override_base_terms() -> None:
    context_id = uuid4()
    resolved = resolve_booking_terms(
        BaseBookingTerms(
            amount=Decimal("3500"),
            currency="DOP",
            planned_duration_minutes=30,
            source_id=uuid4(),
        ),
        (
            ContextBookingTerms(
                id=context_id,
                revision=3,
                amount=Decimal("4000"),
                currency="DOP",
                planned_duration_minutes=45,
                bookable=True,
            ),
        ),
    )

    assert resolved.amount == Decimal("4000")
    assert resolved.currency == "DOP"
    assert resolved.planned_duration_minutes == 45
    assert resolved.context_source_ids == (context_id,)
    assert resolved.context_revisions == (3,)


@pytest.mark.unit
def test_context_duration_can_override_while_price_falls_back_to_base() -> None:
    resolved = resolve_booking_terms(
        BaseBookingTerms(
            amount=Decimal("3500"),
            currency="DOP",
            planned_duration_minutes=30,
        ),
        (
            ContextBookingTerms(
                id=uuid4(),
                revision=1,
                amount=None,
                currency=None,
                planned_duration_minutes=45,
                bookable=True,
            ),
        ),
    )

    assert resolved.amount == Decimal("3500")
    assert resolved.planned_duration_minutes == 45


@pytest.mark.unit
def test_multi_resource_conflicting_terms_fail_closed() -> None:
    base = BaseBookingTerms(
        amount=Decimal("3500"),
        currency="DOP",
        planned_duration_minutes=30,
    )
    contexts = (
        ContextBookingTerms(uuid4(), 1, Decimal("4000"), "DOP", 45, True),
        ContextBookingTerms(uuid4(), 1, Decimal("4500"), "DOP", 45, True),
    )

    with pytest.raises(ConflictingContextualTerms):
        resolve_booking_terms(base, contexts)


@pytest.mark.unit
def test_unbookable_or_incomplete_terms_fail_closed() -> None:
    base = BaseBookingTerms(amount=None, currency=None, planned_duration_minutes=30)
    with pytest.raises(MissingCommercialTerms):
        resolve_booking_terms(base, ())

    with pytest.raises(ContextNotBookable):
        resolve_booking_terms(
            BaseBookingTerms(Decimal("3500"), "DOP", 30),
            (ContextBookingTerms(uuid4(), 1, None, None, None, False),),
        )
