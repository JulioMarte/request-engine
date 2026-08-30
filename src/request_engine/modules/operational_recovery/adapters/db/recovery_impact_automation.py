from uuid import UUID

from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPort,
    RecoveryCommunicationPurpose,
    RecoveryCommunicationRequest,
)
from request_engine.modules.operational_recovery.adapters.db.recovery_automation_principal import (
    RecoveryAutomationPrincipal,
)
from request_engine.modules.operational_recovery.application.workflow_communication_action import (
    impact_dedupe_key,
)
from request_engine.platform.db.session import SessionFactory


class PostgresRecoveryImpactAutomation:
    """Executes the autonomous customer-impact communication under one
    deterministic tenant-scoped system principal, converging with the explicit
    operator action through the section 13 dedupe identity."""

    def __init__(
        self,
        session_factory: SessionFactory,
        communications: RecoveryCommunicationPort,
    ) -> None:
        self._principal = RecoveryAutomationPrincipal(session_factory)
        self._communications = communications

    async def communicate_impact(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        source_revision: int,
        recipients: tuple[UUID, ...],
    ) -> None:
        principal_id = await self._principal.ensure(organization_id)
        for recipient in recipients:
            await self._communications.create_recovery_notification(
                RecoveryCommunicationRequest(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    recipient_party_id=recipient,
                    purpose=RecoveryCommunicationPurpose.IMPACT,
                    execution_id=incident_id,
                    idempotency_key=(
                        f"recovery-impact-auto:{incident_id}:{recipient}:{source_revision}:v1"
                    ),
                    dedupe_key=impact_dedupe_key(
                        incident_id=incident_id,
                        recipient_party_id=recipient,
                        source_revision=source_revision,
                    ),
                    render_context={},
                )
            )
