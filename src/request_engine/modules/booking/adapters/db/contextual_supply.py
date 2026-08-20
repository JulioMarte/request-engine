from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    CapacityModel,
    ExceptionKind,
    RecurringAvailability,
    ResourceAvailability,
)
from request_engine.modules.booking.domain.contextual_supply import (
    BaseBookingTerms,
    ContextBookingTerms,
)


@dataclass(frozen=True, slots=True)
class AssignmentObservation:
    id: UUID
    resource_id: UUID
    location_id: UUID
    effective_start: datetime
    effective_end: datetime | None
    revision: int

    def contains(self, start_at: datetime, end_at: datetime) -> bool:
        return self.effective_start <= start_at and (
            self.effective_end is None or end_at <= self.effective_end
        )


@dataclass(frozen=True, slots=True)
class ContextTermObservation:
    assignment_id: UUID
    effective_start: datetime
    effective_end: datetime | None
    terms: ContextBookingTerms

    def applies_at(self, instant: datetime) -> bool:
        return self.effective_start <= instant and (
            self.effective_end is None or instant < self.effective_end
        )


@dataclass(frozen=True, slots=True)
class LocationObservation:
    id: UUID
    timezone: str
    operational_revision: int
    profile: ResourceAvailability


async def f1_contextual_schema_available(session: AsyncSession) -> bool:
    """Return whether the post-V3 contextual schema is installed.

    Current source code is intentionally still exercised against the frozen V3
    candidate in release-provenance CI. Schema absence there is a supported
    compatibility state, not an error or a reason to mutate candidate history.
    """

    return cast(
        bool,
        (
            await session.execute(
                text(
                    """
                    SELECT
                        to_regclass('request_engine.resource_location_assignments') IS NOT NULL
                        AND to_regclass('request_engine.offering_version_booking_terms') IS NOT NULL
                    """
                )
            )
        ).scalar_one(),
    )


async def load_contextualization(
    session: AsyncSession,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
    window_start: datetime,
    window_end: datetime,
) -> tuple[set[UUID], dict[UUID, tuple[AssignmentObservation, ...]]]:
    if not resource_ids or not await f1_contextual_schema_available(session):
        return set(), {}

    contextualized_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT resource_id
                    FROM request_engine.resource_location_assignments
                    WHERE organization_id = :organization_id
                      AND resource_id = ANY(CAST(:resource_ids AS uuid[]))
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_ids": [str(value) for value in resource_ids],
                },
            )
        )
        .scalars()
        .all()
    )
    contextualized = {cast(UUID, value) for value in contextualized_rows}
    if not contextualized:
        return set(), {}

    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, resource_id, location_id,
                           lower(effective_during) AS effective_start,
                           upper(effective_during) AS effective_end,
                           revision
                    FROM request_engine.resource_location_assignments
                    WHERE organization_id = :organization_id
                      AND resource_id = ANY(CAST(:resource_ids AS uuid[]))
                      AND status = 'active'
                      AND effective_during && tstzrange(:window_start, :window_end, '[)')
                    ORDER BY resource_id, lower(effective_during), location_id, id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_ids": [str(value) for value in resource_ids],
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[AssignmentObservation]] = defaultdict(list)
    for row in rows:
        resource_id = cast(UUID, row["resource_id"])
        grouped[resource_id].append(
            AssignmentObservation(
                id=cast(UUID, row["id"]),
                resource_id=resource_id,
                location_id=cast(UUID, row["location_id"]),
                effective_start=cast(datetime, row["effective_start"]),
                effective_end=cast(datetime | None, row["effective_end"]),
                revision=cast(int, row["revision"]),
            )
        )
    return contextualized, {key: tuple(value) for key, value in grouped.items()}


async def load_assignment_schedules(
    session: AsyncSession,
    organization_id: UUID,
    assignment_ids: tuple[UUID, ...],
) -> dict[UUID, tuple[RecurringAvailability, ...]]:
    if not assignment_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT av.resource_location_assignment_id AS assignment_id,
                           av.weekday, av.local_start, av.local_end,
                           av.valid_from, av.valid_until, l.timezone
                    FROM request_engine.resource_location_availability av
                    JOIN request_engine.resource_location_assignments a
                      ON a.organization_id = av.organization_id
                     AND a.id = av.resource_location_assignment_id
                    JOIN request_engine.locations l
                      ON l.organization_id = a.organization_id
                     AND l.id = a.location_id
                    WHERE av.organization_id = :organization_id
                      AND av.resource_location_assignment_id = ANY(
                          CAST(:assignment_ids AS uuid[])
                      )
                      AND av.active
                    ORDER BY av.resource_location_assignment_id,
                             av.weekday, av.local_start, av.id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "assignment_ids": [str(value) for value in assignment_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[RecurringAvailability]] = defaultdict(list)
    for row in rows:
        grouped[cast(UUID, row["assignment_id"])].append(
            RecurringAvailability(
                weekday=cast(int, row["weekday"]),
                local_start=cast(time, row["local_start"]),
                local_end=cast(time, row["local_end"]),
                timezone=cast(str, row["timezone"]),
                valid_from=cast(date | None, row["valid_from"]),
                valid_until=cast(date | None, row["valid_until"]),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


async def load_assignment_exceptions(
    session: AsyncSession,
    organization_id: UUID,
    assignment_ids: tuple[UUID, ...],
    window_start: datetime,
    window_end: datetime,
) -> dict[UUID, tuple[AvailabilityException, ...]]:
    if not assignment_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT resource_location_assignment_id AS assignment_id,
                           lower(during) AS start_at,
                           upper(during) AS end_at,
                           exception_kind
                    FROM request_engine.resource_location_schedule_exceptions
                    WHERE organization_id = :organization_id
                      AND resource_location_assignment_id = ANY(
                          CAST(:assignment_ids AS uuid[])
                      )
                      AND active
                      AND during && tstzrange(:window_start, :window_end, '[)')
                    ORDER BY resource_location_assignment_id, lower(during), id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "assignment_ids": [str(value) for value in assignment_ids],
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[AvailabilityException]] = defaultdict(list)
    for row in rows:
        grouped[cast(UUID, row["assignment_id"])].append(
            AvailabilityException(
                start_at=cast(datetime, row["start_at"]),
                end_at=cast(datetime, row["end_at"]),
                kind=ExceptionKind(cast(str, row["exception_kind"])),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


async def load_location_observations(
    session: AsyncSession,
    organization_id: UUID,
    location_ids: tuple[UUID, ...],
    window_start: datetime,
    window_end: datetime,
) -> dict[UUID, LocationObservation]:
    if not location_ids:
        return {}

    location_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, timezone, operational_revision
                    FROM request_engine.locations
                    WHERE organization_id = :organization_id
                      AND id = ANY(CAST(:location_ids AS uuid[]))
                      AND active
                    ORDER BY id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "location_ids": [str(value) for value in location_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    timezone_by_location = {
        cast(UUID, row["id"]): cast(str, row["timezone"]) for row in location_rows
    }
    revision_by_location = {
        cast(UUID, row["id"]): cast(int, row["operational_revision"]) for row in location_rows
    }

    hour_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT location_id, weekday, local_start, local_end,
                           valid_from, valid_until
                    FROM request_engine.location_operational_hours
                    WHERE organization_id = :organization_id
                      AND location_id = ANY(CAST(:location_ids AS uuid[]))
                      AND active
                    ORDER BY location_id, weekday, local_start, id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "location_ids": [str(value) for value in location_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    schedules: dict[UUID, list[RecurringAvailability]] = defaultdict(list)
    for row in hour_rows:
        location_id = cast(UUID, row["location_id"])
        timezone = timezone_by_location.get(location_id)
        if timezone is None:
            continue
        schedules[location_id].append(
            RecurringAvailability(
                weekday=cast(int, row["weekday"]),
                local_start=cast(time, row["local_start"]),
                local_end=cast(time, row["local_end"]),
                timezone=timezone,
                valid_from=cast(date | None, row["valid_from"]),
                valid_until=cast(date | None, row["valid_until"]),
            )
        )

    exception_rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT location_id, lower(during) AS start_at,
                           upper(during) AS end_at, exception_kind
                    FROM request_engine.location_hours_exceptions
                    WHERE organization_id = :organization_id
                      AND location_id = ANY(CAST(:location_ids AS uuid[]))
                      AND active
                      AND during && tstzrange(:window_start, :window_end, '[)')
                    ORDER BY location_id, lower(during), id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "location_ids": [str(value) for value in location_ids],
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
        )
        .mappings()
        .all()
    )
    exceptions: dict[UUID, list[AvailabilityException]] = defaultdict(list)
    for row in exception_rows:
        exceptions[cast(UUID, row["location_id"])].append(
            AvailabilityException(
                start_at=cast(datetime, row["start_at"]),
                end_at=cast(datetime, row["end_at"]),
                kind=ExceptionKind(cast(str, row["exception_kind"])),
            )
        )

    result: dict[UUID, LocationObservation] = {}
    for location_id, timezone in timezone_by_location.items():
        result[location_id] = LocationObservation(
            id=location_id,
            timezone=timezone,
            operational_revision=revision_by_location[location_id],
            profile=ResourceAvailability(
                capacity_model=CapacityModel.EXCLUSIVE,
                capacity_units=1,
                default_timezone=timezone,
                schedules=tuple(schedules.get(location_id, ())),
                exceptions=tuple(exceptions.get(location_id, ())),
                live_claims=(),
            ),
        )
    return result


async def load_booking_terms(
    session: AsyncSession,
    organization_id: UUID,
    offering_version_id: UUID,
    assignment_ids: tuple[UUID, ...],
    base_duration_minutes: int | None,
    window_start: datetime,
    window_end: datetime,
) -> tuple[BaseBookingTerms, dict[UUID, tuple[ContextTermObservation, ...]]]:
    if not await f1_contextual_schema_available(session):
        return BaseBookingTerms(
            amount=None,
            currency=None,
            planned_duration_minutes=base_duration_minutes,
        ), {}

    base_row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, amount, currency
                    FROM request_engine.offering_version_booking_terms
                    WHERE organization_id = :organization_id
                      AND offering_version_id = :offering_version_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                },
            )
        )
        .mappings()
        .first()
    )
    base = BaseBookingTerms(
        amount=cast(Decimal, base_row["amount"]) if base_row is not None else None,
        currency=cast(str, base_row["currency"]) if base_row is not None else None,
        planned_duration_minutes=base_duration_minutes,
        source_id=cast(UUID, base_row["id"]) if base_row is not None else None,
    )
    if not assignment_ids:
        return base, {}

    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, resource_location_assignment_id AS assignment_id,
                           lower(effective_during) AS effective_start,
                           upper(effective_during) AS effective_end,
                           amount, currency, planned_duration_minutes,
                           bookable, revision
                    FROM request_engine.booking_context_terms
                    WHERE organization_id = :organization_id
                      AND offering_version_id = :offering_version_id
                      AND resource_location_assignment_id = ANY(
                          CAST(:assignment_ids AS uuid[])
                      )
                      AND active
                      AND effective_during && tstzrange(:window_start, :window_end, '[)')
                    ORDER BY resource_location_assignment_id,
                             lower(effective_during), id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                    "assignment_ids": [str(value) for value in assignment_ids],
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[ContextTermObservation]] = defaultdict(list)
    for row in rows:
        assignment_id = cast(UUID, row["assignment_id"])
        grouped[assignment_id].append(
            ContextTermObservation(
                assignment_id=assignment_id,
                effective_start=cast(datetime, row["effective_start"]),
                effective_end=cast(datetime | None, row["effective_end"]),
                terms=ContextBookingTerms(
                    id=cast(UUID, row["id"]),
                    revision=cast(int, row["revision"]),
                    amount=cast(Decimal | None, row["amount"]),
                    currency=cast(str | None, row["currency"]),
                    planned_duration_minutes=cast(int | None, row["planned_duration_minutes"]),
                    bookable=cast(bool, row["bookable"]),
                ),
            )
        )
    return base, {key: tuple(value) for key, value in grouped.items()}


def effective_context_terms(
    terms: tuple[ContextTermObservation, ...],
    instant: datetime,
) -> ContextBookingTerms | None:
    matching = [row.terms for row in terms if row.applies_at(instant)]
    if len(matching) > 1:
        raise RuntimeError("database returned overlapping active BookingContextTerms")
    return matching[0] if matching else None
