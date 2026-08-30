from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.communications.contracts.recovery import (
    RecoveryCommunicationPort,
    RecoveryCommunicationPurpose,
    RecoveryCommunicationRequest,
)
from request_engine.modules.operational_recovery.application.recovery_impact_automation import (
    AUTOMATION_PRINCIPAL_KIND,
    AUTOMATION_PRINCIPAL_SUBJECT,
)
from request_engine.modules.operational_recovery.application.workflow_communication_action import (
    impact_dedupe_key,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_ENSURE_PRINCIPAL = text(
    """
    INSERT INTO request_engine.principals (
        organization_id, principal_kind, external_subject
    ) VALUES (
        :organization_id, :principal_kind, :external_subject
    )
    ON CONFLICT (organization_id, principal_kind, external_subject)
    DO UPDATE SET updated_at = clock_timestamp()
    RETURNING id
    """
)


class PostgresRecoveryImpactAutomation:
    """Executes the autonomous customer-impact communication under one
    deterministic tenant-scoped system principal, converging with the explicit
    operator action through the section 13 dedupe identity."""

    def __init__(
        self,
        session_factory: SessionFactory,
        communications: RecoveryCommunicationPort,
    ) -> None:
        self._session_factory = session_factory
        self._communications = communications

    async def communicate_impact(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        source_revision: int,
        recipients: tuple[UUID, ...],
    ) -> None:
        principal_id = await self._ensure_automation_principal(organization_id)
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

    async def _ensure_automation_principal(self, organization_id: UUID) -> UUID:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await self._provisioned_principal_id(session, organization_id)

    async def _provisioned_principal_id(self, session: AsyncSession, organization_id: UUID) -> UUID:
        row = (
            await session.execute(
                _ENSURE_PRINCIPAL,
                {
                    "organization_id": organization_id,
                    "principal_kind": AUTOMATION_PRINCIPAL_KIND,
                    "external_subject": AUTOMATION_PRINCIPAL_SUBJECT,
                },
            )
        ).scalar_one()
        return cast(UUID, row)
