from request_engine.modules.catalog.contracts.recovery_schedule import (
    RecoveryLocationExtensionRequest as CatalogLocationExtensionRequest,
)
from request_engine.modules.catalog.contracts.recovery_schedule import (
    RecoveryLocationRevisionConflict as CatalogLocationRevisionConflict,
)
from request_engine.modules.catalog.contracts.recovery_schedule import RecoveryLocationSchedulePort
from request_engine.modules.operational_recovery.application.workflow_location_port import (
    RecoveryLocationExtensionRequest,
    RecoveryLocationExtensionResult,
    RecoveryLocationRevisionConflict,
)


class CatalogRecoveryLocationAdapter:
    def __init__(self, schedule: RecoveryLocationSchedulePort) -> None:
        self._schedule = schedule

    async def extend_location_hours(
        self,
        request: RecoveryLocationExtensionRequest,
    ) -> RecoveryLocationExtensionResult:
        try:
            result = await self._schedule.extend_location_hours(
                CatalogLocationExtensionRequest(
                    organization_id=request.organization_id,
                    principal_id=request.principal_id,
                    authority_party_id=request.authority_party_id,
                    location_id=request.location_id,
                    start_at=request.start_at,
                    end_at=request.end_at,
                    expected_operational_revision=request.expected_operational_revision,
                    idempotency_key=request.idempotency_key,
                    reason=request.reason,
                )
            )
        except CatalogLocationRevisionConflict as exc:
            raise RecoveryLocationRevisionConflict(
                exc.location_id,
                exc.expected,
                exc.actual,
            ) from exc
        return RecoveryLocationExtensionResult(
            exception_id=result.exception_id,
            location_id=result.location_id,
            start_at=result.start_at,
            end_at=result.end_at,
            operational_revision=result.operational_revision,
        )
