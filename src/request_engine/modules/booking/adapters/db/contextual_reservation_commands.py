import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
from request_engine.modules.booking.adapters.db.reservation_commands import (
    LockedResource,
    PostgresReservationCommands,
    load_bookable_offering,
    load_requirements,
    lock_resources,
    read_reservation,
    reservation_from_json,
    reservation_to_json,
    revalidate_exact_slot,
    validate_choice_cardinality,
    validate_resource_capabilities,
    validate_subject_location_and_origin,
)
from request_engine.modules.booking.adapters.db.resource_availability import (
    load_live_capacity_claims,
    load_resource_exceptions,
)
from request_engine.modules.booking.adapters.db.subject_authority import require_subject_authority
from request_engine.modules.booking.application.authority import BOOK_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
)
from request_engine.modules.booking.application.commands.cancel_reservation import (
    CancelReservationCommand,
)
from request_engine.modules.booking.application.errors import (
    AppointmentOptionStale,
    InvalidResourceSelection,
)
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice
from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    LiveCapacityClaim,
    RecurringAvailability,
    ResourceAvailability,
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
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.outbox.postgres import append_outbox


class _RequirementLike(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def ordinal(self) -> int: ...


@dataclass(frozen=True, slots=True)
class _ExpectedContext:
    duration_minutes: int
    amount: Decimal
    currency: str
    location_revision: int
    configuration_fingerprint: str


class PostgresContextualReservationCommands:
    """Authoritative booking over assignment-backed contextual supply."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._reservation_lifecycle = PostgresReservationCommands(session_factory)

    async def book_appointment(self, command: BookAppointmentCommand) -> Reservation:
        return await self._book_contextual(command)

    async def cancel_reservation(self, command: CancelReservationCommand) -> Reservation:
        return await self._reservation_lifecycle.cancel_reservation(command)

    async def _book_contextual(self, command: BookAppointmentCommand) -> Reservation:
        expected = _expected_context(command)
        start_at = require_aware_utc(command.start_at, "start_at")
        end_at = start_at + timedelta(minutes=expected.duration_minutes)
        idempotency_fingerprint = _contextual_command_fingerprint(command, start_at, expected)

        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.book_appointment",
                idempotency_key=command.idempotency_key,
                fingerprint=idempotency_fingerprint,
            )
            if replay is not None:
                return reservation_from_json(cast(dict[str, object], replay["reservation"]))

            await _lock_offering_version(
                session,
                organization_id=command.organization_id,
                offering_version_id=command.offering_version_id,
            )
            offering = await load_bookable_offering(
                session,
                command.organization_id,
                command.offering_version_id,
            )
            base_duration = cast(int, offering["duration_minutes"])
            policy = cast(dict[str, object], offering["booking_policy"])
            step_minutes = slot_step_minutes(policy, base_duration)

            await validate_subject_location_and_origin(
                session,
                organization_id=command.organization_id,
                subject_party_id=command.subject_party_id,
                location_id=command.location_id,
                origin_request_id=command.origin_request_id,
            )
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=command.subject_party_id,
                scope_key=BOOK_APPOINTMENT_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )

            location_id = command.location_id
            await _lock_expected_location(
                session,
                organization_id=command.organization_id,
                location_id=location_id,
                expected_revision=expected.location_revision,
            )

            requirements = await load_requirements(
                session,
                command.organization_id,
                command.offering_version_id,
            )
            choices = validate_choice_cardinality(requirements, command.resources)
            resources = await lock_resources(
                session,
                organization_id=command.organization_id,
                resource_ids=tuple(choice.resource_id for choice in choices.values()),
            )
            await validate_resource_capabilities(
                session,
                organization_id=command.organization_id,
                requirements=requirements,
                choices=choices,
                resources=resources,
                location_id=None,
            )

            await _lock_selected_assignments(
                session,
                organization_id=command.organization_id,
                choices=choices,
            )
            current_availability_revisions = await _load_resource_availability_revisions(
                session,
                organization_id=command.organization_id,
                resource_ids=tuple(resources),
            )
            _require_expected_resource_revisions(choices, current_availability_revisions)

            _, assignments_by_resource = await load_contextualization(
                session,
                command.organization_id,
                tuple(sorted(resources, key=str)),
                start_at,
                end_at,
            )
            selected_assignments = _resolve_selected_assignments(
                choices=choices,
                requirements=requirements,
                assignments_by_resource=assignments_by_resource,
                location_id=location_id,
                start_at=start_at,
                end_at=end_at,
            )
            assignment_ids = tuple(
                sorted({assignment.id for assignment in selected_assignments.values()}, key=str)
            )

            assignment_schedules = await load_assignment_schedules(
                session,
                command.organization_id,
                assignment_ids,
            )
            assignment_exceptions = await load_assignment_exceptions(
                session,
                command.organization_id,
                assignment_ids,
                start_at,
                end_at,
            )
            broad_exceptions = await load_resource_exceptions(
                session,
                command.organization_id,
                tuple(sorted(resources, key=str)),
                start_at,
                end_at,
            )
            live_claims = await load_live_capacity_claims(
                session,
                command.organization_id,
                tuple(sorted(resources, key=str)),
                start_at,
                end_at,
            )
            locations = await load_location_observations(
                session,
                command.organization_id,
                (location_id,),
                start_at,
                end_at,
            )
            location = locations.get(location_id)
            if location is None or location.operational_revision != expected.location_revision:
                raise AppointmentOptionStale()

            base_terms, context_terms = await load_booking_terms(
                session,
                command.organization_id,
                command.offering_version_id,
                assignment_ids,
                base_duration,
                start_at,
                end_at,
            )
            ordered_requirement_ids = tuple(
                requirement.id
                for requirement in sorted(requirements.values(), key=lambda row: row.ordinal)
            )
            context_observations = _effective_context_observations(
                ordered_requirement_ids,
                selected_assignments,
                context_terms,
                start_at,
            )
            try:
                resolved = resolve_booking_terms(base_terms, context_observations)
            except (MissingCommercialTerms, ConflictingContextualTerms, ContextNotBookable) as exc:
                raise AppointmentOptionStale() from exc

            if (
                resolved.amount != expected.amount
                or resolved.currency != expected.currency
                or resolved.planned_duration_minutes != expected.duration_minutes
            ):
                raise AppointmentOptionStale()

            authoritative_end = start_at + timedelta(minutes=resolved.planned_duration_minutes)
            if authoritative_end != end_at:
                raise AppointmentOptionStale()
            if not interval_is_scheduled_available(
                location.profile,
                start_at=start_at,
                end_at=end_at,
            ):
                raise AppointmentOptionStale("Location operational availability changed")

            profiles = _build_authoritative_profiles(
                ordered_requirement_ids=ordered_requirement_ids,
                choices=choices,
                selected_assignments=selected_assignments,
                resources=resources,
                location=location,
                assignment_schedules=assignment_schedules,
                assignment_exceptions=assignment_exceptions,
                broad_exceptions=broad_exceptions,
                live_claims=live_claims,
            )
            revalidate_exact_slot(
                requirements=requirements,
                choices=choices,
                profiles=profiles,
                start_at=start_at,
                end_at=end_at,
                duration_minutes=resolved.planned_duration_minutes,
                step_minutes=step_minutes,
            )

            authoritative_fingerprint = _configuration_fingerprint(
                offering_version_id=command.offering_version_id,
                location=location,
                ordered_requirement_ids=ordered_requirement_ids,
                choices=choices,
                resources=resources,
                current_availability_revisions=current_availability_revisions,
                selected_assignments=selected_assignments,
                base_terms=base_terms,
                context_observations=context_observations,
                resolved=resolved,
            )
            if authoritative_fingerprint != expected.configuration_fingerprint:
                raise AppointmentOptionStale()

            reservation_id = await _insert_contextual_reservation(
                session,
                command=command,
                location_id=location_id,
                start_at=start_at,
                end_at=end_at,
                booking_policy=policy,
            )
            await _insert_contextual_claims(
                session,
                organization_id=command.organization_id,
                reservation_id=reservation_id,
                requirements=requirements,
                choices=choices,
                selected_assignments=selected_assignments,
                start_at=start_at,
                end_at=end_at,
            )

            context_source_ids = tuple(
                sorted(
                    {
                        observation.id
                        for observation in context_observations
                        if observation is not None
                    },
                    key=str,
                )
            )
            await _insert_commercial_commitment(
                session,
                organization_id=command.organization_id,
                reservation_id=reservation_id,
                base_terms=base_terms,
                context_source_ids=context_source_ids,
                resolved=resolved,
                configuration_fingerprint=authoritative_fingerprint,
            )

            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.book_appointment",
                aggregate_kind="Reservation",
                aggregate_id=reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "offering_version_id": str(command.offering_version_id),
                    "subject_party_id": str(command.subject_party_id),
                    "subject_authority": authority.audit_details(),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "location_id": str(location_id),
                    "resource_ids": [str(choice.resource_id) for choice in choices.values()],
                    "amount": str(resolved.amount),
                    "currency": resolved.currency,
                    "planned_duration_minutes": resolved.planned_duration_minutes,
                    "configuration_fingerprint": authoritative_fingerprint,
                    "contextual": True,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.created.v1",
                aggregate_kind="Reservation",
                aggregate_id=reservation_id,
                payload={
                    "reservation_id": str(reservation_id),
                    "offering_version_id": str(command.offering_version_id),
                    "subject_party_id": str(command.subject_party_id),
                    "location_id": str(location_id),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                },
            )
            reservation = await read_reservation(
                session,
                command.organization_id,
                reservation_id,
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reservation": reservation_to_json(reservation)},
            )
            return reservation


def _expected_context(command: BookAppointmentCommand) -> _ExpectedContext:
    duration = command.expected_planned_duration_minutes
    amount = command.expected_amount
    currency = command.expected_currency
    location_revision = command.expected_location_operational_revision
    fingerprint = command.expected_configuration_fingerprint
    if duration <= 0:
        raise InvalidResourceSelection("contextual option has invalid planned duration")
    if amount < 0:
        raise InvalidResourceSelection("contextual option has invalid amount")
    if not currency:
        raise InvalidResourceSelection("contextual option has invalid currency")
    if location_revision <= 0:
        raise InvalidResourceSelection("contextual option has invalid Location revision")
    if not fingerprint:
        raise InvalidResourceSelection("contextual option is missing configuration fingerprint")
    return _ExpectedContext(
        duration_minutes=duration,
        amount=amount,
        currency=currency,
        location_revision=location_revision,
        configuration_fingerprint=fingerprint,
    )


def _contextual_command_fingerprint(
    command: BookAppointmentCommand,
    start_at: datetime,
    expected: _ExpectedContext,
) -> str:
    return command_fingerprint(
        "booking.book_appointment.contextual.v1",
        {
            "offering_version_id": command.offering_version_id,
            "subject_party_id": command.subject_party_id,
            "start_at": start_at,
            "location_id": command.location_id,
            "origin_request_id": command.origin_request_id,
            "resources": [
                {
                    "requirement_id": str(choice.requirement_id),
                    "resource_id": str(choice.resource_id),
                    "resource_location_assignment_id": (
                        str(choice.resource_location_assignment_id)
                        if choice.resource_location_assignment_id is not None
                        else None
                    ),
                    "assignment_revision": choice.assignment_revision,
                    "availability_revision": choice.availability_revision,
                }
                for choice in sorted(
                    command.resources,
                    key=lambda item: (str(item.requirement_id), str(item.resource_id)),
                )
            ],
            "expected_duration_minutes": expected.duration_minutes,
            "expected_amount": str(expected.amount),
            "expected_currency": expected.currency,
            "expected_location_revision": expected.location_revision,
            "expected_configuration_fingerprint": expected.configuration_fingerprint,
        },
    )


async def _lock_offering_version(
    session: AsyncSession,
    *,
    organization_id: UUID,
    offering_version_id: UUID,
) -> None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT ov.id, o.active AS offering_active
                    FROM request_engine.offering_versions ov
                    JOIN request_engine.offerings o
                      ON o.organization_id = ov.organization_id
                     AND o.id = ov.offering_id
                    WHERE ov.organization_id = :organization_id
                      AND ov.id = :offering_version_id
                    FOR UPDATE OF o
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
    if row is None:
        raise AppointmentOptionStale("OfferingVersion no longer exists")
    if row["offering_active"] is not True:
        raise AppointmentOptionStale("Offering is no longer active")


async def _lock_expected_location(
    session: AsyncSession,
    *,
    organization_id: UUID,
    location_id: UUID,
    expected_revision: int,
) -> None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT active, operational_revision
                    FROM request_engine.locations
                    WHERE organization_id = :organization_id
                      AND id = :location_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "location_id": location_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["active"] is not True:
        raise AppointmentOptionStale("Location is no longer active")
    if cast(int, row["operational_revision"]) != expected_revision:
        raise AppointmentOptionStale("Location operational configuration changed")


async def _lock_selected_assignments(
    session: AsyncSession,
    *,
    organization_id: UUID,
    choices: Mapping[UUID, ResourceChoice],
) -> None:
    assignment_ids = tuple(
        sorted(
            {
                choice.resource_location_assignment_id
                for choice in choices.values()
                if choice.resource_location_assignment_id is not None
            },
            key=str,
        )
    )
    if len(assignment_ids) != len(choices):
        raise InvalidResourceSelection("every ResourceChoice requires a Location assignment")
    rows = (
        await session.execute(
            text(
                """
                SELECT id
                FROM request_engine.resource_location_assignments
                WHERE organization_id = :organization_id
                  AND id = ANY(CAST(:assignment_ids AS uuid[]))
                ORDER BY id
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "assignment_ids": [str(value) for value in assignment_ids],
            },
        )
    ).all()
    if len(rows) != len(assignment_ids):
        raise AppointmentOptionStale("one or more ResourceLocationAssignments changed")


async def _load_resource_availability_revisions(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
) -> dict[UUID, int]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, availability_revision
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id
                      AND id = ANY(CAST(:resource_ids AS uuid[]))
                    ORDER BY id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_ids": [str(value) for value in resource_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    return {cast(UUID, row["id"]): cast(int, row["availability_revision"]) for row in rows}


def _require_expected_resource_revisions(
    choices: Mapping[UUID, ResourceChoice],
    current: Mapping[UUID, int],
) -> None:
    for choice in choices.values():
        expected = choice.availability_revision
        if expected is None:
            raise InvalidResourceSelection("contextual option is missing Resource revision")
        if current.get(choice.resource_id) != expected:
            raise AppointmentOptionStale("Resource availability configuration changed")


def _resolve_selected_assignments(
    *,
    choices: Mapping[UUID, ResourceChoice],
    requirements: Mapping[UUID, _RequirementLike],
    assignments_by_resource: Mapping[UUID, tuple[AssignmentObservation, ...]],
    location_id: UUID,
    start_at: datetime,
    end_at: datetime,
) -> dict[UUID, AssignmentObservation]:
    resolved: dict[UUID, AssignmentObservation] = {}
    for requirement in sorted(requirements.values(), key=lambda row: row.ordinal):
        choice = choices[requirement.id]
        assignment_id = choice.resource_location_assignment_id
        assignment_revision = choice.assignment_revision
        if assignment_id is None or assignment_revision is None:
            raise InvalidResourceSelection("assignment id and revision are required")
        assignment = next(
            (
                row
                for row in assignments_by_resource.get(choice.resource_id, ())
                if row.id == assignment_id
            ),
            None,
        )
        if (
            assignment is None
            or assignment.location_id != location_id
            or assignment.revision != assignment_revision
            or not assignment.contains(start_at, end_at)
        ):
            raise AppointmentOptionStale("ResourceLocationAssignment changed")
        resolved[requirement.id] = assignment
    return resolved


def _effective_context_observations(
    ordered_requirement_ids: tuple[UUID, ...],
    selected_assignments: Mapping[UUID, AssignmentObservation],
    context_terms: Mapping[UUID, tuple[ContextTermObservation, ...]],
    start_at: datetime,
) -> tuple[ContextBookingTerms | None, ...]:
    return tuple(
        effective_context_terms(context_terms.get(selected_assignments[rid].id, ()), start_at)
        for rid in ordered_requirement_ids
    )


def _build_authoritative_profiles(
    *,
    ordered_requirement_ids: tuple[UUID, ...],
    choices: Mapping[UUID, ResourceChoice],
    selected_assignments: Mapping[UUID, AssignmentObservation],
    resources: Mapping[UUID, LockedResource],
    location: LocationObservation,
    assignment_schedules: Mapping[UUID, tuple[RecurringAvailability, ...]],
    assignment_exceptions: Mapping[UUID, tuple[AvailabilityException, ...]],
    broad_exceptions: Mapping[UUID, tuple[AvailabilityException, ...]],
    live_claims: Mapping[UUID, tuple[LiveCapacityClaim, ...]],
) -> dict[UUID, ResourceAvailability]:
    profiles: dict[UUID, ResourceAvailability] = {}
    assignment_by_resource: dict[UUID, UUID] = {}
    for requirement_id in ordered_requirement_ids:
        choice = choices[requirement_id]
        assignment = selected_assignments[requirement_id]
        previous = assignment_by_resource.get(choice.resource_id)
        if previous is not None and previous != assignment.id:
            raise InvalidResourceSelection(
                "one Resource cannot use multiple Location assignments in one appointment"
            )
        assignment_by_resource[choice.resource_id] = assignment.id
        if choice.resource_id in profiles:
            continue

        resource = resources[choice.resource_id]
        profiles[choice.resource_id] = ResourceAvailability(
            capacity_model=resource.capacity_model,
            capacity_units=resource.capacity_units,
            default_timezone=location.timezone,
            schedules=assignment_schedules.get(assignment.id, ()),
            exceptions=broad_exceptions.get(choice.resource_id, ())
            + assignment_exceptions.get(assignment.id, ()),
            live_claims=live_claims.get(choice.resource_id, ()),
        )
    return profiles


def _configuration_fingerprint(
    *,
    offering_version_id: UUID,
    location: LocationObservation,
    ordered_requirement_ids: tuple[UUID, ...],
    choices: Mapping[UUID, ResourceChoice],
    resources: Mapping[UUID, LockedResource],
    current_availability_revisions: Mapping[UUID, int],
    selected_assignments: Mapping[UUID, AssignmentObservation],
    base_terms: BaseBookingTerms,
    context_observations: tuple[ContextBookingTerms | None, ...],
    resolved: ResolvedBookingTerms,
) -> str:
    payload = {
        "offering_version_id": str(offering_version_id),
        "location_id": str(location.id),
        "location_operational_revision": location.operational_revision,
        "resources": [
            {
                "requirement_id": str(requirement_id),
                "resource_id": str(choices[requirement_id].resource_id),
                "availability_revision": current_availability_revisions[
                    choices[requirement_id].resource_id
                ],
                "assignment_id": str(selected_assignments[requirement_id].id),
                "assignment_revision": selected_assignments[requirement_id].revision,
            }
            for requirement_id in ordered_requirement_ids
        ],
        "base_terms_id": str(base_terms.source_id) if base_terms.source_id else None,
        "contexts": [
            {"id": str(observation.id), "revision": observation.revision}
            if observation is not None
            else None
            for observation in context_observations
        ],
        "amount": str(resolved.amount),
        "currency": resolved.currency,
        "planned_duration_minutes": resolved.planned_duration_minutes,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


async def _insert_contextual_reservation(
    session: AsyncSession,
    *,
    command: BookAppointmentCommand,
    location_id: UUID,
    start_at: datetime,
    end_at: datetime,
    booking_policy: dict[str, object],
) -> UUID:
    return cast(
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
                        origin_request_id,
                        during,
                        booking_policy_snapshot
                    ) VALUES (
                        :organization_id,
                        :offering_version_id,
                        :subject_party_id,
                        :location_id,
                        :origin_request_id,
                        tstzrange(:start_at, :end_at, '[)'),
                        CAST(:booking_policy AS jsonb)
                    )
                    RETURNING id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "offering_version_id": command.offering_version_id,
                    "subject_party_id": command.subject_party_id,
                    "location_id": location_id,
                    "origin_request_id": command.origin_request_id,
                    "start_at": start_at,
                    "end_at": end_at,
                    "booking_policy": json.dumps(booking_policy, separators=(",", ":")),
                },
            )
        ).scalar_one(),
    )


async def _insert_contextual_claims(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    requirements: Mapping[UUID, _RequirementLike],
    choices: Mapping[UUID, ResourceChoice],
    selected_assignments: Mapping[UUID, AssignmentObservation],
    start_at: datetime,
    end_at: datetime,
) -> None:
    for requirement in sorted(requirements.values(), key=lambda row: row.ordinal):
        choice = choices[requirement.id]
        assignment = selected_assignments[requirement.id]
        quantity_row = await session.execute(
            text(
                """
                SELECT quantity
                FROM request_engine.offering_resource_requirements
                WHERE organization_id = :organization_id
                  AND id = :requirement_id
                """
            ),
            {
                "organization_id": organization_id,
                "requirement_id": requirement.id,
            },
        )
        quantity = cast(int, quantity_row.scalar_one())
        await session.execute(
            text(
                """
                INSERT INTO request_engine.capacity_claims (
                    organization_id,
                    resource_id,
                    requirement_id,
                    reservation_id,
                    resource_location_assignment_id,
                    during,
                    quantity
                ) VALUES (
                    :organization_id,
                    :resource_id,
                    :requirement_id,
                    :reservation_id,
                    :resource_location_assignment_id,
                    tstzrange(:start_at, :end_at, '[)'),
                    :quantity
                )
                """
            ),
            {
                "organization_id": organization_id,
                "resource_id": choice.resource_id,
                "requirement_id": requirement.id,
                "reservation_id": reservation_id,
                "resource_location_assignment_id": assignment.id,
                "start_at": start_at,
                "end_at": end_at,
                "quantity": quantity,
            },
        )


async def _insert_commercial_commitment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    base_terms: BaseBookingTerms,
    context_source_ids: tuple[UUID, ...],
    resolved: ResolvedBookingTerms,
    configuration_fingerprint: str,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO request_engine.reservation_commercial_commitments (
                reservation_id,
                organization_id,
                offering_version_booking_terms_id,
                amount,
                currency,
                planned_duration_minutes,
                configuration_fingerprint
            ) VALUES (
                :reservation_id,
                :organization_id,
                :base_terms_id,
                :amount,
                :currency,
                :planned_duration_minutes,
                :configuration_fingerprint
            )
            """
        ),
        {
            "reservation_id": reservation_id,
            "organization_id": organization_id,
            "base_terms_id": base_terms.source_id,
            "amount": resolved.amount,
            "currency": resolved.currency,
            "planned_duration_minutes": resolved.planned_duration_minutes,
            "configuration_fingerprint": configuration_fingerprint,
        },
    )
    for context_id in context_source_ids:
        await session.execute(
            text(
                """
                INSERT INTO request_engine.reservation_commercial_commitment_context_terms (
                    organization_id,
                    reservation_id,
                    booking_context_terms_id
                ) VALUES (
                    :organization_id,
                    :reservation_id,
                    :context_id
                )
                """
            ),
            {
                "organization_id": organization_id,
                "reservation_id": reservation_id,
                "context_id": context_id,
            },
        )
