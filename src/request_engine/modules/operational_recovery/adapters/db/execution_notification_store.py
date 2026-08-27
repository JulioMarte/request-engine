from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.execution_codec import (
    execution_from_row,
)
from request_engine.modules.operational_recovery.adapters.db.execution_row_store import (
    require_execution,
)
from request_engine.modules.operational_recovery.contracts.models import RecoveryExecution
from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def attach_communication_task(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    execution_id: UUID,
    communication_task_id: UUID,
) -> RecoveryExecution:
    sql = """
        UPDATE request_engine.operational_recovery_executions
        SET communication_task_id = :communication_task_id
        WHERE organization_id = :organization_id AND id = :execution_id
          AND status = 'succeeded' AND communication_task_id IS NULL
        RETURNING *
    """
    async with tenant_transaction(factory, organization_id) as session:
        row = (
            (
                await session.execute(
                    text(sql),
                    {
                        "organization_id": organization_id,
                        "execution_id": execution_id,
                        "communication_task_id": communication_task_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            row = await require_execution(session, organization_id, execution_id)
            current = cast(UUID | None, row["communication_task_id"])
            if current != communication_task_id:
                raise RuntimeError(
                    "recovery execution already references another communication task"
                )
    return execution_from_row(row)
