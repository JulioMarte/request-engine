from typing import Protocol
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident


class CopilotRecoveryIncidentReader(Protocol):
    async def get_open_incident_for_queue(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryIncident | None: ...

    async def find_open_incidents_for_resource(
        self,
        *,
        organization_id: UUID,
        resource_id: UUID,
    ) -> tuple[RecoveryIncident, ...]: ...
