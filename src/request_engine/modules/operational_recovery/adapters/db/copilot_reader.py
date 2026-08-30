from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import (
    incident_from_row,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_queries import (
    get_open_incident_row,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident
from request_engine.platform.db.session import SessionFactory, tenant_transaction


class PostgresCopilotRecoveryIncidentReader(CopilotRecoveryIncidentReader):
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def get_open_incident_for_queue(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> RecoveryIncident | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await get_open_incident_row(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
            )

    async def find_open_incidents_for_resource(
        self,
        *,
        organization_id: UUID,
        resource_id: UUID,
    ) -> tuple[RecoveryIncident, ...]:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT *
                        FROM request_engine.operational_recovery_incidents
                        WHERE organization_id=:organization_id
                          AND resource_id=:resource_id
                          AND status <> 'resolved'
                        ORDER BY id
                        """
                    ),
                    {"organization_id": organization_id, "resource_id": resource_id},
                )
            ).mappings()
            return tuple(incident_from_row(cast(object, row)) for row in rows)
