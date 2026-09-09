from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def read_recovery_source_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
) -> int | None:
    return (
        await session.execute(
            text(
                "SELECT request_read.recovery_source_revision(:organization_id, :service_queue_id)"
            ),
            {"organization_id": organization_id, "service_queue_id": service_queue_id},
        )
    ).scalar_one_or_none()


async def lock_recovery_source_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
) -> int:
    return (
        await session.execute(
            text(
                "SELECT request_cmd.lock_recovery_source_revision("
                ":organization_id, :service_queue_id)"
            ),
            {"organization_id": organization_id, "service_queue_id": service_queue_id},
        )
    ).scalar_one()


class RecoverySourceRevisionReader:
    """Cheap advisory freshness read; the commit fence remains the authority."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def read(
        self,
        *,
        organization_id: UUID,
        service_queue_id: UUID,
    ) -> int | None:
        async with tenant_transaction(self._session_factory, organization_id) as session:
            return await read_recovery_source_revision(
                session,
                organization_id=organization_id,
                service_queue_id=service_queue_id,
            )
