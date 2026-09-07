import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from itertools import product
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from request_engine.modules.booking.adapters.db import candidate_source
from request_engine.modules.booking.adapters.db.contextual_supply import (
    AssignmentObservation,
    ContextTermObservation,
    LocationObservation,
    effective_context_terms,
    load_assignment_exceptions,
    load_assignment_schedules,
    load_booking_terms,
    load_contextualization,
    load_location_observations,
)
from request_engine.modules.booking.adapters.db.effective_booking_policy import (
    EFFECTIVE_BOOKING_POLICY_SELECT,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
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
    interval_is_scheduled_available,
    require_aware_utc,
)
from request_engine.modules.booking.domain.contextual_supply import (
    BaseBookingTerms,
    ConflictingContextualTerms,
    ContextBookingTerms,
    ContextNotBookable,
    MissingCommercialTerms,
    ResolvedBookingTerms,
    resolve_booking_terms,
)
from request_engine.modules.booking.domain.policy import slot_step_minutes
from request_engine.platform.db.session import SessionFactory, tenant_transaction


@dataclass(frozen=True, slots=True)
class _CandidateResource:
    requirement_id: UUID
    ordinal: int
    quantity: int
    resource_id: UUID
    availability_revision: int
    profile: ResourceAvailability
    assignment: AssignmentObservation
    location: LocationObservation

    @property
    def location_id(self) -> UUID:
        return self.assignment.location_id


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
                            f"""
                            SELECT ov.duration_minutes, ov.bookable,
                                   {EFFECTIVE_BOOKING_POLICY_SELECT}
                            FROM request_engine.offering_versions ov
                            JOIN request_engine.offerings o
                              ON o.organization_id = ov.organization_id
                             AND o.id = ov.offering_id
                            WHERE ov.organization_id = :organization_id
                              AND ov.id = :offering_version_id
                              AND o.active
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

            base_duration = cast(int, offering["duration_minutes"])
            booking_policy = cast(dict[str, object], offering["booking_policy"])
            step_minutes = slot_step_minutes(booking_policy, base_duration)

            candidate_rows = await candidate_source.load(
                session,
                organization_id=query.organization_id,
                offering_version_id=query.offering_version_id,
            )
            if query.resource_id is not None:
                candidate_rows = candidate_source.apply_resource_preference(
                    candidate_rows, query.resource_id
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
            _, assignments_by_resource = await load_contextualization(
                session,
                query.organization_id,
                resource_ids,
                window_start,
                window_end,
            )
            assignment_ids = tuple(
                sorted(
                    {
                        assignment.id
                        for assignments in assignments_by_resource.values()
                        for assignment in assignments
                    },
                    key=str,
                )
            )
            location_ids = tuple(
                sorted(
                    {
                        assignment.location_id
                        for assignments in assignments_by_resource.values()
                        for assignment in assignments
                    },
                    key=str,
                )
            )
            broad_exceptions = await load_resource_exceptions(
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
            assignment_schedules = await load_assignment_schedules(
                session,
                query.organization_id,
                assignment_ids,
            )
            assignment_exceptions = await load_assignment_exceptions(
                session,
                query.organization_id,
                assignment_ids,
                window_start,
                window_end,
            )
            locations = await load_location_observations(
                session,
                query.organization_id,
                location_ids,
                window_start,
                window_end,
            )
            base_terms, context_terms = await load_booking_terms(
                session,
                query.organization_id,
                query.offering_version_id,
                assignment_ids,
                base_duration,
                window_start,
                window_end,
            )

        candidates = _build_candidate_resources(
            candidate_rows,
            query_location_id=query.location_id,
            assignments_by_resource=assignments_by_resource,
            broad_exceptions=broad_exceptions,
            live_claims=live_claims,
            assignment_schedules=assignment_schedules,
            assignment_exceptions=assignment_exceptions,
            locations=locations,
        )
        ordinals = sorted({candidate.ordinal for candidate in candidates})
        if len(ordinals) != requirement_count:
            return ()

        return _contextual_slots(
            candidates,
            query=query,
            ordinals=ordinals,
            step_minutes=step_minutes,
            window_start=window_start,
            window_end=window_end,
            base_terms=base_terms,
            context_terms=context_terms,
        )


def _build_candidate_resources(
    rows: Sequence[RowMapping],
    *,
    query_location_id: UUID | None,
    assignments_by_resource: dict[UUID, tuple[AssignmentObservation, ...]],
    broad_exceptions: dict[UUID, tuple[AvailabilityException, ...]],
    live_claims: dict[UUID, tuple[LiveCapacityClaim, ...]],
    assignment_schedules: dict[UUID, tuple[RecurringAvailability, ...]],
    assignment_exceptions: dict[UUID, tuple[AvailabilityException, ...]],
    locations: dict[UUID, LocationObservation],
) -> tuple[_CandidateResource, ...]:
    candidates: list[_CandidateResource] = []
    for row in rows:
        requirement_id = cast(UUID, row["requirement_id"])
        ordinal = cast(int, row["ordinal"])
        quantity = cast(int, row["quantity"])
        resource_id = cast(UUID, row["resource_id"])
        availability_revision = cast(int, row["availability_revision"])
        capacity_model = CapacityModel(cast(str, row["capacity_model"]))
        capacity_units = cast(int, row["capacity_units"])

        for assignment in assignments_by_resource.get(resource_id, ()):
            if query_location_id is not None and assignment.location_id != query_location_id:
                continue
            location = locations.get(assignment.location_id)
            if location is None:
                continue
            exceptions = broad_exceptions.get(resource_id, ()) + assignment_exceptions.get(
                assignment.id, ()
            )
            candidates.append(
                _CandidateResource(
                    requirement_id=requirement_id,
                    ordinal=ordinal,
                    quantity=quantity,
                    resource_id=resource_id,
                    availability_revision=availability_revision,
                    profile=ResourceAvailability(
                        capacity_model=capacity_model,
                        capacity_units=capacity_units,
                        default_timezone=location.timezone,
                        schedules=assignment_schedules.get(assignment.id, ()),
                        exceptions=exceptions,
                        live_claims=live_claims.get(resource_id, ()),
                    ),
                    assignment=assignment,
                    location=location,
                )
            )
    return tuple(candidates)


def _contextual_slots(
    candidates: tuple[_CandidateResource, ...],
    *,
    query: FindAppointmentSlotsQuery,
    ordinals: list[int],
    step_minutes: int,
    window_start: object,
    window_end: object,
    base_terms: BaseBookingTerms,
    context_terms: dict[UUID, tuple[ContextTermObservation, ...]],
) -> tuple[AppointmentSlot, ...]:
    from datetime import datetime

    start = cast(datetime, window_start)
    end = cast(datetime, window_end)
    starts: dict[datetime, dict[int, list[_CandidateResource]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for candidate in candidates:
        seed_intervals = find_resource_intervals(
            candidate.profile,
            window_start=start,
            window_end=end,
            duration_minutes=step_minutes,
            step_minutes=step_minutes,
            required_quantity=candidate.quantity,
        )
        for seed in seed_intervals:
            if not candidate.assignment.contains(seed.start_at, seed.end_at):
                continue
            if not interval_is_scheduled_available(
                candidate.location.profile,
                start_at=seed.start_at,
                end_at=seed.end_at,
            ):
                continue
            starts[seed.start_at][candidate.ordinal].append(candidate)

    slots: list[AppointmentSlot] = []
    for start_at in sorted(starts):
        by_ordinal = starts[start_at]
        if any(ordinal not in by_ordinal for ordinal in ordinals):
            continue
        choices_by_requirement = [
            sorted(
                by_ordinal[ordinal],
                key=lambda candidate: (
                    str(candidate.resource_id),
                    str(candidate.assignment.id),
                ),
            )
            for ordinal in ordinals
        ]
        for combination in product(*choices_by_requirement):
            location_id = _slot_location(query.location_id, combination)
            slot = _contextual_slot(
                combination,
                offering_version_id=query.offering_version_id,
                requested_location_id=location_id,
                start_at=start_at,
                window_end=end,
                base_terms=base_terms,
                context_terms=context_terms,
            )
            if slot is None:
                continue
            slots.append(slot)
            if len(slots) >= query.limit:
                return tuple(slots)
    return tuple(slots)


def _contextual_slot(
    combination: tuple[_CandidateResource, ...],
    *,
    offering_version_id: UUID,
    requested_location_id: UUID | None,
    start_at: object,
    window_end: object,
    base_terms: BaseBookingTerms,
    context_terms: dict[UUID, tuple[ContextTermObservation, ...]],
) -> AppointmentSlot | None:
    from datetime import datetime

    start = cast(datetime, start_at)
    end_limit = cast(datetime, window_end)
    if requested_location_id is None:
        return None

    context_observations = tuple(
        effective_context_terms(context_terms.get(candidate.assignment.id, ()), start)
        for candidate in combination
    )
    try:
        resolved = resolve_booking_terms(base_terms, context_observations)
    except (MissingCommercialTerms, ConflictingContextualTerms, ContextNotBookable):
        return None

    interval = AvailableInterval(
        start,
        start + timedelta(minutes=resolved.planned_duration_minutes),
    )
    if interval.end_at > end_limit:
        return None
    if not _combination_exactly_available(combination, interval):
        return None

    location_observation = _contextual_location(combination, requested_location_id)
    if location_observation is None:
        return None
    resources = tuple(
        ResourceChoice(
            requirement_id=candidate.requirement_id,
            resource_id=candidate.resource_id,
            resource_location_assignment_id=candidate.assignment.id,
            assignment_revision=candidate.assignment.revision,
            availability_revision=candidate.availability_revision,
        )
        for candidate in combination
    )
    fingerprint = _configuration_fingerprint(
        offering_version_id=offering_version_id,
        location=location_observation,
        combination=combination,
        resolved=resolved,
        context_observations=context_observations,
    )
    return AppointmentSlot(
        offering_version_id=offering_version_id,
        start_at=interval.start_at,
        end_at=interval.end_at,
        location_id=requested_location_id,
        resources=resources,
        planned_duration_minutes=resolved.planned_duration_minutes,
        amount=resolved.amount,
        currency=resolved.currency,
        location_operational_revision=location_observation.operational_revision,
        configuration_fingerprint=fingerprint,
    )


def _combination_exactly_available(
    combination: tuple[_CandidateResource, ...],
    interval: AvailableInterval,
) -> bool:
    by_resource: dict[UUID, list[_CandidateResource]] = defaultdict(list)
    for candidate in combination:
        if not interval_is_scheduled_available(
            candidate.profile,
            start_at=interval.start_at,
            end_at=interval.end_at,
        ):
            return False
        if not candidate.assignment.contains(interval.start_at, interval.end_at):
            return False
        if not interval_is_scheduled_available(
            candidate.location.profile,
            start_at=interval.start_at,
            end_at=interval.end_at,
        ):
            return False
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
        if any(candidate.location_id != requested_location_id for candidate in combination):
            return None
        return requested_location_id
    locations = {candidate.location_id for candidate in combination}
    return next(iter(locations)) if len(locations) == 1 else None


def _contextual_location(
    combination: tuple[_CandidateResource, ...],
    location_id: UUID,
) -> LocationObservation | None:
    observations = {candidate.location for candidate in combination}
    if len(observations) != 1:
        return None
    observation = next(iter(observations))
    return observation if observation.id == location_id else None


def _configuration_fingerprint(
    *,
    offering_version_id: UUID,
    location: LocationObservation,
    combination: tuple[_CandidateResource, ...],
    resolved: ResolvedBookingTerms,
    context_observations: tuple[ContextBookingTerms | None, ...],
) -> str:
    contexts: list[dict[str, object] | None] = []
    for observation in context_observations:
        if observation is None:
            contexts.append(None)
        else:
            contexts.append({"id": str(observation.id), "revision": observation.revision})

    payload = {
        "offering_version_id": str(offering_version_id),
        "location_id": str(location.id),
        "location_operational_revision": location.operational_revision,
        "resources": [
            {
                "requirement_id": str(candidate.requirement_id),
                "resource_id": str(candidate.resource_id),
                "availability_revision": candidate.availability_revision,
                "assignment_id": str(candidate.assignment.id),
                "assignment_revision": candidate.assignment.revision,
            }
            for candidate in combination
        ],
        "base_terms_id": str(resolved.base_source_id) if resolved.base_source_id else None,
        "contexts": contexts,
        "amount": str(resolved.amount),
        "currency": resolved.currency,
        "planned_duration_minutes": resolved.planned_duration_minutes,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
