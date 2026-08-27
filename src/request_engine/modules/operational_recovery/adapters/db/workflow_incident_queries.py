from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.workflow_codec import incident_from_row
from request_engine.modules.operational_recovery.contracts.workflow import RecoveryIncident


async def get_incident_row(
    session: AsyncSession,
    *,
    organization_id: UUID,
    incident_id: UUID,
) -> RecoveryIncident | None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT * FROM request_engine.operational_recovery_incidents
                    WHERE organization_id = :organization_id AND id = :incident_id
                    """
                ),
                {"organization_id": organization_id, "incident_id": incident_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else incident_from_row(cast(RowMapping, row))


async def get_open_incident_row(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    lock: bool = False,
) -> RecoveryIncident | None:
    suffix = " FOR UPDATE" if lock else ""
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT * FROM request_engine.operational_recovery_incidents
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :service_queue_id
                      AND status <> 'resolved'
                    """
                    + suffix
                ),
                {"organization_id": organization_id, "service_queue_id": service_queue_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else incident_from_row(cast(RowMapping, row))
