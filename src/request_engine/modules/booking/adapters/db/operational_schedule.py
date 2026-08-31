from uuid import UUID

from request_engine.modules.booking.adapters.db.contextual_supply_lifecycle_commands import (
    PostgresContextualSupplyLifecycleCommands,
)
from request_engine.modules.booking.adapters.db.operational_schedule_replay import (
    load_extension_replay,
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
            return await load_extension_replay(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                idempotency_key=idempotency_key,
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
