from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def require_execution(
    session: AsyncSession,
    organization_id: UUID,
    execution_id: UUID,
) -> RowMapping:
    sql = """
        SELECT * FROM request_engine.operational_recovery_executions
        WHERE organization_id = :organization_id AND id = :execution_id
    """
    return (
        (
            await session.execute(
                text(sql),
                {"organization_id": organization_id, "execution_id": execution_id},
            )
        )
        .mappings()
        .one()
    )
