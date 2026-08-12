from collections import defaultdict
from dataclasses import dataclass
from itertools import product
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
    load_resource_schedules,
)
from request_engine.modules.booking.application.errors import (
    BookingConfigurationError,
    OfferingVersionNotBookable,
    OfferingVersionNotFound,
)
from request_engine.modules.booking.application.queries.find_appointment_slots import (
    FindAppointmentSlotsQuery,
)
from request_engine.modules.booking.contracts.appointments import AppointmentSlot, ResourceChoice
from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    AvailableInterval,
    CapacityModel,
    LiveCapacityClaim,
    RecurringAvailability,
    ResourceAvailability,
    find_resource_intervals,
    interval_has_resource_capacity,
    require_aware_utc,
)
from request_engine.modules.booking.domain.policy import slot_step_minutes
from request_engine.platform.db.session import SessionFactory, tenant_transaction


@dataclass(frozen=True, slots=True)
class _CandidateResource:
    requirement_id: UUID
    ordinal: int
    quantity: int
    resource_id: UUID
    location_id: UUID | None
    profile: ResourceAvailability


class PostgresAppointmentAvailabilityReader:
    """Advisory slot planner; authoritative commands always revalidate under locks."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def find_slots(self, query: FindAppointmentSlotsQuery) -> tuple[AppointmentSlot, ...]:
        window_start = require_aware_utc(query.window_start, "window_start")
        window_end = require_aware_utc(query.window_end, "window_end")
        if window_end <= window_start:
            raise ValueError("window_end must be after window_start")

        async with tenant_transaction(self._session_factory, query.organization_id) as session:
            offering = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT duration_minutes, bookable, booking_policy
                            FROM request_engine.offering_versions
                            WHERE organization_id = :organization_id
                              AND id = :offering_version_id
                            """
                        ),
                        {
                            "organization_id": query.organization_id,
                            "offering_version_id": query.offering_version_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if offering is None:
                raise OfferingVersionNotFound(query.offering_version_id)
            if offering["bookable"] is not True or offering["duration_minutes"] is None:
                raise OfferingVersionNotBookable(query.offering_version_id)

            duration_minutes = cast(int, offering["duration_minutes"])
            booking_policy = cast(dict[str, object], offering["booking_policy"])
            step_minutes = slot_step_minutes(booking_policy, duration_minutes)

            candidate_rows = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT
                                rr.id AS requirement_id,
                                rr.ordinal,
                                rr.quantity,
                                r.id AS resource_id,
                                r.location_id,
                                r.capacity_model,
                                r.capacity_units,
                                COALESCE(l.timezone, 'UTC') AS default_timezone
                            FROM request_engine.offering_resource_requirements rr
                            JOIN request_engine.resource_capability_assignments a
                              ON a.organization_id = rr.organization_id
                             AND a.capability_id = rr.capability_id
                            JOIN request_engine.resources r
                              ON r.organization_id = a.organization_id
                             AND r.id = a.resource_id
                            LEFT JOIN request_engine.locations l
                              ON l.organization_id = r.organization_id
                             AND l.id = r.location_id
                            WHERE rr.organization_id = :organization_id
                              AND rr.offering_version_id = :offering_version_id
                              AND r.active
                              AND (
                                  :location_id IS NULL
                                  OR r.location_id IS NULL
                                  OR r.location_id = :location_id
                              )
                            ORDER BY rr.ordinal, r.id
                            """
                        ),
                        {
                            "organization_id": query.organization_id,
                            "offering_version_id": query.offering_version_id,
                            "location_id": query.location_id,
                        },
                    )
                )
                .mappings()
                .all()
            )

            requirement_count = cast(
                int,
                (
                    await session.execute(
                        text(
                            """
                            SELECT count(*)
                            FROM request_engine.offering_resource_requirements
                            WHERE organization_id = :organization_id
                              AND offering_version_id = :offering_version_id
                            """
                        ),
                        {
                            "organization_id": query.organization_id,
                            "offering_version_id": query.offering_version_id,
                        },
                    )
                ).scalar_one(),
            )
            if requirement_count == 0:
                raise BookingConfigurationError(
                    "bookable OfferingVersion requires at least one resource requirement"
                )
            if not candidate_rows:
                return ()

            resource_ids = tuple(
                sorted({cast(UUID, row["resource_id"]) for row in candidate_rows}, key=str)
            )
            schedules = await load_resource_schedules(
                session,
                query.organization_id,
                resource_ids,
            )
            exceptions = await load_resource_exceptions(
                session,
                query.organization_id,
                resource_ids,
                window_start,
                window_end,
            )
            live_claims = await load_live_capacity_claims(
                session,
                query.organization_id,
                resource_ids,
                window_start,
                window_end,
            )

        candidates = _build_candidate_resources(
            candidate_rows,
            schedules=schedules,
            exceptions=exceptions,
            live_claims=live_claims,
        )
        ordinals = sorted({candidate.ordinal for candidate in candidates})
        if len(ordinals) != requirement_count:
            return ()

        interval_candidates: dict[
            AvailableInterval,
            dict[int, list[_CandidateResource]],
        ] = defaultdict(lambda: defaultdict(list))
        for candidate in candidates:
            intervals = find_resource_intervals(
                candidate.profile,
                window_start=window_start,
                window_end=window_end,
                duration_minutes=duration_minutes,
                step_minutes=step_minutes,
                required_quantity=candidate.quantity,
            )
            for interval in intervals:
                interval_candidates[interval][candidate.ordinal].append(candidate)

        slots: list[AppointmentSlot] = []
        for interval in sorted(interval_candidates):
            by_ordinal = interval_candidates[interval]
            if any(ordinal not in by_ordinal for ordinal in ordinals):
                continue
            choices_by_requirement = [
                sorted(by_ordinal[ordinal], key=lambda candidate: str(candidate.resource_id))
                for ordinal in ordinals
            ]
            for combination in product(*choices_by_requirement):
                if not _combination_has_capacity(combination, interval):
                    continue
                resources = tuple(
                    ResourceChoice(
                        requirement_id=candidate.requirement_id,
                        resource_id=candidate.resource_id,
                    )
                    for candidate in combination
                )
                slots.append(
                    AppointmentSlot(
                        offering_version_id=query.offering_version_id,
                        start_at=interval.start_at,
                        end_at=interval.end_at,
                        location_id=_slot_location(query.location_id, combination),
                        resources=resources,
                    )
                )
                if len(slots) >= query.limit:
                    return tuple(slots)

        return tuple(slots)


def _build_candidate_resources(
    rows: list[RowMapping],
    *,
    schedules: dict[UUID, tuple[RecurringAvailability, ...]],
    exceptions: dict[UUID, tuple[AvailabilityException, ...]],
    live_claims: dict[UUID, tuple[LiveCapacityClaim, ...]],
) -> tuple[_CandidateResource, ...]:
    candidates: list[_CandidateResource] = []
    for row in rows:
        resource_id = cast(UUID, row["resource_id"])
        candidates.append(
            _CandidateResource(
                requirement_id=cast(UUID, row["requirement_id"]),
                ordinal=cast(int, row["ordinal"]),
                quantity=cast(int, row["quantity"]),
                resource_id=resource_id,
                location_id=cast(UUID | None, row["location_id"]),
                profile=ResourceAvailability(
                    capacity_model=CapacityModel(cast(str, row["capacity_model"])),
                    capacity_units=cast(int, row["capacity_units"]),
                    default_timezone=cast(str, row["default_timezone"]),
                    schedules=schedules.get(resource_id, ()),
                    exceptions=exceptions.get(resource_id, ()),
                    live_claims=live_claims.get(resource_id, ()),
                ),
            )
        )
    return tuple(candidates)


def _combination_has_capacity(
    combination: tuple[_CandidateResource, ...],
    interval: AvailableInterval,
) -> bool:
    by_resource: dict[UUID, list[_CandidateResource]] = defaultdict(list)
    for candidate in combination:
        by_resource[candidate.resource_id].append(candidate)

    for values in by_resource.values():
        profile = values[0].profile
        quantity = sum(value.quantity for value in values)
        if profile.capacity_model is CapacityModel.EXCLUSIVE and len(values) > 1:
            return False
        if not interval_has_resource_capacity(
            profile,
            start_at=interval.start_at,
            end_at=interval.end_at,
            required_quantity=quantity,
        ):
            return False
    return True


def _slot_location(
    requested_location_id: UUID | None,
    combination: tuple[_CandidateResource, ...],
) -> UUID | None:
    if requested_location_id is not None:
        return requested_location_id
    locations = {
        candidate.location_id for candidate in combination if candidate.location_id is not None
    }
    return next(iter(locations)) if len(locations) == 1 else None
