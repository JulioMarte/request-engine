from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.execution_codec import execution_from_row
from request_engine.modules.operational_recovery.contracts.models import RecoveryExecution, RecoveryExecutionStatus
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_SELECT = "SELECT * FROM request_engine.operational_recovery_executions WHERE organization_id = :organization_id AND id = :execution_id"
_SUCCEED = "UPDATE request_engine.operational_recovery_executions SET status = 'succeeded', resulting_reservation_revision = :resulting_revision, completed_at = clock_timestamp() WHERE organization_id = :organization_id AND id = :execution_id AND status = 'prepared' RETURNING *"
_REJECT = "UPDATE request_engine.operational_recovery_executions SET status = 'rejected', failure_code = :failure_code, completed_at = clock_timestamp() WHERE organization_id = :organization_id AND id = :execution_id AND status = 'prepared' RETURNING *"
_ATTACH = "UPDATE request_engine.operational_recovery_executions SET communication_task_id = :communication_task_id WHERE organization_id = :organization_id AND id = :execution_id AND status = 'succeeded' AND communication_task_id IS NULL RETURNING *"


async def _require_execution(session: AsyncSession, organization_id: UUID, execution_id: UUID) -> RowMapping:
    return ((await session.execute(text(_SELECT), {"organization_id": organization_id, "execution_id": execution_id})).mappings().one())


async def succeed_execution(factory: SessionFactory, *, organization_id: UUID, execution_id: UUID, resulting_revision: int) -> RecoveryExecution:
    async with tenant_transaction(factory, organization_id) as session:
        row = ((await session.execute(text(_SUCCEED), {"organization_id": organization_id, "execution_id": execution_id, "resulting_revision": resulting_revision})).mappings().one_or_none())
        if row is None:
            row = await _require_execution(session, organization_id, execution_id)
            if row["status"] != RecoveryExecutionStatus.SUCCEEDED.value or cast(int | None, row["resulting_reservation_revision"]) != resulting_revision:
                raise RuntimeError("recovery execution cannot transition to succeeded")
    return execution_from_row(row)


async def reject_execution(factory: SessionFactory, *, organization_id: UUID, execution_id: UUID, failure_code: str) -> RecoveryExecution:
    async with tenant_transaction(factory, organization_id) as session:
        row = ((await session.execute(text(_REJECT), {"organization_id": organization_id, "execution_id": execution_id, "failure_code": failure_code})).mappings().one_or_none())
        if row is None:
            row = await _require_execution(session, organization_id, execution_id)
            if row["status"] != RecoveryExecutionStatus.REJECTED.value or cast(str | None, row["failure_code"]) != failure_code:
                raise RuntimeError("recovery execution cannot transition to rejected")
    return execution_from_row(row)


async def attach_communication_task(factory: SessionFactory, *, organization_id: UUID, execution_id: UUID, communication_task_id: UUID) -> RecoveryExecution:
    async with tenant_transaction(factory, organization_id) as session:
        row = ((await session.execute(text(_ATTACH), {"organization_id": organization_id, "execution_id": execution_id, "communication_task_id": communication_task_id})).mappings().one_or_none())
        if row is None:
            row = await _require_execution(session, organization_id, execution_id)
            if cast(UUID | None, row["communication_task_id"]) != communication_task_id:
                raise RuntimeError("recovery execution already references another communication task")
    return execution_from_row(row)
