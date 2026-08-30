from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.application.recovery_impact_automation import (
    AUTOMATION_PRINCIPAL_KIND,
    AUTOMATION_PRINCIPAL_SUBJECT,
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


class RecoveryAutomationPrincipal:
    """The deterministic tenant-scoped system principal every operational
    recovery automation executes under, so durable facts attribute autonomous
    behavior to one reviewable actor per organization."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def ensure(self, organization_id: UUID) -> UUID:
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
