from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from request_engine.modules.booking.application.commands.assign_resource_to_location import (
    AssignResourceToLocationCommand,
    ResourceLocationAssignmentState,
)
from request_engine.modules.booking.application.commands.configure_booking_context_terms import (
    BookingContextTermsState,
    ConfigureBookingContextTermsCommand,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
)
from request_engine.modules.booking.domain.availability import require_aware_utc
from request_engine.modules.tenancy.adapters.db.operational_authority import (
    require_operational_authority,
)
from request_engine.modules.tenancy.contracts.operational_authority import (
    MANAGE_COMMERCIAL_TERMS_SCOPE,
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
)
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


class PostgresContextualConfigCommands:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def assign_resource_to_location(
        self,
        command: AssignResourceToLocationCommand,
    ) -> ResourceLocationAssignmentState:
        effective_from, effective_until = _validated_effective_range(
            command.effective_from,
            command.effective_until,
        )
        fingerprint = command_fingerprint(
            "booking.assign_resource_to_location",
            {
                "authority_party_id": command.authority_party_id,
                "resource_id": command.resource_id,
                "location_id": command.location_id,
                "effective_from": effective_from,
                "effective_until": effective_until,
                "expected_resource_availability_revision": (
                    command.expected_resource_availability_revision
                ),
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="booking.assign_resource_to_location",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _assignment_from_json(cast(dict[str, object], replay["assignment"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                location = (
                    await session.execute(
                        text(
                            """
                            SELECT id
                            FROM request_engine.locations
                            WHERE organization_id = :organization_id
                              AND id = :location_id
                              AND active
                            FOR UPDATE
                            """
                        ),
                        {
                            "organization_id": command.organization_id,
                            "location_id": command.location_id,
                        },
                    )
                ).first()
                if location is None:
                    raise ContextualConfigurationConflict(
                        "Location is missing, inactive, or belongs to another Organization"
                    )

                resource_row = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT availability_revision, active
                                FROM request_engine.resources
                                WHERE organization_id = :organization_id
                                  AND id = :resource_id
                                FOR UPDATE
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": command.resource_id,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if resource_row is None or resource_row["active"] is not True:
                    raise ContextualConfigurationConflict(
                        "Resource is missing, inactive, or belongs to another Organization"
                    )
                current_revision = cast(int, resource_row["availability_revision"])
                if current_revision != command.expected_resource_availability_revision:
                    raise ResourceAvailabilityRevisionConflict(
                        command.resource_id,
                        command.expected_resource_availability_revision,
                        current_revision,
                    )

                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.resource_location_assignments (
                                    organization_id,
                                    resource_id,
                                    location_id,
                                    effective_during
                                ) VALUES (
                                    :organization_id,
                                    :resource_id,
                                    :location_id,
                                    tstzrange(:effective_from, :effective_until, '[)')
                                )
                                RETURNING id, revision
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": command.resource_id,
                                "location_id": command.location_id,
                                "effective_from": effective_from,
                                "effective_until": effective_until,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                final_resource_revision = cast(
                    int,
                    (
                        await session.execute(
                            text(
                                """
                                SELECT availability_revision
                                FROM request_engine.resources
                                WHERE organization_id = :organization_id
                                  AND id = :resource_id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "resource_id": command.resource_id,
                            },
                        )
                    ).scalar_one(),
                )
                state = ResourceLocationAssignmentState(
                    assignment_id=cast(UUID, row["id"]),
                    resource_id=command.resource_id,
                    location_id=command.location_id,
                    effective_from=effective_from,
                    effective_until=effective_until,
                    assignment_revision=cast(int, row["revision"]),
                    resource_availability_revision=final_resource_revision,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="booking.assign_resource_to_location",
                    aggregate_kind="ResourceLocationAssignment",
                    aggregate_id=state.assignment_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "resource_id": str(command.resource_id),
                        "location_id": str(command.location_id),
                        "previous_resource_availability_revision": current_revision,
                        "new_resource_availability_revision": final_resource_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"assignment": _assignment_to_json(state)},
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise ContextualConfigurationConflict(
                    "ResourceLocationAssignment overlaps existing effective configuration"
                ) from None
            raise

    async def configure_booking_context_terms(
        self,
        command: ConfigureBookingContextTermsCommand,
    ) -> BookingContextTermsState:
        effective_from, effective_until = _validated_effective_range(
            command.effective_from,
            command.effective_until,
        )
        _validate_terms(
            command.amount,
            command.currency,
            command.planned_duration_minutes,
            command.bookable,
        )
        fingerprint = command_fingerprint(
            "booking.configure_booking_context_terms",
            {
                "authority_party_id": command.authority_party_id,
                "resource_location_assignment_id": command.resource_location_assignment_id,
                "offering_version_id": command.offering_version_id,
                "effective_from": effective_from,
                "effective_until": effective_until,
                "amount": str(command.amount) if command.amount is not None else None,
                "currency": command.currency,
                "planned_duration_minutes": command.planned_duration_minutes,
                "bookable": command.bookable,
            },
        )
        try:
            async with tenant_transaction(
                self._session_factory, command.organization_id
            ) as session:
                idempotency_id, replay = await acquire_idempotency(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    capability="booking.configure_booking_context_terms",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _terms_from_json(cast(dict[str, object], replay["terms"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_COMMERCIAL_TERMS_SCOPE,
                )
                assignment_row = (
                    (
                        await session.execute(
                            text(
                                """
                                SELECT a.resource_id
                                FROM request_engine.resource_location_assignments a
                                JOIN request_engine.resources r
                                  ON r.organization_id = a.organization_id
                                 AND r.id = a.resource_id
                                WHERE a.organization_id = :organization_id
                                  AND a.id = :assignment_id
                                  AND r.active
                                FOR UPDATE OF r, a
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "assignment_id": command.resource_location_assignment_id,
                            },
                        )
                    )
                    .mappings()
                    .first()
                )
                if assignment_row is None:
                    raise ContextualConfigurationConflict(
                        "ResourceLocationAssignment is missing or not configurable"
                    )
                offering = (
                    await session.execute(
                        text(
                            """
                            SELECT ov.id
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
                            "organization_id": command.organization_id,
                            "offering_version_id": command.offering_version_id,
                        },
                    )
                ).first()
                if offering is None:
                    raise ContextualConfigurationConflict(
                        "OfferingVersion is missing or belongs to another Organization"
                    )

                row = (
                    (
                        await session.execute(
                            text(
                                """
                                INSERT INTO request_engine.booking_context_terms (
                                    organization_id,
                                    resource_location_assignment_id,
                                    offering_version_id,
                                    effective_during,
                                    amount,
                                    currency,
                                    planned_duration_minutes,
                                    bookable
                                ) VALUES (
                                    :organization_id,
                                    :assignment_id,
                                    :offering_version_id,
                                    tstzrange(:effective_from, :effective_until, '[)'),
                                    :amount,
                                    :currency,
                                    :planned_duration_minutes,
                                    :bookable
                                )
                                RETURNING id, revision
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "assignment_id": command.resource_location_assignment_id,
                                "offering_version_id": command.offering_version_id,
                                "effective_from": effective_from,
                                "effective_until": effective_until,
                                "amount": command.amount,
                                "currency": command.currency,
                                "planned_duration_minutes": command.planned_duration_minutes,
                                "bookable": command.bookable,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                state = BookingContextTermsState(
                    context_terms_id=cast(UUID, row["id"]),
                    resource_location_assignment_id=command.resource_location_assignment_id,
                    offering_version_id=command.offering_version_id,
                    effective_from=effective_from,
                    effective_until=effective_until,
                    amount=command.amount,
                    currency=command.currency,
                    planned_duration_minutes=command.planned_duration_minutes,
                    bookable=command.bookable,
                    revision=cast(int, row["revision"]),
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="booking.configure_booking_context_terms",
                    aggregate_kind="BookingContextTerms",
                    aggregate_id=state.context_terms_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "resource_location_assignment_id": str(
                            command.resource_location_assignment_id
                        ),
                        "offering_version_id": str(command.offering_version_id),
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"terms": _terms_to_json(state)},
                )
                return state
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23P01":
                raise ContextualConfigurationConflict(
                    "BookingContextTerms overlap existing effective configuration"
                ) from None
            raise


def _validated_effective_range(
    effective_from: datetime,
    effective_until: datetime | None,
) -> tuple[datetime, datetime | None]:
    start = require_aware_utc(effective_from, "effective_from")
    end = (
        require_aware_utc(effective_until, "effective_until")
        if effective_until is not None
        else None
    )
    if end is not None and end <= start:
        raise ValueError("effective_until must be after effective_from")
    return start, end


def _validate_terms(
    amount: Decimal | None,
    currency: str | None,
    planned_duration_minutes: int | None,
    bookable: bool,
) -> None:
    if (amount is None) != (currency is None):
        raise ValueError("amount and currency must be present together")
    if amount is not None and amount < 0:
        raise ValueError("amount must be non-negative")
    if currency is not None and (
        len(currency) != 3 or not currency.isalpha() or currency != currency.upper()
    ):
        raise ValueError("currency must be an uppercase three-letter code")
    if planned_duration_minutes is not None and planned_duration_minutes <= 0:
        raise ValueError("planned_duration_minutes must be positive")
    if amount is None and planned_duration_minutes is None and bookable:
        raise ValueError("bookable context terms require a material override")


def _assignment_to_json(state: ResourceLocationAssignmentState) -> dict[str, object]:
    return {
        "assignment_id": str(state.assignment_id),
        "resource_id": str(state.resource_id),
        "location_id": str(state.location_id),
        "effective_from": state.effective_from.isoformat(),
        "effective_until": state.effective_until.isoformat() if state.effective_until else None,
        "assignment_revision": state.assignment_revision,
        "resource_availability_revision": state.resource_availability_revision,
    }


def _assignment_from_json(value: dict[str, object]) -> ResourceLocationAssignmentState:
    effective_until = cast(str | None, value.get("effective_until"))
    return ResourceLocationAssignmentState(
        assignment_id=UUID(cast(str, value["assignment_id"])),
        resource_id=UUID(cast(str, value["resource_id"])),
        location_id=UUID(cast(str, value["location_id"])),
        effective_from=datetime.fromisoformat(cast(str, value["effective_from"])),
        effective_until=datetime.fromisoformat(effective_until) if effective_until else None,
        assignment_revision=cast(int, value["assignment_revision"]),
        resource_availability_revision=cast(int, value["resource_availability_revision"]),
    )


def _terms_to_json(state: BookingContextTermsState) -> dict[str, object]:
    return {
        "context_terms_id": str(state.context_terms_id),
        "resource_location_assignment_id": str(state.resource_location_assignment_id),
        "offering_version_id": str(state.offering_version_id),
        "effective_from": state.effective_from.isoformat(),
        "effective_until": state.effective_until.isoformat() if state.effective_until else None,
        "amount": str(state.amount) if state.amount is not None else None,
        "currency": state.currency,
        "planned_duration_minutes": state.planned_duration_minutes,
        "bookable": state.bookable,
        "revision": state.revision,
    }


def _terms_from_json(value: dict[str, object]) -> BookingContextTermsState:
    effective_until = cast(str | None, value.get("effective_until"))
    amount = cast(str | None, value.get("amount"))
    return BookingContextTermsState(
        context_terms_id=UUID(cast(str, value["context_terms_id"])),
        resource_location_assignment_id=UUID(cast(str, value["resource_location_assignment_id"])),
        offering_version_id=UUID(cast(str, value["offering_version_id"])),
        effective_from=datetime.fromisoformat(cast(str, value["effective_from"])),
        effective_until=datetime.fromisoformat(effective_until) if effective_until else None,
        amount=Decimal(amount) if amount is not None else None,
        currency=cast(str | None, value.get("currency")),
        planned_duration_minutes=cast(int | None, value.get("planned_duration_minutes")),
        bookable=cast(bool, value["bookable"]),
        revision=cast(int, value["revision"]),
    )
