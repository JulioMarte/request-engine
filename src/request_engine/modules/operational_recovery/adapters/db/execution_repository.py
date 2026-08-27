from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.execution_notification_store import (
    attach_communication_task,
)
from request_engine.modules.operational_recovery.adapters.db.execution_prepare_store import (
    prepare_execution,
)
from request_engine.modules.operational_recovery.adapters.db.execution_transition_store import (
    reject_execution,
    succeed_execution,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryExecutionRecord
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RescheduleProposal,
)
from request_engine.platform.db.session import SessionFactory


class ExecutionRepositoryMixin:
    _session_factory: SessionFactory

    async def prepare_execution(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
        command_fingerprint: str,
        proposal: RescheduleProposal,
        reservation_id: UUID,
        notification_requested: bool,
    ) -> RecoveryExecutionRecord:
        return await prepare_execution(
            self._session_factory,
            organization_id=organization_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
            proposal=proposal,
            reservation_id=reservation_id,
            notification_requested=notification_requested,
        )

    async def succeed_execution(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        resulting_revision: int,
    ) -> RecoveryExecution:
        return await succeed_execution(
            self._session_factory,
            organization_id=organization_id,
            execution_id=execution_id,
            resulting_revision=resulting_revision,
        )

    async def reject_execution(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        failure_code: str,
    ) -> RecoveryExecution:
        return await reject_execution(
            self._session_factory,
            organization_id=organization_id,
            execution_id=execution_id,
            failure_code=failure_code,
        )

    async def attach_communication_task(
        self,
        *,
        organization_id: UUID,
        execution_id: UUID,
        communication_task_id: UUID,
    ) -> RecoveryExecution:
        return await attach_communication_task(
            self._session_factory,
            organization_id=organization_id,
            execution_id=execution_id,
            communication_task_id=communication_task_id,
        )
