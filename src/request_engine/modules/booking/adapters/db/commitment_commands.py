import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.contextual_recovery_shared import (
    build_authoritative_profiles,
    configuration_fingerprint,
    effective_context_observations,
    load_resource_availability_revisions,
    lock_selected_assignments,
    require_expected_resource_revisions,
    resolve_selected_assignments,
)
from request_engine.modules.booking.adapters.db.contextual_supply import (
    AssignmentObservation,
    load_assignment_exceptions,
    load_assignment_schedules,
    load_booking_terms,
    load_contextualization,
    load_location_observations,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    LockedResource,
    ensure_reservation_revision,
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
from request_engine.modules.booking.application.authority import MANAGE_APPOINTMENT_SCOPE
from request_engine.modules.booking.application.commands.reschedule_reservation import (
    RescheduleReservationCommand,
)
from request_engine.modules.booking.application.errors import (
    AppointmentOptionStale,
    BookingConfigurationError,
    ReservationNotFound,
    ReservationNotReschedulable,
)
from request_engine.modules.booking.contracts.appointments import Reservation, ResourceChoice
from request_engine.modules.booking.domain.availability import interval_is_scheduled_available
from request_engine.modules.booking.domain.contextual_supply import (
    ConflictingContextualTerms,
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


class PostgresBookingCommitmentCommands:
    """Authoritative contextual reservation replacement."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def reschedule_reservation(self, command: RescheduleReservationCommand) -> Reservation:
        start_at = command.start_at
        end_at = start_at + timedelta(minutes=command.expected_planned_duration_minutes)
        fingerprint = _reschedule_fingerprint(command)
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.reschedule_reservation",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return reservation_from_json(cast(dict[str, object], replay["reservation"]))

            reservation_row = await _lock_reservation(
                session, command.organization_id, command.reservation_id
            )
            subject_party_id = cast(UUID, reservation_row["subject_party_id"])
            authority = await require_subject_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                subject_party_id=subject_party_id,
                scope_key=MANAGE_APPOINTMENT_SCOPE,
                allow_operator_override=command.allow_subject_override,
            )
            ensure_reservation_revision(
                reservation_row, command.reservation_id, command.expected_revision
            )
            status = cast(str, reservation_row["status"])
            if status != "confirmed":
                raise ReservationNotReschedulable(command.reservation_id, status)

            offering_version_id = cast(UUID, reservation_row["offering_version_id"])
            offering = await load_bookable_offering(
                session, command.organization_id, offering_version_id
            )
            base_duration = cast(int, offering["duration_minutes"])
            policy = cast(dict[str, object], reservation_row["booking_policy_snapshot"])
            step_minutes = slot_step_minutes(policy, base_duration)
            await validate_subject_location_and_origin(
                session,
                organization_id=command.organization_id,
                subject_party_id=subject_party_id,
                location_id=command.location_id,
                origin_request_id=cast(UUID | None, reservation_row["origin_request_id"]),
            )

            requirements = await load_requirements(
                session, command.organization_id, offering_version_id
            )
            choices = validate_choice_cardinality(requirements, command.resources)
            old_claims = await _active_reservation_claims(
                session, command.organization_id, command.reservation_id
            )
            old_resource_ids = tuple(cast(UUID, row["resource_id"]) for row in old_claims)
            new_resource_ids = tuple(choice.resource_id for choice in choices.values())
            all_resource_ids = tuple(sorted(set(old_resource_ids + new_resource_ids), key=str))
            all_resources = await lock_resources(
                session,
                organization_id=command.organization_id,
                resource_ids=all_resource_ids,
            )
            resources = {
                resource_id: all_resources[resource_id] for resource_id in set(new_resource_ids)
            }
            await validate_resource_capabilities(
                session,
                organization_id=command.organization_id,
                requirements=requirements,
                choices=choices,
                resources=resources,
                location_id=None,
            )
            await lock_selected_assignments(
                session,
                organization_id=command.organization_id,
                choices=choices,
            )
            current_revisions = await load_resource_availability_revisions(
                session,
                organization_id=command.organization_id,
                resource_ids=tuple(sorted(resources, key=str)),
            )
            require_expected_resource_revisions(choices, current_revisions)

            _, assignments_by_resource = await load_contextualization(
                session,
                command.organization_id,
                tuple(sorted(resources, key=str)),
                start_at,
                end_at,
            )
            selected = cast(
                Mapping[UUID, AssignmentObservation],
                resolve_selected_assignments(
                    choices=choices,
                    requirements=requirements,
                    assignments_by_resource=assignments_by_resource,
                    location_id=command.location_id,
                    start_at=start_at,
                    end_at=end_at,
                ),
            )
            assignment_ids = tuple(
                sorted({assignment.id for assignment in selected.values()}, key=str)
            )
            schedules = await load_assignment_schedules(
                session, command.organization_id, assignment_ids
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
                exclude_reservation_id=command.reservation_id,
            )
            locations = await load_location_observations(
                session,
                command.organization_id,
                (command.location_id,),
                start_at,
                end_at,
            )
            location = locations.get(command.location_id)
            if (
                location is None
                or location.operational_revision
                != command.expected_location_operational_revision
                or not interval_is_scheduled_available(
                    location.profile, start_at=start_at, end_at=end_at
                )
            ):
                raise AppointmentOptionStale("Location operational configuration changed")

            base_terms, context_terms = await load_booking_terms(
                session,
                command.organization_id,
                offering_version_id,
                assignment_ids,
                base_duration,
                start_at,
                end_at,
            )
            ordered_requirement_ids = tuple(
                requirement.id
                for requirement in sorted(requirements.values(), key=lambda row: row.ordinal)
            )
            observations = effective_context_observations(
                ordered_requirement_ids,
                selected,
                context_terms,
                start_at,
            )
            try:
                resolved = resolve_booking_terms(base_terms, observations)
            except (MissingCommercialTerms, ConflictingContextualTerms, ContextNotBookable) as exc:
                raise AppointmentOptionStale("contextual commercial terms changed") from exc
            _require_expected_terms(command, resolved)
            await _require_preserved_commercial_commitment(
                session,
                organization_id=command.organization_id,
                reservation_id=command.reservation_id,
                resolved=resolved,
            )

            profiles = cast(
                dict[UUID, object],
                build_authoritative_profiles(
                    ordered_requirement_ids=ordered_requirement_ids,
                    choices=choices,
                    selected_assignments=selected,
                    resources=resources,
                    location=location,
                    assignment_schedules=schedules,
                    assignment_exceptions=assignment_exceptions,
                    broad_exceptions=broad_exceptions,
                    live_claims=live_claims,
                ),
            )
            revalidate_exact_slot(
                requirements=requirements,
                choices=choices,
                profiles=cast(dict[UUID, object], profiles),
                start_at=start_at,
                end_at=end_at,
                duration_minutes=resolved.planned_duration_minutes,
                step_minutes=step_minutes,
            )
            authoritative_fingerprint = configuration_fingerprint(
                offering_version_id=offering_version_id,
                location=location,
                ordered_requirement_ids=ordered_requirement_ids,
                choices=choices,
                resources=resources,
                current_availability_revisions=current_revisions,
                selected_assignments=selected,
                base_terms=base_terms,
                context_observations=observations,
                resolved=resolved,
            )
            if authoritative_fingerprint != command.expected_configuration_fingerprint:
                raise AppointmentOptionStale("contextual configuration fingerprint changed")

            await _replace_reservation(
                session,
                command=command,
                requirements=requirements,
                choices=choices,
                selected=selected,
                old_claims=old_claims,
                start_at=start_at,
                end_at=end_at,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.reschedule_reservation",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                idempotency_id=idempotency_id,
                details={
                    "subject_party_id": str(subject_party_id),
                    "subject_authority": authority.audit_details(),
                    "expected_revision": command.expected_revision,
                    "location_id": str(command.location_id),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                    "configuration_fingerprint": authoritative_fingerprint,
                    "contextual": True,
                },
            )
            await append_outbox(
                session,
                organization_id=command.organization_id,
                event_type="reservation.rescheduled.v1",
                aggregate_kind="Reservation",
                aggregate_id=command.reservation_id,
                payload={
                    "reservation_id": str(command.reservation_id),
                    "location_id": str(command.location_id),
                    "start_at": start_at.isoformat(),
                    "end_at": end_at.isoformat(),
                },
            )
            reservation = await read_reservation(
                session, command.organization_id, command.reservation_id
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"reservation": reservation_to_json(reservation)},
            )
            return reservation


def _reschedule_fingerprint(command: RescheduleReservationCommand) -> str:
    return command_fingerprint(
        "booking.reschedule_reservation.contextual.v1",
        {
            "reservation_id": command.reservation_id,
            "expected_revision": command.expected_revision,
            "start_at": command.start_at,
            "location_id": command.location_id,
            "resources": [
                {
                    "requirement_id": choice.requirement_id,
                    "resource_id": choice.resource_id,
                    "assignment_id": choice.resource_location_assignment_id,
                    "assignment_revision": choice.assignment_revision,
                    "availability_revision": choice.availability_revision,
                }
                for choice in command.resources
            ],
            "planned_duration_minutes": command.expected_planned_duration_minutes,
            "amount": str(command.expected_amount),
            "currency": command.expected_currency,
            "location_revision": command.expected_location_operational_revision,
            "configuration_fingerprint": command.expected_configuration_fingerprint,
        },
    )


def _require_expected_terms(
    command: RescheduleReservationCommand,
    resolved: ResolvedBookingTerms,
) -> None:
    if (
        resolved.amount != command.expected_amount
        or resolved.currency != command.expected_currency
        or resolved.planned_duration_minutes != command.expected_planned_duration_minutes
    ):
        raise AppointmentOptionStale("contextual option terms changed")


async def _require_preserved_commercial_commitment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    reservation_id: UUID,
    resolved: ResolvedBookingTerms,
) -> None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT amount, currency, planned_duration_minutes
                    FROM request_engine.reservation_commercial_commitments
                    WHERE organization_id = :organization_id
                      AND reservation_id = :reservation_id
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise BookingConfigurationError(
            f"Reservation {reservation_id} is missing its commercial commitment"
        )
    if (
        cast(Decimal, row["amount"]) != resolved.amount
        or cast(str, row["currency"]) != resolved.currency
        or cast(int, row["planned_duration_minutes"])
        != resolved.planned_duration_minutes
    ):
        raise AppointmentOptionStale(
            "reschedule target would change committed commercial semantics"
        )


async def _lock_reservation(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_version_id, subject_party_id, location_id,
                           origin_request_id, lower(during) AS start_at,
                           upper(during) AS end_at, status,
                           booking_policy_snapshot, revision
                    FROM request_engine.reservations
                    WHERE organization_id = :organization_id
                      AND id = :reservation_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ReservationNotFound(reservation_id)
    return row


async def _active_reservation_claims(
    session: AsyncSession,
    organization_id: UUID,
    reservation_id: UUID,
) -> tuple[RowMapping, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, resource_id, requirement_id,
                           resource_location_assignment_id, quantity
                    FROM request_engine.capacity_claims
                    WHERE organization_id = :organization_id
                      AND reservation_id = :reservation_id
                      AND status = 'active'
                    ORDER BY requirement_id
                    """
                ),
                {"organization_id": organization_id, "reservation_id": reservation_id},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        raise BookingConfigurationError(f"Reservation {reservation_id} has no active claims")
    return tuple(rows)


async def _replace_reservation(
    session: AsyncSession,
    *,
    command: RescheduleReservationCommand,
    requirements: Mapping[UUID, object],
    choices: Mapping[UUID, ResourceChoice],
    selected: Mapping[UUID, AssignmentObservation],
    old_claims: tuple[RowMapping, ...],
    start_at: datetime,
    end_at: datetime,
) -> None:
    old_by_requirement = {
        cast(UUID, row["requirement_id"]): cast(UUID, row["id"]) for row in old_claims
    }
    if set(old_by_requirement) != set(requirements):
        raise BookingConfigurationError(
            f"Reservation {command.reservation_id} does not have the canonical claim set"
        )
    await session.execute(
        text(
            """
            UPDATE request_engine.capacity_claims
            SET status = 'released', released_at = clock_timestamp(),
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND reservation_id = :reservation_id
              AND status = 'active'
            """
        ),
        {
            "organization_id": command.organization_id,
            "reservation_id": command.reservation_id,
        },
    )
    await session.execute(
        text(
            """
            UPDATE request_engine.reservations
            SET location_id = :location_id,
                during = tstzrange(:start_at, :end_at, '[)'),
                revision = revision + 1,
                updated_at = clock_timestamp()
            WHERE organization_id = :organization_id
              AND id = :reservation_id
            """
        ),
        {
            "organization_id": command.organization_id,
            "reservation_id": command.reservation_id,
            "location_id": command.location_id,
            "start_at": start_at,
            "end_at": end_at,
        },
    )
    replacement_ids: dict[UUID, UUID] = {}
    for requirement_id, requirement in sorted(
        requirements.items(), key=lambda item: cast(object, item[1]).ordinal
    ):
        choice = choices[requirement_id]
        assignment = selected[requirement_id]
        replacement_ids[requirement_id] = cast(
            UUID,
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.capacity_claims (
                            organization_id, resource_id, requirement_id,
                            reservation_id, resource_location_assignment_id,
                            during, quantity
                        ) VALUES (
                            :organization_id, :resource_id, :requirement_id,
                            :reservation_id, :assignment_id,
                            tstzrange(:start_at, :end_at, '[)'), :quantity
                        ) RETURNING id
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "resource_id": choice.resource_id,
                        "requirement_id": requirement_id,
                        "reservation_id": command.reservation_id,
                        "assignment_id": assignment.id,
                        "start_at": start_at,
                        "end_at": end_at,
                        "quantity": cast(object, requirement).quantity,
                    },
                )
            ).scalar_one(),
        )
    for requirement_id, old_claim_id in old_by_requirement.items():
        await session.execute(
            text(
                """
                UPDATE request_engine.capacity_claims
                SET status = 'replaced', replaced_by_claim_id = :new_claim_id,
                    updated_at = clock_timestamp()
                WHERE organization_id = :organization_id
                  AND id = :old_claim_id
                  AND status = 'released'
                """
            ),
            {
                "organization_id": command.organization_id,
                "old_claim_id": old_claim_id,
                "new_claim_id": replacement_ids[requirement_id],
            },
        )
