from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import (
    action_from_row,
    incident_from_row,
)
from request_engine.modules.operational_recovery.adapters.db.workflow_incident_queries import (
    get_open_incident_row,
)
from request_engine.modules.operational_recovery.contracts.copilot import (
    CopilotRecoveryIncidentReader,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryIncident,
)
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
            return tuple(incident_from_row(row) for row in rows)

    async def get_action_by_idempotency(
        self,
        *,
        organization_id: UUID,
        principal_id: UUID,
        idempotency_key: str,
    ) -> RecoveryAction | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            """
                            SELECT *
                            FROM request_engine.operational_recovery_actions
                            WHERE organization_id=:organization_id
                              AND principal_id=:principal_id
                              AND idempotency_key=:idempotency_key
                            """
                        ),
                        {
                            "organization_id": organization_id,
                            "principal_id": principal_id,
                            "idempotency_key": idempotency_key,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            return action_from_row(row) if row is not None else None
