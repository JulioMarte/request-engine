from uuid import UUID

from request_engine.modules.operational_recovery.adapters.db.execution_prepare_store import (
    prepare_execution,
)
from request_engine.modules.operational_recovery.adapters.db.execution_transition_store import (
    attach_communication_task,
    reject_execution,
    succeed_execution,
)
from request_engine.modules.operational_recovery.adapters.db.proposal_store import (
    create_proposal,
    find_proposal_replay,
    get_proposal,
)
from request_engine.modules.operational_recovery.application.ports import (
    RecoveryExecutionRecord,
    RecoveryRepository,
)
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RescheduleProposal,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryRepository(RecoveryRepository):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def find_proposal_replay(self, *, organization_id: UUID, principal_id: UUID, idempotency_key: str, command_fingerprint: str) -> RescheduleProposal | None:
        return await find_proposal_replay(self._session_factory, organization_id=organization_id, principal_id=principal_id, idempotency_key=idempotency_key, command_fingerprint=command_fingerprint)

    async def create_proposal(self, *, organization_id: UUID, principal_id: UUID, idempotency_key: str, command_fingerprint: str, proposal: RescheduleProposal) -> RescheduleProposal:
        return await create_proposal(self._session_factory, organization_id=organization_id, principal_id=principal_id, idempotency_key=idempotency_key, command_fingerprint=command_fingerprint, proposal=proposal)

    async def get_proposal(self, *, organization_id: UUID, proposal_id: UUID) -> RescheduleProposal | None:
        return await get_proposal(self._session_factory, organization_id=organization_id, proposal_id=proposal_id)

    async def prepare_execution(self, *, organization_id: UUID, principal_id: UUID, idempotency_key: str, command_fingerprint: str, proposal: RescheduleProposal, reservation_id: UUID, notification_requested: bool) -> RecoveryExecutionRecord:
        return await prepare_execution(self._session_factory, organization_id=organization_id, principal_id=principal_id, idempotency_key=idempotency_key, command_fingerprint=command_fingerprint, proposal=proposal, reservation_id=reservation_id, notification_requested=notification_requested)

    async def succeed_execution(self, *, organization_id: UUID, execution_id: UUID, resulting_revision: int) -> RecoveryExecution:
        return await succeed_execution(self._session_factory, organization_id=organization_id, execution_id=execution_id, resulting_revision=resulting_revision)

    async def reject_execution(self, *, organization_id: UUID, execution_id: UUID, failure_code: str) -> RecoveryExecution:
        return await reject_execution(self._session_factory, organization_id=organization_id, execution_id=execution_id, failure_code=failure_code)

    async def attach_communication_task(self, *, organization_id: UUID, execution_id: UUID, communication_task_id: UUID) -> RecoveryExecution:
        return await attach_communication_task(self._session_factory, organization_id=organization_id, execution_id=execution_id, communication_task_id=communication_task_id)
