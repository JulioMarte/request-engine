from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.execution_codec import (
    execution_from_row,
)
from request_engine.modules.operational_recovery.adapters.db.execution_row_store import (
    require_execution,
)
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RecoveryExecutionStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction


async def succeed_execution(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    execution_id: UUID,
    resulting_revision: int,
) -> RecoveryExecution:
    sql = """
        UPDATE request_engine.operational_recovery_executions
        SET status = 'succeeded', resulting_reservation_revision = :resulting_revision,
            completed_at = clock_timestamp()
        WHERE organization_id = :organization_id AND id = :execution_id
          AND status = 'prepared'
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
                        "resulting_revision": resulting_revision,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            row = await require_execution(session, organization_id, execution_id)
            current = cast(int | None, row["resulting_reservation_revision"])
            if row["status"] != RecoveryExecutionStatus.SUCCEEDED.value:
                raise RuntimeError("recovery execution cannot transition to succeeded")
            if current != resulting_revision:
                raise RuntimeError("recovery execution cannot transition to succeeded")
    return execution_from_row(row)


async def reject_execution(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    execution_id: UUID,
    failure_code: str,
) -> RecoveryExecution:
    sql = """
        UPDATE request_engine.operational_recovery_executions
        SET status = 'rejected', failure_code = :failure_code,
            completed_at = clock_timestamp()
        WHERE organization_id = :organization_id AND id = :execution_id
          AND status = 'prepared'
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
                        "failure_code": failure_code,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            row = await require_execution(session, organization_id, execution_id)
            current = cast(str | None, row["failure_code"])
            if row["status"] != RecoveryExecutionStatus.REJECTED.value:
                raise RuntimeError("recovery execution cannot transition to rejected")
            if current != failure_code:
                raise RuntimeError("recovery execution cannot transition to rejected")
    return execution_from_row(row)
