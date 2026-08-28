from datetime import timedelta
from uuid import UUID

from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationRequest,
)
from request_engine.modules.communications.contracts.tasks import (
    CommunicationTask,
    CommunicationTaskStatus,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    CommunicateImpactRecoveryActionCommand,
)

from .workflow_schedule_test_support import INCIDENT, NOW, ORG, PRINCIPAL

RECIPIENT = UUID(int=12)
TASK_ID = UUID(int=13)
EXPECTED_DEDUPE = f"operational-recovery:{INCIDENT}:impact:{RECIPIENT}:3"


class FakeCommunications:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.requests: list[RecoveryCommunicationRequest] = []
        self.fail_once = fail_once

    async def create_recovery_notification(
        self,
        request: RecoveryCommunicationRequest,
    ) -> CommunicationTask:
        self.requests.append(request)
        if self.fail_once:
            self.fail_once = False
            raise TimeoutError("simulated response loss after Communications commit")
        return CommunicationTask(
            id=TASK_ID,
            recipient_party_id=request.recipient_party_id,
            contact_point_id=None,
            purpose="operational_recovery_rescheduled",
            source_kind="OperationalRecoveryExecution",
            source_id=request.execution_id,
            channel_policy={"kind": "transactional"},
            template_key="operational_recovery.rescheduled",
            template_version=1,
            render_context=request.render_context,
            dedupe_key=request.dedupe_key,
            not_before=request.not_before,
            expires_at=None,
            status=CommunicationTaskStatus.PENDING,
            revision=1,
        )


def command() -> CommunicateImpactRecoveryActionCommand:
    return CommunicateImpactRecoveryActionCommand(
        organization_id=ORG,
        principal_id=PRINCIPAL,
        incident_id=INCIDENT,
        expected_source_revision=3,
        recipient_party_id=RECIPIENT,
        idempotency_key="impact-communication-1",
        message="Running about 20 minutes behind.",
        not_before=NOW + timedelta(hours=1),
    )
