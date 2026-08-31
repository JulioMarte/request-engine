from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.booking.adapters.db.contextual_supply_lifecycle_commands import (
    PostgresContextualSupplyLifecycleCommands,
)
from request_engine.modules.booking.application.commands import (
    set_resource_location_schedule_exception as schedule_exception,
)
from request_engine.modules.booking.application.operational_errors import (
    ResourceAvailabilityRevisionConflict,
)
from request_engine.modules.booking.contracts.operational_schedule import (
    OperationalAssignmentExtensionReplay,
    OperationalAssignmentExtensionRequest,
    OperationalAssignmentExtensionResult,
    OperationalAssignmentRevisionConflict,
    OperationalAssignmentSchedulePort,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import get_completed_idempotency_result

_CAPABILITY = "booking.set_resource_location_schedule_exception"


class PostgresOperationalAssignmentSchedule(OperationalAssignmentSchedulePort):
    """Operator-native adapter over Booking's authoritative supply writer."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._writer = PostgresContextualSupplyLifecycleCommands(session_factory)

    async def get_extension_by_idempotency(
        self,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
    ) -> OperationalAssignmentExtensionReplay | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            result = await get_completed_idempotency_result(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability=_CAPABILITY,
                idempotency_key=idempotency_key,
            )
            if result is None:
                return None
            details = (
                await session.execute(
                    text(
                        """
                        SELECT a.details
                        FROM request_engine.audit_records a
                        JOIN request_engine.idempotency_records i
                          ON i.organization_id = a.organization_id
                         AND i.id = a.idempotency_record_id
                        WHERE i.organization_id = :organization_id
                          AND i.principal_id = :principal_id
                          AND i.capability = :capability
                          AND i.idempotency_key = :idempotency_key
                          AND a.command_name = :capability
                        ORDER BY a.created_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "organization_id": organization_id,
                        "principal_id": principal_id,
                        "capability": _CAPABILITY,
                        "idempotency_key": idempotency_key,
                    },
                )
            ).scalar_one_or_none()
        exception = result.get("exception")
        if not isinstance(exception, dict) or not isinstance(details, dict):
            raise RuntimeError("completed Booking extension is missing replay provenance")
        if exception.get("exception_kind") != "available" or exception.get("active") is not True:
            return None
        reason = exception.get("reason")
        expected_revision = details.get("previous_resource_availability_revision")
        if not isinstance(reason, str) or not isinstance(expected_revision, int):
            raise RuntimeError("completed Booking extension has invalid replay provenance")
        return OperationalAssignmentExtensionReplay(
            assignment_id=UUID(str(exception["assignment_id"])),
            start_at=datetime.fromisoformat(str(exception["start_at"])),
            end_at=datetime.fromisoformat(str(exception["end_at"])),
            expected_resource_availability_revision=expected_revision,
            reason=reason,
        )

    async def extend_assignment_hours(
        self,
        request: OperationalAssignmentExtensionRequest,
    ) -> OperationalAssignmentExtensionResult:
        try:
            state = await self._writer.set_resource_location_schedule_exception(
                schedule_exception.SetResourceLocationScheduleExceptionCommand(
                    organization_id=request.organization_id,
                    principal_id=request.principal_id,
                    authority_party_id=request.authority_party_id,
                    assignment_id=request.assignment_id,
                    start_at=request.start_at,
                    end_at=request.end_at,
                    exception_kind="available",
                    expected_resource_availability_revision=(
                        request.expected_resource_availability_revision
                    ),
                    idempotency_key=request.idempotency_key,
                    reason=request.reason,
                    active=True,
                )
            )
        except ResourceAvailabilityRevisionConflict as exc:
            raise OperationalAssignmentRevisionConflict(
                request.assignment_id,
                exc.expected,
                exc.actual,
            ) from exc
        return OperationalAssignmentExtensionResult(
            exception_id=state.exception_id,
            assignment_id=state.assignment_id,
            start_at=state.start_at,
            end_at=state.end_at,
            resource_availability_revision=state.resource_availability_revision,
        )
