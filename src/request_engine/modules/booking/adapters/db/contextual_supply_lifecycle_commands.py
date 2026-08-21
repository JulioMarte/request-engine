from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.commands.retire_resource_location_assignment import (  # noqa: E501
    RetiredResourceLocationAssignmentState,
    RetireResourceLocationAssignmentCommand,
)
from request_engine.modules.booking.application.commands.set_resource_location_availability import (
    ResourceLocationAvailabilityState,
    ResourceLocationAvailabilityWindow,
    SetResourceLocationAvailabilityCommand,
)
from request_engine.modules.booking.application.commands.set_resource_location_schedule_exception import (  # noqa: E501
    ResourceLocationScheduleExceptionState,
    SetResourceLocationScheduleExceptionCommand,
)
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
    ResourceLocationAssignmentRevisionConflict,
)
from request_engine.modules.booking.domain.availability import require_aware_utc
from request_engine.platform.audit.postgres import append_audit
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)
from request_engine.platform.security.operational_authority import (
    MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
    require_operational_authority,
)


class PostgresContextualSupplyLifecycleCommands:
    """Semantic lifecycle writes for Resource-at-Location operational supply."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def retire_resource_location_assignment(
        self,
        command: RetireResourceLocationAssignmentCommand,
    ) -> RetiredResourceLocationAssignmentState:
        retired_at = require_aware_utc(command.retired_at, "retired_at")
        fingerprint = command_fingerprint(
            "booking.retire_resource_location_assignment",
            {
                "authority_party_id": command.authority_party_id,
                "assignment_id": command.assignment_id,
                "retired_at": retired_at,
                "expected_assignment_revision": command.expected_assignment_revision,
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
                    capability="booking.retire_resource_location_assignment",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _retired_state_from_json(cast(dict[str, object], replay["assignment"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                assignment = await _lock_assignment_roots(
                    session,
                    organization_id=command.organization_id,
                    assignment_id=command.assignment_id,
                )
                resource_id = cast(UUID, assignment["resource_id"])
                _require_revisions(
                    command.assignment_id,
                    resource_id,
                    assignment_revision=cast(int, assignment["revision"]),
                    expected_assignment_revision=command.expected_assignment_revision,
                    availability_revision=cast(int, assignment["availability_revision"]),
                    expected_availability_revision=(
                        command.expected_resource_availability_revision
                    ),
                )
                if assignment["status"] == "retired":
                    raise ContextualConfigurationConflict(
                        "ResourceLocationAssignment is already retired"
                    )
                effective_from = cast(datetime, assignment["effective_from"])
                effective_until = cast(datetime | None, assignment["effective_until"])
                if retired_at <= effective_from:
                    raise ContextualConfigurationConflict(
                        "retired_at must be after assignment effective_from"
                    )
                if effective_until is not None and retired_at > effective_until:
                    raise ContextualConfigurationConflict(
                        "retired_at cannot extend beyond the existing assignment effective_until"
                    )

                row = (
                    (
                        await session.execute(
                            text(
                                """
                                UPDATE request_engine.resource_location_assignments
                                   SET status = 'retired',
                                       effective_during = tstzrange(
                                           lower(effective_during), :retired_at, '[)'
                                       )
                                 WHERE organization_id = :organization_id
                                   AND id = :assignment_id
                                RETURNING revision
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "assignment_id": command.assignment_id,
                                "retired_at": retired_at,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                final_resource_revision = await _resource_revision(
                    session,
                    command.organization_id,
                    resource_id,
                )
                state = RetiredResourceLocationAssignmentState(
                    assignment_id=command.assignment_id,
                    retired_at=retired_at,
                    assignment_revision=cast(int, row["revision"]),
                    resource_availability_revision=final_resource_revision,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="booking.retire_resource_location_assignment",
                    aggregate_kind="ResourceLocationAssignment",
                    aggregate_id=command.assignment_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "resource_id": str(resource_id),
                        "retired_at": retired_at.isoformat(),
                        "previous_assignment_revision": command.expected_assignment_revision,
                        "previous_resource_availability_revision": (
                            command.expected_resource_availability_revision
                        ),
                        "new_resource_availability_revision": final_resource_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"assignment": _retired_state_to_json(state)},
                )
                return state
        except DBAPIError as exc:
            _translate_configuration_db_error(exc)
            raise

    async def set_resource_location_availability(
        self,
        command: SetResourceLocationAvailabilityCommand,
    ) -> ResourceLocationAvailabilityState:
        windows = tuple(sorted(command.windows, key=_window_sort_key))
        fingerprint = command_fingerprint(
            "booking.set_resource_location_availability",
            {
                "authority_party_id": command.authority_party_id,
                "assignment_id": command.assignment_id,
                "windows": [_window_to_json(window) for window in windows],
                "expected_resource_availability_revision": (
                    command.expected_resource_availability_revision
                ),
            },
        )
        async with tenant_transaction(self._session_factory, command.organization_id) as session:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                capability="booking.set_resource_location_availability",
                idempotency_key=command.idempotency_key,
                fingerprint=fingerprint,
            )
            if replay is not None:
                return _availability_state_from_json(
                    cast(dict[str, object], replay["availability"])
                )

            authority = await require_operational_authority(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                authority_party_id=command.authority_party_id,
                scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
            )
            assignment = await _lock_assignment_roots(
                session,
                organization_id=command.organization_id,
                assignment_id=command.assignment_id,
            )
            resource_id = cast(UUID, assignment["resource_id"])
            if assignment["status"] != "active":
                raise ContextualConfigurationConflict(
                    "ResourceLocationAssignment must be active to configure availability"
                )
            current_revision = cast(int, assignment["availability_revision"])
            if current_revision != command.expected_resource_availability_revision:
                raise ResourceAvailabilityRevisionConflict(
                    resource_id,
                    command.expected_resource_availability_revision,
                    current_revision,
                )

            await session.execute(
                text(
                    """
                    DELETE FROM request_engine.resource_location_availability
                    WHERE organization_id = :organization_id
                      AND resource_location_assignment_id = :assignment_id
                    """
                ),
                {
                    "organization_id": command.organization_id,
                    "assignment_id": command.assignment_id,
                },
            )
            for window in windows:
                await session.execute(
                    text(
                        """
                        INSERT INTO request_engine.resource_location_availability (
                            organization_id,
                            resource_location_assignment_id,
                            weekday,
                            local_start,
                            local_end,
                            valid_from,
                            valid_until
                        ) VALUES (
                            :organization_id,
                            :assignment_id,
                            :weekday,
                            :local_start,
                            :local_end,
                            :valid_from,
                            :valid_until
                        )
                        """
                    ),
                    {
                        "organization_id": command.organization_id,
                        "assignment_id": command.assignment_id,
                        "weekday": window.weekday,
                        "local_start": window.local_start,
                        "local_end": window.local_end,
                        "valid_from": window.valid_from,
                        "valid_until": window.valid_until,
                    },
                )
            final_revision = await _resource_revision(
                session,
                command.organization_id,
                resource_id,
            )
            state = ResourceLocationAvailabilityState(
                assignment_id=command.assignment_id,
                windows=windows,
                resource_availability_revision=final_revision,
            )
            await append_audit(
                session,
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                command_name="booking.set_resource_location_availability",
                aggregate_kind="ResourceLocationAssignment",
                aggregate_id=command.assignment_id,
                idempotency_id=idempotency_id,
                details={
                    "authority": authority.audit_details(),
                    "resource_id": str(resource_id),
                    "window_count": len(windows),
                    "previous_resource_availability_revision": current_revision,
                    "new_resource_availability_revision": final_revision,
                },
            )
            await complete_idempotency(
                session,
                idempotency_id,
                {"availability": _availability_state_to_json(state)},
            )
            return state

    async def set_resource_location_schedule_exception(
        self,
        command: SetResourceLocationScheduleExceptionCommand,
    ) -> ResourceLocationScheduleExceptionState:
        start_at = require_aware_utc(command.start_at, "start_at")
        end_at = require_aware_utc(command.end_at, "end_at")
        if end_at <= start_at:
            raise ValueError("end_at must be after start_at")
        fingerprint = command_fingerprint(
            "booking.set_resource_location_schedule_exception",
            {
                "authority_party_id": command.authority_party_id,
                "assignment_id": command.assignment_id,
                "exception_id": command.exception_id,
                "start_at": start_at,
                "end_at": end_at,
                "exception_kind": command.exception_kind,
                "reason": command.reason,
                "active": command.active,
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
                    capability="booking.set_resource_location_schedule_exception",
                    idempotency_key=command.idempotency_key,
                    fingerprint=fingerprint,
                )
                if replay is not None:
                    return _exception_state_from_json(cast(dict[str, object], replay["exception"]))

                authority = await require_operational_authority(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    authority_party_id=command.authority_party_id,
                    scope_key=MANAGE_CONTEXTUAL_SUPPLY_SCOPE,
                )
                assignment = await _lock_assignment_roots(
                    session,
                    organization_id=command.organization_id,
                    assignment_id=command.assignment_id,
                )
                resource_id = cast(UUID, assignment["resource_id"])
                if assignment["status"] != "active":
                    raise ContextualConfigurationConflict(
                        "ResourceLocationAssignment must be active to configure exceptions"
                    )
                current_revision = cast(int, assignment["availability_revision"])
                if current_revision != command.expected_resource_availability_revision:
                    raise ResourceAvailabilityRevisionConflict(
                        resource_id,
                        command.expected_resource_availability_revision,
                        current_revision,
                    )

                if command.exception_id is None:
                    exception_id = cast(
                        UUID,
                        (
                            await session.execute(
                                text(
                                    """
                                    INSERT INTO
                                        request_engine.resource_location_schedule_exceptions (
                                        organization_id,
                                        resource_location_assignment_id,
                                        during,
                                        exception_kind,
                                        reason,
                                        active
                                    ) VALUES (
                                        :organization_id,
                                        :assignment_id,
                                        tstzrange(:start_at, :end_at, '[)'),
                                        :exception_kind,
                                        :reason,
                                        :active
                                    )
                                    RETURNING id
                                    """
                                ),
                                {
                                    "organization_id": command.organization_id,
                                    "assignment_id": command.assignment_id,
                                    "start_at": start_at,
                                    "end_at": end_at,
                                    "exception_kind": command.exception_kind,
                                    "reason": command.reason,
                                    "active": command.active,
                                },
                            )
                        ).scalar_one(),
                    )
                else:
                    row = (
                        await session.execute(
                            text(
                                """
                                UPDATE request_engine.resource_location_schedule_exceptions
                                   SET during = tstzrange(:start_at, :end_at, '[)'),
                                       exception_kind = :exception_kind,
                                       reason = :reason,
                                       active = :active,
                                       updated_at = clock_timestamp()
                                 WHERE organization_id = :organization_id
                                   AND id = :exception_id
                                   AND resource_location_assignment_id = :assignment_id
                                RETURNING id
                                """
                            ),
                            {
                                "organization_id": command.organization_id,
                                "assignment_id": command.assignment_id,
                                "exception_id": command.exception_id,
                                "start_at": start_at,
                                "end_at": end_at,
                                "exception_kind": command.exception_kind,
                                "reason": command.reason,
                                "active": command.active,
                            },
                        )
                    ).first()
                    if row is None:
                        raise ContextualConfigurationConflict(
                            "schedule exception is missing or belongs to another assignment"
                        )
                    exception_id = command.exception_id

                final_revision = await _resource_revision(
                    session,
                    command.organization_id,
                    resource_id,
                )
                state = ResourceLocationScheduleExceptionState(
                    exception_id=exception_id,
                    assignment_id=command.assignment_id,
                    start_at=start_at,
                    end_at=end_at,
                    exception_kind=command.exception_kind,
                    reason=command.reason,
                    active=command.active,
                    resource_availability_revision=final_revision,
                )
                await append_audit(
                    session,
                    organization_id=command.organization_id,
                    principal_id=command.principal_id,
                    command_name="booking.set_resource_location_schedule_exception",
                    aggregate_kind="ResourceLocationScheduleException",
                    aggregate_id=exception_id,
                    idempotency_id=idempotency_id,
                    details={
                        "authority": authority.audit_details(),
                        "assignment_id": str(command.assignment_id),
                        "resource_id": str(resource_id),
                        "exception_kind": command.exception_kind,
                        "active": command.active,
                        "previous_resource_availability_revision": current_revision,
                        "new_resource_availability_revision": final_revision,
                    },
                )
                await complete_idempotency(
                    session,
                    idempotency_id,
                    {"exception": _exception_state_to_json(state)},
                )
                return state
        except DBAPIError as exc:
            _translate_configuration_db_error(exc)
            raise


async def _lock_assignment_roots(
    session: AsyncSession,
    *,
    organization_id: UUID,
    assignment_id: UUID,
) -> RowMapping:
    identity = (
        (
            await session.execute(
                text(
                    """
                    SELECT resource_id, location_id
                    FROM request_engine.resource_location_assignments
                    WHERE organization_id = :organization_id
                      AND id = :assignment_id
                    """
                ),
                {"organization_id": organization_id, "assignment_id": assignment_id},
            )
        )
        .mappings()
        .first()
    )
    if identity is None:
        raise ContextualConfigurationConflict(
            "ResourceLocationAssignment is missing or belongs to another Organization"
        )
    resource_id = cast(UUID, identity["resource_id"])
    location_id = cast(UUID, identity["location_id"])

    await session.execute(
        text(
            """
            SELECT id
            FROM request_engine.locations
            WHERE organization_id = :organization_id AND id = :location_id
            FOR UPDATE
            """
        ),
        {"organization_id": organization_id, "location_id": location_id},
    )
    await session.execute(
        text(
            """
            SELECT id
            FROM request_engine.resources
            WHERE organization_id = :organization_id AND id = :resource_id
            FOR UPDATE
            """
        ),
        {"organization_id": organization_id, "resource_id": resource_id},
    )
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT a.resource_id,
                           a.location_id,
                           a.status,
                           a.revision,
                           lower(a.effective_during) AS effective_from,
                           upper(a.effective_during) AS effective_until,
                           r.availability_revision
                    FROM request_engine.resource_location_assignments a
                    JOIN request_engine.resources r
                      ON r.organization_id = a.organization_id
                     AND r.id = a.resource_id
                    WHERE a.organization_id = :organization_id
                      AND a.id = :assignment_id
                    FOR UPDATE OF a
                    """
                ),
                {"organization_id": organization_id, "assignment_id": assignment_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ContextualConfigurationConflict(
            "ResourceLocationAssignment disappeared while locking"
        )
    return row


async def _resource_revision(
    session: AsyncSession,
    organization_id: UUID,
    resource_id: UUID,
) -> int:
    return cast(
        int,
        (
            await session.execute(
                text(
                    """
                    SELECT availability_revision
                    FROM request_engine.resources
                    WHERE organization_id = :organization_id AND id = :resource_id
                    """
                ),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        ).scalar_one(),
    )


def _require_revisions(
    assignment_id: UUID,
    resource_id: UUID,
    *,
    assignment_revision: int,
    expected_assignment_revision: int,
    availability_revision: int,
    expected_availability_revision: int,
) -> None:
    if assignment_revision != expected_assignment_revision:
        raise ResourceLocationAssignmentRevisionConflict(
            assignment_id,
            expected_assignment_revision,
            assignment_revision,
        )
    if availability_revision != expected_availability_revision:
        raise ResourceAvailabilityRevisionConflict(
            resource_id,
            expected_availability_revision,
            availability_revision,
        )


def _window_sort_key(window: ResourceLocationAvailabilityWindow) -> tuple[object, ...]:
    return (
        window.weekday,
        window.local_start,
        window.local_end,
        window.valid_from or datetime.min.date(),
        window.valid_until or datetime.max.date(),
    )


def _window_to_json(window: ResourceLocationAvailabilityWindow) -> dict[str, object]:
    return {
        "weekday": window.weekday,
        "local_start": window.local_start.isoformat(),
        "local_end": window.local_end.isoformat(),
        "valid_from": window.valid_from.isoformat() if window.valid_from else None,
        "valid_until": window.valid_until.isoformat() if window.valid_until else None,
    }


def _retired_state_to_json(state: RetiredResourceLocationAssignmentState) -> dict[str, object]:
    return {
        "assignment_id": str(state.assignment_id),
        "retired_at": state.retired_at.isoformat(),
        "assignment_revision": state.assignment_revision,
        "resource_availability_revision": state.resource_availability_revision,
    }


def _retired_state_from_json(value: dict[str, object]) -> RetiredResourceLocationAssignmentState:
    return RetiredResourceLocationAssignmentState(
        assignment_id=UUID(cast(str, value["assignment_id"])),
        retired_at=datetime.fromisoformat(cast(str, value["retired_at"])),
        assignment_revision=cast(int, value["assignment_revision"]),
        resource_availability_revision=cast(int, value["resource_availability_revision"]),
    )


def _availability_state_to_json(state: ResourceLocationAvailabilityState) -> dict[str, object]:
    return {
        "assignment_id": str(state.assignment_id),
        "windows": [_window_to_json(window) for window in state.windows],
        "resource_availability_revision": state.resource_availability_revision,
    }


def _availability_state_from_json(value: dict[str, object]) -> ResourceLocationAvailabilityState:
    from datetime import date, time

    windows = cast(list[dict[str, object]], value["windows"])
    return ResourceLocationAvailabilityState(
        assignment_id=UUID(cast(str, value["assignment_id"])),
        windows=tuple(
            ResourceLocationAvailabilityWindow(
                weekday=cast(int, item["weekday"]),
                local_start=time.fromisoformat(cast(str, item["local_start"])),
                local_end=time.fromisoformat(cast(str, item["local_end"])),
                valid_from=(
                    date.fromisoformat(cast(str, item["valid_from"]))
                    if item.get("valid_from") is not None
                    else None
                ),
                valid_until=(
                    date.fromisoformat(cast(str, item["valid_until"]))
                    if item.get("valid_until") is not None
                    else None
                ),
            )
            for item in windows
        ),
        resource_availability_revision=cast(int, value["resource_availability_revision"]),
    )


def _exception_state_to_json(
    state: ResourceLocationScheduleExceptionState,
) -> dict[str, object]:
    return {
        "exception_id": str(state.exception_id),
        "assignment_id": str(state.assignment_id),
        "start_at": state.start_at.isoformat(),
        "end_at": state.end_at.isoformat(),
        "exception_kind": state.exception_kind,
        "reason": state.reason,
        "active": state.active,
        "resource_availability_revision": state.resource_availability_revision,
    }


def _exception_state_from_json(
    value: dict[str, object],
) -> ResourceLocationScheduleExceptionState:
    kind = cast(str, value["exception_kind"])
    if kind not in ("available", "unavailable"):
        raise ValueError("stored exception_kind is invalid")
    return ResourceLocationScheduleExceptionState(
        exception_id=UUID(cast(str, value["exception_id"])),
        assignment_id=UUID(cast(str, value["assignment_id"])),
        start_at=datetime.fromisoformat(cast(str, value["start_at"])),
        end_at=datetime.fromisoformat(cast(str, value["end_at"])),
        exception_kind=kind,
        reason=cast(str | None, value.get("reason")),
        active=cast(bool, value["active"]),
        resource_availability_revision=cast(int, value["resource_availability_revision"]),
    )


def _translate_configuration_db_error(exc: DBAPIError) -> None:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate in {"23P01", "23514", "55000"}:
        raise ContextualConfigurationConflict(
            "contextual supply change conflicts with effective configuration or durable claims"
        ) from None
