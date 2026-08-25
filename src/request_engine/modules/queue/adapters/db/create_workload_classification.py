from typing import cast

from sqlalchemy import text

from request_engine.modules.queue.adapters.db.workload_management_common import (
    record_workload_fact,
    workload_from_json,
    workload_from_row,
    workload_to_json,
)
from request_engine.modules.queue.application.live_commands import (
    CreateWorkloadClassificationCommand,
)
from request_engine.modules.queue.application.live_errors import WorkloadKeyConflict
from request_engine.modules.queue.contracts.live_queue import WorkloadClassification
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    command_fingerprint,
    complete_idempotency,
)


async def create_workload_classification(
    session_factory: SessionFactory,
    command: CreateWorkloadClassificationCommand,
) -> WorkloadClassification:
    fingerprint = command_fingerprint(
        "workload.create",
        {"workload_key": command.workload_key, "display_name": command.display_name},
    )
    async with tenant_transaction(session_factory, command.organization_id) as session:
        idem, replay = await acquire_idempotency(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            capability="workload.manage",
            idempotency_key=command.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is not None:
            return workload_from_json(cast(dict[str, object], replay["workload"]))
        inserted = await session.execute(
            text(
                "INSERT INTO request_engine.operational_workload_classifications "
                "(organization_id,workload_key,display_name) "
                "VALUES (:organization_id,btrim(:workload_key),btrim(:display_name)) "
                "ON CONFLICT (organization_id,workload_key) DO NOTHING "
                "RETURNING id,workload_key,display_name,active,revision"
            ),
            {
                "organization_id": command.organization_id,
                "workload_key": command.workload_key,
                "display_name": command.display_name,
            },
        )
        row = inserted.mappings().one_or_none()
        if row is None:
            raise WorkloadKeyConflict(command.workload_key.strip())
        result = workload_from_row(row)
        await record_workload_fact(
            session,
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            idempotency_id=idem,
            command_name="workload.create",
            workload=result,
            event_type="workload.classification_created.v1",
        )
        await complete_idempotency(session, idem, {"workload": workload_to_json(result)})
        return result
