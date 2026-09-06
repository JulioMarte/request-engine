import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import product
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_supply import (
    load_assignment_exceptions,
    load_assignment_schedules,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    load_bookable_offering,
    load_requirements,
    lock_resource_ids,
    lock_resources,
    read_reservation,
    revalidate_exact_slot,
    validate_resource_capabilities,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
)
from request_engine.modules.booking.application.errors import (
    AppointmentUnavailable,
    BookingConfigurationError,
    CapacityHoldExpired,
    CapacityHoldNotActive,
    CapacityHoldNotFound,
    InvalidHoldExpiration,
)
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice
from request_engine.modules.booking.contracts.holds import CapacityHold, CapacityHoldStatus
from request_engine.modules.booking.contracts.slot_offer_capacity import (
    AcquireSlotOfferHold,
    ConsumeSlotOfferHold,
    ReleaseSlotOfferHold,
    SlotOfferCandidatePreferenceUnavailable,
    SlotOfferCapacityPort,
    SlotOfferCapacityUnavailable,
)
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


@dataclass(frozen=True, slots=True)
class _Candidate:
    requirement_id: UUID
    ordinal: int
    quantity: int
    resource_id: UUID
    assignment_id: UUID
    assignment_revision: int
    profile: ResourceAvailability


class PostgresSlotOfferCapacity(SlotOfferCapacityPort):
    """Booking-owned capacity primitives used by queue offer orchestration."""

    async def acquire_slot_offer_hold(
        self,
        transaction: object,
        request: AcquireSlotOfferHold,
    ) -> CapacityHold:
        session = _session(transaction)
        start_at = require_aware_utc(request.start_at, "start_at")
        end_at = require_aware_utc(request.end_at, "end_at")
        expires_at = require_aware_utc(request.expires_at, "expires_at")
        if request.location_id is None:
            raise SlotOfferCapacityUnavailable("SlotOpportunity requires a Location")
        now = cast(datetime, (await session.execute(text("SELECT clock_timestamp()"))).scalar_one())
        if expires_at <= now:
            raise InvalidHoldExpiration()

        offering = await load_bookable_offering(
            session,
            request.organization_id,
            request.offering_version_id,
        )
        duration_minutes = cast(int, offering["duration_minutes"])
        if int((end_at - start_at).total_seconds()) != duration_minutes * 60:
            raise BookingConfigurationError(
                "SlotOpportunity interval does not match OfferingVersion duration"
            )
        policy = cast(dict[str, object], offering["booking_policy"])
        step_minutes = slot_step_minutes(policy, duration_minutes)
        requirements = await load_requirements(
            session,
            request.organization_id,
            request.offering_version_id,
        )

        candidate_rows = (
            (
                await session.execute(
                    text(
                        """
                        SELECT rr.id AS requirement_id,
                               rr.ordinal,
                               rr.quantity,
                               r.id AS resource_id,
                               r.capacity_model,
                               r.capacity_units,
                               rla.id AS assignment_id,
                               rla.revision AS assignment_revision,
                               l.timezone AS location_timezone
                        FROM request_engine.offering_resource_requirements rr
                        JOIN request_engine.resource_capability_assignments a
                          ON a.organization_id = rr.organization_id
                         AND a.capability_id = rr.capability_id
                        JOIN request_engine.resources r
                          ON r.organization_id = a.organization_id
                         AND r.id = a.resource_id
                        JOIN request_engine.resource_location_assignments rla
                          ON rla.organization_id = r.organization_id
                         AND rla.resource_id = r.id
                         AND rla.location_id = :location_id
                         AND rla.effective_during @> CAST(:start_at AS timestamptz)
                         AND (
                             upper_inf(rla.effective_during)
                             OR upper(rla.effective_during) >= CAST(:end_at AS timestamptz)
                         )
                        JOIN request_engine.locations l
                          ON l.organization_id = rla.organization_id
                         AND l.id = rla.location_id
                         AND l.active
                        WHERE rr.organization_id = :organization_id
                          AND rr.offering_version_id = :offering_version_id
                          AND r.active
                        ORDER BY rr.ordinal, r.id, rla.id
                        """
                    ),
                    {
                        "organization_id": request.organization_id,
                        "offering_version_id": request.offering_version_id,
                        "location_id": request.location_id,
                        "start_at": start_at,
                        "end_at": end_at,
                    },
                )
            )
            .mappings()
            .all()
        )
        if not candidate_rows:
            raise SlotOfferCapacityUnavailable("no eligible Resources exist for SlotOpportunity")

        resource_ids = tuple(
            sorted({cast(UUID, row["resource_id"]) for row in candidate_rows}, key=str)
        )
        assignment_ids = tuple(
            sorted({cast(UUID, row["assignment_id"]) for row in candidate_rows}, key=str)
        )
        assignment_schedules = await load_assignment_schedules(
            session, request.organization_id, assignment_ids
        )
        assignment_exceptions = await load_assignment_exceptions(
            session,
            request.organization_id,
            assignment_ids,
            start_at,
            end_at,
        )
        exceptions = await load_resource_exceptions(
            session,
            request.organization_id,
            resource_ids,
            start_at,
            end_at,
        )
        live_claims = await load_live_capacity_claims(
            session,
            request.organization_id,
            resource_ids,
            start_at,
            end_at,
        )
        candidates = _build_candidates(
            candidate_rows,
            assignment_schedules=assignment_schedules,
            assignment_exceptions=assignment_exceptions,
            exceptions=exceptions,
            live_claims=live_claims,
        )
        interval = AvailableInterval(start_at, end_at)
        by_ordinal: dict[int, list[_Candidate]] = defaultdict(list)
        for candidate in candidates:
            intervals = find_resource_intervals(
                candidate.profile,
                window_start=start_at,
                window_end=end_at,
                duration_minutes=duration_minutes,
                step_minutes=step_minutes,
                required_quantity=candidate.quantity,
            )
            if interval in intervals:
                by_ordinal[candidate.ordinal].append(candidate)

        ordinals = sorted(requirement.ordinal for requirement in requirements.values())
        if any(not by_ordinal[ordinal] for ordinal in ordinals):
            raise SlotOfferCapacityUnavailable("SlotOpportunity no longer has complete capacity")

        choice_groups = [
            sorted(
                by_ordinal[ordinal],
                key=lambda value: (str(value.resource_id), str(value.assignment_id)),
            )
            for ordinal in ordinals
        ]
        all_available: list[tuple[_Candidate, ...]] = []
        for raw_combination in product(*choice_groups):
            combination = tuple(raw_combination)
            if _combination_has_capacity(combination, interval):
                all_available.append(combination)
        if not all_available:
            raise SlotOfferCapacityUnavailable("SlotOpportunity no longer has eligible capacity")

        eligible_combinations = [
            combination
            for combination in all_available
            if request.preferred_resource_id is None
            or any(value.resource_id == request.preferred_resource_id for value in combination)
        ]
        if not eligible_combinations:
            raise SlotOfferCandidatePreferenceUnavailable(
                "candidate preferred Resource is not available for this slot"
            )

        for selected in eligible_combinations:
            try:
                async with session.begin_nested():
                    choices_tuple = tuple(
                        ResourceChoice(
                            candidate.requirement_id,
                            candidate.resource_id,
                            candidate.assignment_id,
                            candidate.assignment_revision,
                        )
                        for candidate in selected
                    )
                    choices = {choice.requirement_id: choice for choice in choices_tuple}
                    resources = await lock_resources(
                        session,
                        organization_id=request.organization_id,
                        resource_ids=tuple(choice.resource_id for choice in choices_tuple),
                    )
                    await validate_resource_capabilities(
                        session,
                        organization_id=request.organization_id,
                        requirements=requirements,
                        choices=choices,
                        resources=resources,
                        location_id=None,
                    )
                    await _lock_assignments(
                        session,
                        organization_id=request.organization_id,
                        location_id=request.location_id,
                        selected=selected,
                        start_at=start_at,
                        end_at=end_at,
                    )
                    locked_profiles = await _load_selected_profiles(
                        session,
                        organization_id=request.organization_id,
                        selected=selected,
                        start_at=start_at,
                        end_at=end_at,
                    )
                    revalidate_exact_slot(
                        requirements=requirements,
                        choices=choices,
                        profiles=locked_profiles,
                        start_at=start_at,
                        end_at=end_at,
                        duration_minutes=duration_minutes,
                        step_minutes=step_minutes,
                    )

                    hold_id = cast(
                        UUID,
                        (
                            await session.execute(
                                text(
                                    """
                                    INSERT INTO request_engine.capacity_holds (
                                        organization_id,
                                        offering_version_id,
                                        subject_party_id,
                                        location_id,
                                        during,
                                        expires_at
                                    ) VALUES (
                                        :organization_id,
                                        :offering_version_id,
                                        :subject_party_id,
                                        :location_id,
                                        tstzrange(:start_at, :end_at, '[)'),
                                        :expires_at
                                    )
                                    RETURNING id
                                    """
                                ),
                                {
                                    "organization_id": request.organization_id,
                                    "offering_version_id": request.offering_version_id,
                                    "subject_party_id": request.subject_party_id,
                                    "location_id": request.location_id,
                                    "start_at": start_at,
                                    "end_at": end_at,
                                    "expires_at": expires_at,
                                },
                            )
                        ).scalar_one(),
                    )
                    selected_by_requirement = {
                        candidate.requirement_id: candidate for candidate in selected
                    }
                    for requirement in sorted(requirements.values(), key=lambda item: item.ordinal):
                        candidate = selected_by_requirement[requirement.id]
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.capacity_claims (
                                    organization_id,
                                    resource_id,
                                    requirement_id,
                                    hold_id,
                                    resource_location_assignment_id,
                                    during,
                                    quantity
                                ) VALUES (
                                    :organization_id,
                                    :resource_id,
                                    :requirement_id,
                                    :hold_id,
                                    :assignment_id,
                                    tstzrange(:start_at, :end_at, '[)'),
                                    :quantity
                                )
                                """
                            ),
                            {
                                "organization_id": request.organization_id,
                                "resource_id": candidate.resource_id,
                                "requirement_id": requirement.id,
                                "hold_id": hold_id,
                                "assignment_id": candidate.assignment_id,
                                "start_at": start_at,
                                "end_at": end_at,
                                "quantity": requirement.quantity,
                            },
                        )
                    hold = await _read_hold(session, request.organization_id, hold_id)
            except AppointmentUnavailable:
                continue
            except IntegrityError as exc:
                if _is_capacity_conflict(exc):
                    continue
                raise
            else:
                return hold

        raise SlotOfferCapacityUnavailable("SlotOpportunity no longer has eligible capacity")

    async def consume_slot_offer_hold(
        self,
        transaction: object,
        request: ConsumeSlotOfferHold,
    ) -> Reservation:
        session = _session(transaction)
        hold_row = await _lock_hold(session, request.organization_id, request.hold_id)
        _assert_live_hold(hold_row, request.hold_id)
        resource_ids = await _active_owner_resource_ids(
            session,
            request.organization_id,
            hold_id=request.hold_id,
        )
        await lock_resource_ids(session, request.organization_id, resource_ids)
        hold_row = await _read_locked_hold(session, request.organization_id, request.hold_id)
        _assert_live_hold(hold_row, request.hold_id)

        offering = await load_bookable_offering(
            session,
            request.organization_id,
            cast(UUID, hold_row["offering_version_id"]),
        )
        booking_policy = cast(dict[str, object], offering["booking_policy"])
        reservation_id = cast(
            UUID,
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.reservations (
                            organization_id,
                            offering_version_id,
                            subject_party_id,
                            location_id,
                            during,
                            booking_policy_snapshot
                        ) VALUES (
                            :organization_id,
                            :offering_version_id,
                            :subject_party_id,
                            :location_id,
                            :during,
                            CAST(:booking_policy AS jsonb)
                        )
                        RETURNING id
                        """
                    ),
                    {
                        "organization_id": request.organization_id,
                        "offering_version_id": hold_row["offering_version_id"],
                        "subject_party_id": hold_row["subject_party_id"],
                        "location_id": hold_row["location_id"],
                        "during": hold_row["during"],
                        "booking_policy": json.dumps(booking_policy, separators=(",", ":")),
                    },
                )
            ).scalar_one(),
        )
        await session.execute(
            text(
                """
                UPDATE request_engine.capacity_claims
                SET reservation_id = :reservation_id,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND hold_id = :hold_id
                  AND reservation_id IS NULL
                  AND status = 'active'
                """
            ),
            {
                "organization_id": request.organization_id,
                "hold_id": request.hold_id,
                "reservation_id": reservation_id,
            },
        )
        await session.execute(
            text(
                """
                UPDATE request_engine.capacity_holds
                SET status = 'consumed',
                    revision = revision + 1,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND id = :hold_id
                  AND status = 'active'
                """
            ),
            {"organization_id": request.organization_id, "hold_id": request.hold_id},
        )
        return await read_reservation(session, request.organization_id, reservation_id)

    async def release_slot_offer_hold(
        self,
        transaction: object,
        request: ReleaseSlotOfferHold,
    ) -> CapacityHold:
        session = _session(transaction)
        hold_row = await _lock_hold(session, request.organization_id, request.hold_id)
        current_status = cast(str, hold_row["status"])
        if current_status == request.terminal_status:
            return _hold_from_row(hold_row)
        if current_status != "active":
            raise CapacityHoldNotActive(request.hold_id, current_status)

        resource_ids = await _active_owner_resource_ids(
            session,
            request.organization_id,
            hold_id=request.hold_id,
        )
        await lock_resource_ids(session, request.organization_id, resource_ids)
        await session.execute(
            text(
                """
                UPDATE request_engine.capacity_claims
                SET status = 'released',
                    released_at = clock_timestamp(),
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND hold_id = :hold_id
                  AND reservation_id IS NULL
                  AND status = 'active'
                """
            ),
            {"organization_id": request.organization_id, "hold_id": request.hold_id},
        )
        await session.execute(
            text(
                """
                UPDATE request_engine.capacity_holds
                SET status = :terminal_status,
                    revision = revision + 1,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND id = :hold_id
                  AND status = 'active'
                """
            ),
            {
                "organization_id": request.organization_id,
                "hold_id": request.hold_id,
                "terminal_status": request.terminal_status,
            },
        )
        return await _read_hold(session, request.organization_id, request.hold_id)


def _session(transaction: object) -> AsyncSession:
    if not isinstance(transaction, AsyncSession):
        raise TypeError("slot-offer capacity transaction must be an AsyncSession")
    return transaction


def _is_capacity_conflict(exc: IntegrityError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "23P01"


def _build_candidates(
    rows: Sequence[RowMapping],
    *,
    assignment_schedules: dict[UUID, tuple[RecurringAvailability, ...]],
    assignment_exceptions: dict[UUID, tuple[AvailabilityException, ...]],
    exceptions: dict[UUID, tuple[AvailabilityException, ...]],
    live_claims: dict[UUID, tuple[LiveCapacityClaim, ...]],
) -> tuple[_Candidate, ...]:
    result: list[_Candidate] = []
    for row in rows:
        resource_id = cast(UUID, row["resource_id"])
        assignment_id = cast(UUID, row["assignment_id"])
        result.append(
            _Candidate(
                requirement_id=cast(UUID, row["requirement_id"]),
                ordinal=cast(int, row["ordinal"]),
                quantity=cast(int, row["quantity"]),
                resource_id=resource_id,
                assignment_id=assignment_id,
                assignment_revision=cast(int, row["assignment_revision"]),
                profile=ResourceAvailability(
                    capacity_model=CapacityModel(cast(str, row["capacity_model"])),
                    capacity_units=cast(int, row["capacity_units"]),
                    default_timezone=cast(str, row["location_timezone"]),
                    schedules=assignment_schedules.get(assignment_id, ()),
                    exceptions=exceptions.get(resource_id, ())
                    + assignment_exceptions.get(assignment_id, ()),
                    live_claims=live_claims.get(resource_id, ()),
                ),
            )
        )
    return tuple(result)


def _combination_has_capacity(
    combination: tuple[_Candidate, ...],
    interval: AvailableInterval,
) -> bool:
    grouped: dict[UUID, list[_Candidate]] = defaultdict(list)
    for candidate in combination:
        grouped[candidate.resource_id].append(candidate)
    for values in grouped.values():
        profile = values[0].profile
        if profile.capacity_model is CapacityModel.EXCLUSIVE and len(values) > 1:
            return False
        required_quantity = sum(value.quantity for value in values)
        if not interval_has_resource_capacity(
            profile,
            start_at=interval.start_at,
            end_at=interval.end_at,
            required_quantity=required_quantity,
        ):
            return False
    return True


async def _lock_assignments(
    session: AsyncSession,
    *,
    organization_id: UUID,
    location_id: UUID,
    selected: tuple[_Candidate, ...],
    start_at: datetime,
    end_at: datetime,
) -> None:
    expected = {candidate.assignment_id: candidate.assignment_revision for candidate in selected}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, revision, location_id, effective_during
                    FROM request_engine.resource_location_assignments
                    WHERE organization_id = :organization_id
                      AND id = ANY(CAST(:assignment_ids AS uuid[]))
                    ORDER BY id
                    FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "assignment_ids": [str(value) for value in sorted(expected, key=str)],
                },
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(expected):
        raise AppointmentUnavailable("ResourceLocationAssignment changed")
    for row in rows:
        assignment_id = cast(UUID, row["id"])
        if cast(UUID, row["location_id"]) != location_id:
            raise AppointmentUnavailable("ResourceLocationAssignment changed")
        if cast(int, row["revision"]) != expected[assignment_id]:
            raise AppointmentUnavailable("ResourceLocationAssignment changed")
        during = row["effective_during"]
        if start_at not in during or (during.upper is not None and during.upper < end_at):
            raise AppointmentUnavailable("ResourceLocationAssignment changed")


async def _load_selected_profiles(
    session: AsyncSession,
    *,
    organization_id: UUID,
    selected: tuple[_Candidate, ...],
    start_at: datetime,
    end_at: datetime,
) -> dict[UUID, ResourceAvailability]:
    resource_ids = tuple(sorted({candidate.resource_id for candidate in selected}, key=str))
    assignment_ids = tuple(sorted({candidate.assignment_id for candidate in selected}, key=str))
    schedules = await load_assignment_schedules(session, organization_id, assignment_ids)
    assignment_exceptions = await load_assignment_exceptions(
        session, organization_id, assignment_ids, start_at, end_at
    )
    broad_exceptions = await load_resource_exceptions(
        session, organization_id, resource_ids, start_at, end_at
    )
    claims = await load_live_capacity_claims(
        session, organization_id, resource_ids, start_at, end_at
    )
    profiles: dict[UUID, ResourceAvailability] = {}
    for candidate in selected:
        if candidate.resource_id in profiles:
            continue
        profiles[candidate.resource_id] = ResourceAvailability(
            capacity_model=candidate.profile.capacity_model,
            capacity_units=candidate.profile.capacity_units,
            default_timezone=candidate.profile.default_timezone,
            schedules=schedules.get(candidate.assignment_id, ()),
            exceptions=broad_exceptions.get(candidate.resource_id, ())
            + assignment_exceptions.get(candidate.assignment_id, ()),
            live_claims=claims.get(candidate.resource_id, ()),
        )
    return profiles


async def _lock_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> RowMapping:
    row = await _read_hold_row(session, organization_id, hold_id, lock=True)
    if row is None:
        raise CapacityHoldNotFound(hold_id)
    return row


async def _read_locked_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> RowMapping:
    row = await _read_hold_row(session, organization_id, hold_id, lock=False)
    if row is None:
        raise CapacityHoldNotFound(hold_id)
    return row


async def _read_hold_row(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
    *,
    lock: bool,
) -> RowMapping | None:
    suffix = " FOR UPDATE" if lock else ""
    query = text(
        """
        SELECT id, offering_version_id, subject_party_id, location_id,
               during, lower(during) AS start_at, upper(during) AS end_at,
               status, expires_at, revision, clock_timestamp() AS db_now
        FROM request_engine.capacity_holds
        WHERE organization_id = :organization_id
          AND id = :hold_id
        """
        + suffix
    )
    return (
        (
            await session.execute(
                query,
                {"organization_id": organization_id, "hold_id": hold_id},
            )
        )
        .mappings()
        .first()
    )


def _assert_live_hold(row: RowMapping, hold_id: UUID) -> None:
    status = cast(str, row["status"])
    if status != "active":
        raise CapacityHoldNotActive(hold_id, status)
    if cast(datetime, row["expires_at"]) <= cast(datetime, row["db_now"]):
        raise CapacityHoldExpired(hold_id)


async def _active_owner_resource_ids(
    session: AsyncSession,
    organization_id: UUID,
    *,
    hold_id: UUID,
) -> tuple[UUID, ...]:
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT resource_id
                FROM request_engine.capacity_claims
                WHERE organization_id = :organization_id
                  AND hold_id = :hold_id
                  AND reservation_id IS NULL
                  AND status = 'active'
                ORDER BY resource_id
                """
            ),
            {"organization_id": organization_id, "hold_id": hold_id},
        )
    ).all()
    resource_ids = tuple(cast(UUID, row[0]) for row in rows)
    if not resource_ids:
        raise BookingConfigurationError(f"CapacityHold {hold_id} has no active claims")
    return resource_ids


async def _read_hold(
    session: AsyncSession,
    organization_id: UUID,
    hold_id: UUID,
) -> CapacityHold:
    row = await _read_hold_row(session, organization_id, hold_id, lock=False)
    if row is None:
        raise CapacityHoldNotFound(hold_id)
    return _hold_from_row(row)


def _hold_from_row(row: RowMapping) -> CapacityHold:
    return CapacityHold(
        id=cast(UUID, row["id"]),
        offering_version_id=cast(UUID, row["offering_version_id"]),
        subject_party_id=cast(UUID, row["subject_party_id"]),
        location_id=cast(UUID | None, row["location_id"]),
        start_at=cast(datetime, row["start_at"]),
        end_at=cast(datetime, row["end_at"]),
        expires_at=cast(datetime, row["expires_at"]),
        status=CapacityHoldStatus(cast(str, row["status"])),
        revision=cast(int, row["revision"]),
    )
