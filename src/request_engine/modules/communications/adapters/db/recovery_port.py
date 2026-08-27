from request_engine.modules.communications.adapters.db.communication_commands import PostgresCommunicationCommands
from request_engine.modules.communications.application.commands.create_communication_task import CreateCommunicationTaskCommand
from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPort,
    RecoveryCommunicationRequest,
)
from request_engine.modules.communications.contracts.tasks import CommunicationTask
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryCommunicationPort(RecoveryCommunicationPort):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._commands = PostgresCommunicationCommands(session_factory)

    async def create_recovery_notification(
        self, request: RecoveryCommunicationRequest
    ) -> CommunicationTask:
        return await self._commands.create_communication_task(
            CreateCommunicationTaskCommand(
                organization_id=request.organization_id,
                principal_id=request.principal_id,
                recipient_party_id=request.recipient_party_id,
                purpose="operational_recovery_rescheduled",
                template_key="operational_recovery.rescheduled",
                template_version=1,
                channel_policy={"kind": "transactional"},
                render_context=request.render_context,
                idempotency_key=request.idempotency_key,
                source_kind="OperationalRecoveryExecution",
                source_id=request.execution_id,
                dedupe_key=request.dedupe_key,
                not_before=request.not_before,
            )
        )
