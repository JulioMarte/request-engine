from request_engine.modules.catalog.adapters.db.operational_profile_commands import (
    PostgresOperationalProfileCommands,
)
from request_engine.modules.catalog.application.commands.set_location_hours_exception import (
    SetLocationHoursExceptionCommand,
)
from request_engine.modules.catalog.contracts.recovery_schedule import (
    RecoveryLocationExtensionRequest,
    RecoveryLocationExtensionResult,
    RecoveryLocationSchedulePort,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryLocationSchedule(RecoveryLocationSchedulePort):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._commands = PostgresOperationalProfileCommands(session_factory)

    async def extend_location_hours(
        self,
        request: RecoveryLocationExtensionRequest,
    ) -> RecoveryLocationExtensionResult:
        state = await self._commands.set_location_hours_exception(
            SetLocationHoursExceptionCommand(
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                authority_party_id=request.authority_party_id,
                location_id=request.location_id,
                start_at=request.start_at,
                end_at=request.end_at,
                exception_kind="available",
                expected_operational_revision=request.expected_operational_revision,
                idempotency_key=request.idempotency_key,
                reason=request.reason,
            )
        )
        return RecoveryLocationExtensionResult(
            exception_id=state.exception_id,
            location_id=state.location_id,
            start_at=state.start_at,
            end_at=state.end_at,
            operational_revision=state.operational_revision,
        )
