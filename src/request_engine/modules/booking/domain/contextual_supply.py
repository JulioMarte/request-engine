from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from request_engine.modules.booking.domain.availability import (
    AvailableInterval,
    ResourceAvailability,
    find_resource_intervals,
    interval_is_scheduled_available,
)


class ContextualSupplyError(ValueError):
    """Base class for deterministic F1 contextual configuration failures."""


class MissingCommercialTerms(ContextualSupplyError):
    pass


class ConflictingContextualTerms(ContextualSupplyError):
    pass


class ContextNotBookable(ContextualSupplyError):
    pass


@dataclass(frozen=True, slots=True)
class BaseBookingTerms:
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    source_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ContextBookingTerms:
    id: UUID
    revision: int
    amount: Decimal | None
    currency: str | None
    planned_duration_minutes: int | None
    bookable: bool


@dataclass(frozen=True, slots=True)
class ResolvedBookingTerms:
    amount: Decimal
    currency: str
    planned_duration_minutes: int
    base_source_id: UUID | None
    context_source_ids: tuple[UUID, ...]
    context_revisions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ContextualResourceAvailability:
    """Composed scheduling input for one Resource-at-Location assignment."""

    location: ResourceAvailability
    resource: ResourceAvailability


def find_contextual_resource_intervals(
    profile: ContextualResourceAvailability,
    *,
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    step_minutes: int,
    required_quantity: int,
) -> tuple[AvailableInterval, ...]:
    """Return intervals allowed by both Resource context and physical Location."""

    resource_intervals = find_resource_intervals(
        profile.resource,
        window_start=window_start,
        window_end=window_end,
        duration_minutes=duration_minutes,
        step_minutes=step_minutes,
        required_quantity=required_quantity,
    )
    return tuple(
        interval
        for interval in resource_intervals
        if interval_is_scheduled_available(
            profile.location,
            start_at=interval.start_at,
            end_at=interval.end_at,
        )
    )


def resolve_booking_terms(
    base: BaseBookingTerms,
    contexts: tuple[ContextBookingTerms | None, ...],
) -> ResolvedBookingTerms:
    """Resolve deterministic F1 terms for every selected Resource context.

    ``None`` is an explicit selected Resource-at-Location context with no exact
    override, so it resolves through OfferingVersion defaults and still
    participates in conflict detection against Resources that do have an exact
    override.
    """

    if any(context is not None and not context.bookable for context in contexts):
        raise ContextNotBookable("one or more selected booking contexts are not bookable")

    if not contexts:
        amount, currency, duration = _require_complete_terms(
            base.amount,
            base.currency,
            base.planned_duration_minutes,
        )
        return ResolvedBookingTerms(
            amount=amount,
            currency=currency,
            planned_duration_minutes=duration,
            base_source_id=base.source_id,
            context_source_ids=(),
            context_revisions=(),
        )

    resolved = [
        _resolve_one(base, context)
        for context in contexts
    ]
    first = resolved[0]
    if any(value != first for value in resolved[1:]):
        raise ConflictingContextualTerms(
            "selected Resource-at-Location contexts resolve to conflicting booking terms"
        )

    amount, currency, duration = first
    actual_contexts = tuple(context for context in contexts if context is not None)
    return ResolvedBookingTerms(
        amount=amount,
        currency=currency,
        planned_duration_minutes=duration,
        base_source_id=base.source_id,
        context_source_ids=tuple(context.id for context in actual_contexts),
        context_revisions=tuple(context.revision for context in actual_contexts),
    )


def _resolve_one(
    base: BaseBookingTerms,
    context: ContextBookingTerms | None,
) -> tuple[Decimal, str, int]:
    if context is None:
        return _require_complete_terms(
            base.amount,
            base.currency,
            base.planned_duration_minutes,
        )
    return _require_complete_terms(
        context.amount if context.amount is not None else base.amount,
        context.currency if context.currency is not None else base.currency,
        (
            context.planned_duration_minutes
            if context.planned_duration_minutes is not None
            else base.planned_duration_minutes
        ),
    )


def _require_complete_terms(
    amount: Decimal | None,
    currency: str | None,
    duration: int | None,
) -> tuple[Decimal, str, int]:
    if amount is None or currency is None or duration is None:
        raise MissingCommercialTerms(
            "bookable contextual supply requires amount, currency and planned duration"
        )
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        raise ValueError("currency must be an uppercase three-letter code")
    if duration <= 0:
        raise ValueError("planned duration must be positive")
    return amount, currency, duration
