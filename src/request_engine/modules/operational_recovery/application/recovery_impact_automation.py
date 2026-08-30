from typing import Protocol
from uuid import UUID


class RecoveryImpactAutomation(Protocol):
    """Contract 32 sections 13/14: the accepted autonomous communication policy.

    The scheduled handler executes the customer-impact communication with an
    explicit tenant-scoped system principal; capacity, schedule and intake
    mutations stay operator-only.
    """

    async def communicate_impact(
        self,
        *,
        organization_id: UUID,
        incident_id: UUID,
        source_revision: int,
        recipients: tuple[UUID, ...],
    ) -> None: ...


AUTOMATION_PRINCIPAL_KIND = "service"
AUTOMATION_PRINCIPAL_SUBJECT = "operational_recovery_automation"
AUTOMATION_CAPABILITY = "operational_recovery.communicate"
